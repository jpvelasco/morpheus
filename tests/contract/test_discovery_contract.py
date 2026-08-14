"""Phase 12 discovery contracts: schema envelope, fingerprint, missing evidence."""

from __future__ import annotations

import pytest

from morpheus.core.discovery import CapabilityValue, machine_fingerprint, normalize_capabilities
from morpheus.core.records import (
    AcceleratorFacts,
    CapabilityProfile,
    HostProfile,
    SchemaVersionError,
    StorageFacts,
    decode_record,
    encode_record,
)


def _profile(
    *,
    machine_id: str = "0" * 64,
    accelerators: tuple[AcceleratorFacts, ...] = (),
    memory_bytes: int | None = 32 * 1024**3,
    container_runtime: str | None = None,
) -> HostProfile:
    return HostProfile(
        profile_version=1,
        machine_id=machine_id,
        platform="linux",
        architecture="x86_64",
        cpu_cores=8,
        cpu_features=("avx2",),
        memory_bytes=memory_bytes,
        accelerators=accelerators,
        storage=(StorageFacts(category="system", total_bytes=1024**4),),
        os_version="6.8.0-45-generic",
        container_runtime=container_runtime,
        driver_versions=(),
    )


def _sources() -> dict[str, CapabilityValue]:
    return {
        "memory": CapabilityValue.KNOWN,
        "cpu": CapabilityValue.KNOWN,
        "storage": CapabilityValue.KNOWN,
        "accelerator": CapabilityValue.KNOWN,
        "driver": CapabilityValue.KNOWN,
        "container": CapabilityValue.UNAVAILABLE,
    }


def test_discovery_contract_host_profile_round_trips_through_the_codec() -> None:
    profile = _profile(
        accelerators=(
            AcceleratorFacts(
                vendor="nvidia",
                name="RTX 4070 Ti Super",
                device_id="GPU-abc",
                memory_bytes=16 * 1024**3,
                topology=("pcie-00000000-01-00-0",),
                capabilities=("cuda",),
                state="available",
            ),
        ),
        container_runtime="docker",
    )
    restored = decode_record(encode_record(profile))
    assert restored == profile
    assert restored.record_id == profile.record_id
    assert restored.schema_version == 1


def test_discovery_contract_capability_profile_round_trips_through_the_codec() -> None:
    capabilities = normalize_capabilities(_profile(), source_states=_sources())
    restored = decode_record(encode_record(capabilities))
    assert restored == capabilities
    assert isinstance(restored, CapabilityProfile)


def test_discovery_contract_envelope_rejects_unknown_payload_fields() -> None:
    payload = _profile().public_dict()
    payload["hostname"] = "secret-host"
    envelope = {
        "record_type": "host_profile",
        "schema_version": 1,
        "record_id": payload["machine_id"],
        "payload": payload,
    }
    import json

    with pytest.raises(ValueError, match="exactly its declared fields"):
        decode_record(json.dumps(envelope).encode())


def test_discovery_contract_rejects_unsupported_schema_version() -> None:
    envelope = {
        "record_type": "host_profile",
        "schema_version": 99,
        "record_id": "0" * 64,
        "payload": _profile().public_dict(),
    }
    import json

    with pytest.raises(SchemaVersionError):
        decode_record(json.dumps(envelope).encode())


def test_discovery_contract_fingerprint_is_deterministic_across_fixtures() -> None:
    profiles = (
        _profile(),
        _profile(machine_id="1" * 64, memory_bytes=64 * 1024**3),
        _profile(
            machine_id="2" * 64,
            accelerators=(
                AcceleratorFacts(
                    vendor="nvidia",
                    name="GPU",
                    device_id="GPU-x",
                    memory_bytes=8 * 1024**3,
                    topology=(),
                    capabilities=("cuda",),
                    state="available",
                ),
            ),
        ),
    )
    for profile in profiles:
        first = machine_fingerprint(profile)
        second = machine_fingerprint(profile)
        assert first == second
        assert len(first) == 64


def test_discovery_contract_machine_id_is_the_stable_fingerprint() -> None:
    profile = _profile(machine_id="pending")
    from morpheus.core.discovery import fingerprint_profile

    bound = fingerprint_profile(profile)
    assert bound.machine_id == machine_fingerprint(profile)
    assert bound.record_id == bound.machine_id


def test_discovery_contract_plat_001_values_are_exactly_the_four_states() -> None:
    expected = {"known", "unavailable", "permission_denied", "unsupported"}
    capabilities = normalize_capabilities(_profile(), source_states=_sources())
    states = {
        capabilities.memory_state,
        capabilities.storage_state,
        capabilities.accelerator_state,
        capabilities.accelerator_memory_state,
        capabilities.driver_state,
    }
    assert states <= expected
    assert CapabilityValue(value="known") is CapabilityValue.KNOWN
    assert CapabilityValue(value="permission_denied") is CapabilityValue.PERMISSION_DENIED


def test_discovery_contract_missing_evidence_is_never_zero_capacity() -> None:
    sources = _sources()
    sources["memory"] = CapabilityValue.PERMISSION_DENIED
    sources["storage"] = CapabilityValue.UNSUPPORTED
    capabilities = normalize_capabilities(_profile(), source_states=sources)
    assert capabilities.memory_bytes is None
    assert capabilities.storage_bytes is None
    assert capabilities.missing_evidence == ("memory", "storage")


def test_discovery_contract_capability_amounts_require_known_state() -> None:
    sources = _sources()
    sources["accelerator"] = CapabilityValue.PERMISSION_DENIED
    capabilities = normalize_capabilities(
        _profile(
            accelerators=(
                AcceleratorFacts(
                    vendor="nvidia",
                    name="GPU",
                    device_id="GPU-x",
                    memory_bytes=8 * 1024**3,
                    topology=(),
                    capabilities=("cuda",),
                    state="available",
                ),
            ),
        ),
        source_states=sources,
    )
    assert capabilities.accelerator_count is None
    assert capabilities.accelerator_memory_bytes is None


def test_discovery_contract_invalid_state_amount_pair_is_rejected() -> None:
    from morpheus.core.records import CapabilityProfile

    with pytest.raises(ValueError, match="amount must be unknown"):
        CapabilityProfile(
            machine_id="0" * 64,
            memory_state="permission_denied",
            memory_bytes=1024,
            storage_state="known",
            storage_bytes=2048,
            accelerator_state="known",
            accelerator_count=0,
            accelerator_memory_state="known",
            accelerator_memory_bytes=0,
            driver_state="known",
            container_runtime=None,
            supported_formats=("gguf",),
            features=(),
            missing_evidence=(),
        )


def test_discovery_contract_nvidia_rows_build_exact_typed_facts() -> None:
    from morpheus.core.discovery import parse_nvidia_smi_csv

    fixture = (
        "index, name, uuid, bus_id, memory.total, memory.used, "
        "driver_version, utilization.gpu, temperature.gpu\n"
        "0, RTX 4070 Ti Super, GPU-abc, 00000000:01:00.0, 16384, 831, "
        "550.54.14, 42, 55\n"
    )
    rows = parse_nvidia_smi_csv(fixture)
    assert len(rows) == 1
    values = dict(rows[0])
    assert values["uuid"] == "GPU-abc"
    assert values["bus_id"] == "00000000:01:00.0"
    assert values["driver_version"] == "550.54.14"
    assert values["utilization.gpu"] == "42"
