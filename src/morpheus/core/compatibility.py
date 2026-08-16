"""Desktop compatibility handshake core (DESK-002).

Pure, dependency-free semantic-version range checks used by the
`/api/v1/system/compatibility` handshake. The desktop supplies its semantic
version in `X-Morpheus-Desktop-Version`; the response reports API and backend
versions, the supported desktop version range, OS and architecture, enabled
adapter identities and tiers, supported operations, and compatibility status.
"""

from __future__ import annotations

import platform
import re
from typing import Any

_SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

API_VERSION = 1
DESKTOP_MINIMUM = "0.1.0"
DESKTOP_MAXIMUM = "0.1.0"

# Adapter identities and tiers advertised by the compatibility handshake.
# Tier policy follows the Phase 15 contract: llama.cpp is the common stable
# path, vLLM is an additional Linux NVIDIA tier validated in Phase 18.
ADAPTERS = (
    {"id": "llama.cpp", "tier": "stable"},
    {"id": "vllm", "tier": "linux-nvidia"},
)

# Operations the Control API exposes to desktop and browser surfaces alike.
OPERATIONS = (
    "session",
    "health",
    "models",
    "capabilities",
    "navigation",
    "controls",
    "metrics",
    "events",
    "benchmarks",
    "analytics",
    "settings",
    "workflows",
    "recovery",
)


class CompatibilityError(ValueError):
    """A semantic version or compatibility input is malformed."""


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse a strict ``major.minor.patch`` semantic version."""
    match = _SEMVER_PATTERN.match(value)
    if match is None:
        raise CompatibilityError(f"not a major.minor.patch semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_in_range(value: str, minimum: str, maximum: str) -> bool:
    """Return whether ``value`` falls inside the inclusive version range."""
    parsed = parse_semver(value)
    return parse_semver(minimum) <= parsed <= parse_semver(maximum)


def desktop_compatibility(
    *,
    desktop_version: str | None,
    backend_version: str,
    desktop_minimum: str = DESKTOP_MINIMUM,
    desktop_maximum: str = DESKTOP_MAXIMUM,
) -> dict[str, Any]:
    """Classify the desktop/backend compatibility state.

    The desktop is expected to always send its semantic version. A missing
    version is reported as ``missing_desktop_version`` rather than silently
    treated as compatible, keeping the handshake honest for non-desktop
    clients.
    """
    if desktop_version is None:
        return {
            "status": "missing_desktop_version",
            "backend_version": backend_version,
        }
    supported = {
        "min": desktop_minimum,
        "max": desktop_maximum,
    }
    if version_in_range(desktop_version, desktop_minimum, desktop_maximum):
        return {
            "status": "compatible",
            "desktop_version": desktop_version,
            "backend_version": backend_version,
            "supported_desktop_range": supported,
        }
    return {
        "status": "unsupported_desktop",
        "desktop_version": desktop_version,
        "backend_version": backend_version,
        "supported_desktop_range": supported,
    }


def compatibility_payload(
    *,
    backend_version: str,
    desktop_version: str | None,
    os_name: str | None = None,
    architecture: str | None = None,
    adapters: tuple[dict[str, str], ...] = ADAPTERS,
    operations: tuple[str, ...] = OPERATIONS,
) -> dict[str, Any]:
    """Build the versioned compatibility handshake payload."""
    return {
        "schema_version": API_VERSION,
        "api_version": API_VERSION,
        "backend_version": backend_version,
        "os": os_name or platform.system().lower(),
        "architecture": architecture or platform.machine(),
        "adapters": list(adapters),
        "operations": list(operations),
        "compatibility": desktop_compatibility(
            desktop_version=desktop_version,
            backend_version=backend_version,
        ),
    }
