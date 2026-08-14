"""Privacy-reviewed, deterministic profile export (HOST-001/002 validation)."""

from __future__ import annotations

import json
import re
from datetime import UTC
from typing import Any, Protocol

from morpheus.core.discovery import DiscoveryResult
from morpheus.core.records import CapabilityProfile

_SECRET_SHAPED_KEY = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|credential|auth[_-]?header|private[_-]?key)",
    re.IGNORECASE,
)


class _PublicDictRecord(Protocol):
    def public_dict(self) -> dict[str, Any]: ...


def _record_export(record: _PublicDictRecord) -> dict[str, Any]:
    return record.public_dict()


def export_discovery_result(
    result: DiscoveryResult,
    capability_profile: CapabilityProfile,
    include_utilization: bool = True,
) -> dict[str, Any]:
    """Deterministic, privacy-reviewed export of a discovery result."""
    utilization = None
    if include_utilization:
        utilization = {
            "observed_at": result.utilization.observed_at.astimezone(UTC).isoformat(),
            "load_average_1m": result.utilization.load_average_1m,
            "memory_available_bytes": result.utilization.memory_available_bytes,
            "free_bytes_by_storage": [
                [name, free] for name, free in result.utilization.free_bytes_by_storage
            ],
            "accelerators": [
                {
                    "device_id": acc.device_id,
                    "memory_used_bytes": acc.memory_used_bytes,
                    "utilization_percent": acc.utilization_percent,
                }
                for acc in result.utilization.accelerators
            ],
        }
    return {
        "schema_version": 1,
        "profile": _record_export(result.profile),
        "capability_profile": _record_export(capability_profile),
        "utilization": utilization,
        "source_states": [[name, state] for name, state in result.source_states],
    }


def export_to_json(
    result: DiscoveryResult,
    capability_profile: CapabilityProfile,
    include_utilization: bool = True,
) -> str:
    """Render the canonical JSON document with a stable key order."""
    return json.dumps(
        export_discovery_result(result, capability_profile, include_utilization),
        indent=2,
        sort_keys=True,
    )


def privacy_violations(exported: dict[str, Any]) -> tuple[str, ...]:
    """Return secret-shaped fields found in an export."""
    violations: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else key
                if _SECRET_SHAPED_KEY.search(key) and value not in (None, "", [], {}):
                    violations.append(f"{child} looks like a secret value")
                walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(exported, "")
    return tuple(violations)


def assert_export_is_private(exported: dict[str, Any]) -> None:
    """Raise on any secret-shaped field so captures never retain secrets."""
    violations = privacy_violations(exported)
    if violations:
        raise ValueError("export contains secret-shaped fields: " + "; ".join(violations))
