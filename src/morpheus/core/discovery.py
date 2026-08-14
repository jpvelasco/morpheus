"""Pure discovery domain: fingerprints, capability normalization, parsers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum

from morpheus.core.records import AcceleratorFacts, CapabilityProfile, HostProfile

_MEMINFO_LINE = re.compile(r"^(MemTotal|MemAvailable):\s+(\d+)\s+kB$")
_FEATURE_LINE = re.compile(r"^flags\s*:")


class CapabilityValue(StrEnum):
    """PLAT-001 capability values; missing evidence is never zero or false."""

    KNOWN = "known"
    UNAVAILABLE = "unavailable"
    PERMISSION_DENIED = "permission_denied"
    UNSUPPORTED = "unsupported"


def parse_meminfo_bytes(text: str) -> dict[str, int]:
    """Parse /proc/meminfo KiB values into bytes for the named keys."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        match = _MEMINFO_LINE.fullmatch(line.strip())
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    return values


def parse_cpu_features(text: str) -> tuple[str, ...]:
    """Extract the sorted, deduplicated CPU feature flag set."""
    features: set[str] = set()
    for line in text.splitlines():
        if _FEATURE_LINE.match(line):
            _, _, raw = line.partition(":")
            features.update(raw.split())
    return tuple(sorted(features))


def parse_nvidia_smi_csv(text: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Parse nvidia-smi CSV output into header-mapped rows, skipping malformed rows."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ()
    header = [field.strip() for field in lines[0].split(",")]
    rows: list[tuple[tuple[str, str], ...]] = []
    for line in lines[1:]:
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != len(header):
            continue
        rows.append(tuple(zip(header, fields, strict=True)))
    return tuple(rows)


def parse_docker_version_json(text: str) -> dict[str, str]:
    """Extract client and server versions from `docker version --format {{json .}}`."""
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("docker version must be a JSON object")
    versions: dict[str, str] = {}
    for side in ("Client", "Server"):
        section = document.get(side)
        if not isinstance(section, dict):
            continue
        version = section.get("Version")
        if isinstance(version, str):
            versions[side.lower()] = version
    return versions


def machine_fingerprint(profile: HostProfile) -> str:
    """Stable identity hash over every non-volatile profile field."""
    data = asdict(profile)
    data.pop("machine_id")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _amount[T](state: CapabilityValue, value: T | None) -> tuple[CapabilityValue, T | None]:
    if state is CapabilityValue.KNOWN:
        return state, value
    return state, None


def normalize_capabilities(
    profile: HostProfile,
    *,
    source_states: Mapping[str, CapabilityValue],
    supported_formats: tuple[str, ...] = ("gguf",),
    features: tuple[str, ...] = (),
) -> CapabilityProfile:
    """Normalize discovery evidence into PLAT-001 typed capability values."""
    known_sources = frozenset({"memory", "cpu", "storage", "accelerator", "driver", "container"})
    unknown = {name for name in source_states if name not in known_sources}
    if unknown:
        raise ValueError(f"unknown evidence source names: {', '.join(sorted(unknown))}")

    memory_state, memory_bytes = _amount(
        source_states.get("memory", CapabilityValue.PERMISSION_DENIED), profile.memory_bytes
    )
    storage_total = None
    if profile.storage:
        storage_total = min(entry.total_bytes for entry in profile.storage)
    storage_state, storage_bytes = _amount(
        source_states.get("storage", CapabilityValue.PERMISSION_DENIED),
        storage_total,
    )
    accelerator_state, accelerator_count = _amount(
        source_states.get("accelerator", CapabilityValue.PERMISSION_DENIED),
        len(profile.accelerators),
    )
    accelerator_memory_state, accelerator_memory_bytes = _amount(
        source_states.get("accelerator", CapabilityValue.PERMISSION_DENIED),
        _combined_accelerator_memory(profile.accelerators),
    )
    driver_state, _ = _amount(source_states.get("driver", CapabilityValue.PERMISSION_DENIED), None)
    container_state, container_runtime = _amount(
        source_states.get("container", CapabilityValue.PERMISSION_DENIED),
        profile.container_runtime,
    )
    missing_evidence = tuple(
        sorted(
            name
            for name, state in source_states.items()
            if state
            in {
                CapabilityValue.PERMISSION_DENIED,
                CapabilityValue.UNSUPPORTED,
            }
        )
    )
    return CapabilityProfile(
        machine_id=profile.machine_id,
        memory_state=memory_state.value,
        memory_bytes=memory_bytes,
        storage_state=storage_state.value,
        storage_bytes=storage_bytes,
        accelerator_state=accelerator_state.value,
        accelerator_count=accelerator_count,
        accelerator_memory_state=accelerator_memory_state.value,
        accelerator_memory_bytes=accelerator_memory_bytes,
        driver_state=driver_state.value,
        container_runtime=container_runtime,
        supported_formats=supported_formats,
        features=features,
        missing_evidence=missing_evidence,
    )


def _combined_accelerator_memory(accelerators: tuple[AcceleratorFacts, ...]) -> int | None:
    if not accelerators:
        return 0
    if any(accelerator.memory_bytes is None for accelerator in accelerators):
        return None
    return sum(memory for memory in (a.memory_bytes for a in accelerators) if memory is not None)


def fingerprint_profile(profile: HostProfile) -> HostProfile:
    """Return the profile with its machine identity bound to the stable fingerprint."""
    return replace(profile, machine_id=machine_fingerprint(profile))


@dataclass(frozen=True, slots=True)
class AcceleratorUtilization:
    device_id: str
    memory_used_bytes: int | None
    utilization_percent: int | None


@dataclass(frozen=True, slots=True)
class UtilizationSnapshot:
    observed_at: datetime
    load_average_1m: float | None
    memory_available_bytes: int | None
    free_bytes_by_storage: tuple[tuple[str, int], ...]
    accelerators: tuple[AcceleratorUtilization, ...]

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("utilization timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    profile: HostProfile
    utilization: UtilizationSnapshot
    source_states: tuple[tuple[str, str], ...]

    @property
    def source_state(self) -> dict[str, CapabilityValue]:
        return {name: CapabilityValue(state) for name, state in self.source_states}


__all__ = [
    "AcceleratorUtilization",
    "CapabilityValue",
    "DiscoveryResult",
    "UtilizationSnapshot",
    "fingerprint_profile",
    "machine_fingerprint",
    "normalize_capabilities",
    "parse_cpu_features",
    "parse_docker_version_json",
    "parse_meminfo_bytes",
    "parse_nvidia_smi_csv",
]
