from __future__ import annotations

import pytest

from morpheus.core.records import (
    AcceleratorFacts,
    CapabilityProfile,
    DriverFacts,
    HostProfile,
    StorageFacts,
)


def _facts(**overrides: object) -> AcceleratorFacts:
    values: dict[str, object] = {
        "vendor": "nvidia",
        "name": "RTX 4070 Ti Super",
        "device_id": "GPU-abc",
        "memory_bytes": 16 * 1024**3,
        "topology": (),
        "capabilities": ("cuda",),
        "state": "available",
    }
    values.update(overrides)
    return AcceleratorFacts(**values)  # type: ignore[arg-type]


def _profile(**overrides: object) -> HostProfile:
    values: dict[str, object] = {
        "profile_version": 1,
        "machine_id": "0" * 64,
        "platform": "linux",
        "architecture": "x86_64",
        "cpu_cores": 8,
        "cpu_features": (),
        "memory_bytes": 32 * 1024**3,
        "accelerators": (),
        "storage": (StorageFacts(category="system", total_bytes=1024**4),),
        "os_version": "6.8.0-45-generic",
        "container_runtime": None,
        "driver_versions": (),
    }
    values.update(overrides)
    return HostProfile(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"profile_version": 0},
        {"machine_id": "bad;id"},
        {"platform": "lin ux"},
        {"architecture": "x;86"},
        {"cpu_cores": 0},
        {"cpu_features": ("bad flag;",)},
        {"memory_bytes": 0},
        {"accelerators": (object(),)},
        {"storage": ("not-facts",)},
        {"os_version": "v1; rm -rf"},
        {"container_runtime": "bad;runtime"},
        {"driver_versions": (object(),)},
    ],
)
def test_host_profile_rejects_invalid_payloads(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _profile(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"vendor": "bad;vendor"},
        {"name": "bad;name"},
        {"device_id": "bad device"},
        {"memory_bytes": 0},
        {"topology": ("bad topology",)},
        {"capabilities": ("bad;cap",)},
        {"state": "bad state"},
    ],
)
def test_accelerator_facts_rejects_invalid_payloads(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _facts(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "bad category"},
        {"total_bytes": 0},
    ],
)
def test_storage_facts_rejects_invalid_payloads(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {"category": "system", "total_bytes": 1024}
    values.update(overrides)
    with pytest.raises(ValueError):
        StorageFacts(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "bad kind"},
        {"version": "bad version"},
    ],
)
def test_driver_facts_rejects_invalid_payloads(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {"kind": "nvidia-cuda", "version": "550.54.14"}
    values.update(overrides)
    with pytest.raises(ValueError):
        DriverFacts(**values)  # type: ignore[arg-type]


def _capabilities(**overrides: object) -> CapabilityProfile:
    values: dict[str, object] = {
        "machine_id": "0" * 64,
        "memory_state": "known",
        "memory_bytes": 1024,
        "storage_state": "known",
        "storage_bytes": 2048,
        "accelerator_state": "unavailable",
        "accelerator_count": 0,
        "accelerator_memory_state": "known",
        "accelerator_memory_bytes": 0,
        "driver_state": "known",
        "container_runtime": None,
        "supported_formats": ("gguf",),
        "features": (),
        "missing_evidence": (),
    }
    values.update(overrides)
    return CapabilityProfile(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"machine_id": "bad;id"},
        {"memory_state": "unknown"},
        {"supported_formats": ("bad format;",)},
        {"features": ("bad feature;",)},
        {"missing_evidence": ("bad evidence",)},
        {"container_runtime": "bad;runtime"},
    ],
)
def test_capability_profile_rejects_invalid_payloads(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _capabilities(**overrides)


def test_capability_profile_accepts_zero_amounts_for_known_unavailable_state() -> None:
    capabilities = _capabilities()
    assert capabilities.accelerator_count == 0
    assert capabilities.accelerator_memory_bytes == 0
