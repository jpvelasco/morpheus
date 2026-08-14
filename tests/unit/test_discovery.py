from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from morpheus.core.discovery import (
    CapabilityValue,
    UtilizationSnapshot,
    machine_fingerprint,
    normalize_capabilities,
    parse_cpu_features,
    parse_docker_version_json,
    parse_meminfo_bytes,
    parse_nvidia_smi_csv,
)
from morpheus.core.records import (
    AcceleratorFacts,
    DriverFacts,
    HostProfile,
    StorageFacts,
)


def _profile(**overrides: object) -> HostProfile:
    values: dict[str, object] = {
        "profile_version": 1,
        "machine_id": "0" * 64,
        "platform": "linux",
        "architecture": "x86_64",
        "cpu_cores": 8,
        "cpu_features": ("avx2", "sse4_1"),
        "memory_bytes": 64 * 1024**3,
        "accelerators": (
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
        "storage": (StorageFacts(category="system", total_bytes=2 * 1024**4),),
        "os_version": "6.8.0-45-generic",
        "container_runtime": "docker",
        "driver_versions": (DriverFacts(kind="nvidia-cuda", version="550.54.14"),),
    }
    values.update(overrides)
    return HostProfile(**values)  # type: ignore[arg-type]


def _known_sources() -> dict[str, CapabilityValue]:
    return {
        "memory": CapabilityValue.KNOWN,
        "cpu": CapabilityValue.KNOWN,
        "storage": CapabilityValue.KNOWN,
        "accelerator": CapabilityValue.KNOWN,
        "driver": CapabilityValue.KNOWN,
        "container": CapabilityValue.KNOWN,
    }


def test_parse_meminfo_bytes_reads_total_and_available_in_bytes() -> None:
    fixture = "MemTotal:       1000 kB\nMemFree: 100 kB\nMemAvailable: 600 kB\n"
    assert parse_meminfo_bytes(fixture) == {
        "MemTotal": 1_024_000,
        "MemAvailable": 614_400,
    }


def test_parse_meminfo_bytes_ignores_other_lines_and_missing_keys() -> None:
    fixture = "MemFree: 100 kB\nBuffers: 50 kB\n"
    assert parse_meminfo_bytes(fixture) == {}


def test_parse_cpu_features_deduplicates_and_sorts() -> None:
    fixture = "flags\t\t: avx2 sse4_1\nflags : sse4_1 avx512f\nmodel name : x\n"
    assert parse_cpu_features(fixture) == ("avx2", "avx512f", "sse4_1")


def test_parse_nvidia_smi_csv_maps_rows_by_header() -> None:
    fixture = "index, name, memory.total\n0, GPU, 16384\n1, GPU B, 8192\n"
    rows = parse_nvidia_smi_csv(fixture)
    assert len(rows) == 2
    assert dict(rows[0]) == {"index": "0", "name": "GPU", "memory.total": "16384"}
    assert dict(rows[1])["name"] == "GPU B"


def test_parse_nvidia_smi_csv_skips_malformed_rows_and_empty_input() -> None:
    fixture = "index, name\n0, GPU\nmalformed\n"
    rows = parse_nvidia_smi_csv(fixture)
    assert len(rows) == 1
    assert parse_nvidia_smi_csv("") == ()


def test_parse_docker_version_json_extracts_both_sides() -> None:
    fixture = json.dumps({"Client": {"Version": "29.6.2"}, "Server": {"Version": "29.6.2"}})
    assert parse_docker_version_json(fixture) == {
        "client": "29.6.2",
        "server": "29.6.2",
    }


def test_parse_docker_version_json_reports_missing_server() -> None:
    fixture = json.dumps({"Client": {"Version": "29.6.2"}})
    assert parse_docker_version_json(fixture) == {"client": "29.6.2"}


def test_parse_docker_version_json_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_docker_version_json("[1, 2]")


def test_machine_fingerprint_is_stable_across_identical_profiles() -> None:
    assert machine_fingerprint(_profile()) == machine_fingerprint(_profile())


def test_machine_fingerprint_excludes_the_machine_id_itself() -> None:
    first = machine_fingerprint(_profile(machine_id="0" * 64))
    second = machine_fingerprint(_profile(machine_id="1" * 64))
    assert first == second


def test_machine_fingerprint_changes_when_stable_facts_change() -> None:
    assert machine_fingerprint(_profile()) != machine_fingerprint(
        _profile(memory_bytes=128 * 1024**3)
    )


def test_normalize_capabilities_known_full_evidence() -> None:
    profile = _profile()
    capabilities = normalize_capabilities(profile, source_states=_known_sources())
    assert capabilities.memory_state == "known"
    assert capabilities.memory_bytes == profile.memory_bytes
    assert capabilities.accelerator_state == "known"
    assert capabilities.accelerator_count == 1
    assert capabilities.accelerator_memory_bytes == 16 * 1024**3
    assert capabilities.storage_bytes == 2 * 1024**4
    assert capabilities.driver_state == "known"
    assert capabilities.container_runtime == "docker"
    assert capabilities.supported_formats == ("gguf",)
    assert capabilities.missing_evidence == ()


def test_normalize_capabilities_cpu_only_is_zero_not_unknown() -> None:
    capabilities = normalize_capabilities(
        _profile(accelerators=()),
        source_states=_known_sources(),
    )
    assert capabilities.accelerator_state == "known"
    assert capabilities.accelerator_count == 0
    assert capabilities.accelerator_memory_bytes == 0


def test_normalize_capabilities_permission_denied_never_becomes_zero() -> None:
    sources = _known_sources()
    sources["memory"] = CapabilityValue.PERMISSION_DENIED
    sources["accelerator"] = CapabilityValue.UNSUPPORTED
    capabilities = normalize_capabilities(_profile(), source_states=sources)
    assert capabilities.memory_state == "permission_denied"
    assert capabilities.memory_bytes is None
    assert capabilities.accelerator_state == "unsupported"
    assert capabilities.accelerator_count is None
    assert capabilities.accelerator_memory_bytes is None
    assert capabilities.missing_evidence == ("accelerator", "memory")


def test_normalize_capabilities_partial_accelerator_memory_is_unknown() -> None:
    profile = _profile(
        accelerators=(
            AcceleratorFacts(
                vendor="nvidia",
                name="GPU A",
                device_id="GPU-a",
                memory_bytes=8 * 1024**3,
                topology=(),
                capabilities=("cuda",),
                state="available",
            ),
            AcceleratorFacts(
                vendor="nvidia",
                name="GPU B",
                device_id="GPU-b",
                memory_bytes=None,
                topology=(),
                capabilities=("cuda",),
                state="available",
            ),
        )
    )
    capabilities = normalize_capabilities(profile, source_states=_known_sources())
    assert capabilities.accelerator_count == 2
    assert capabilities.accelerator_memory_bytes is None


def test_normalize_capabilities_rejects_unknown_source_names() -> None:
    with pytest.raises(ValueError, match="unknown evidence source"):
        normalize_capabilities(_profile(), source_states={"shell": CapabilityValue.KNOWN})


def test_utilization_snapshot_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        UtilizationSnapshot(
            observed_at=datetime.fromisoformat("2026-01-01T00:00:00"),
            load_average_1m=None,
            memory_available_bytes=None,
            free_bytes_by_storage=(),
            accelerators=(),
        )


def test_utilization_snapshot_accepts_aware_timestamp() -> None:
    snapshot = UtilizationSnapshot(
        observed_at=datetime.now(UTC),
        load_average_1m=0.5,
        memory_available_bytes=1024,
        free_bytes_by_storage=(("system", 2048),),
        accelerators=(),
    )
    assert snapshot.load_average_1m == 0.5
