"""Guarded real-host capture lane (12.4): no capture without explicit authority."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from morpheus.core.discovery import DiscoveryResult
from morpheus.core.export import assert_export_is_private, export_discovery_result
from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.core.records import CapabilityProfile

_AUTHORIZATION_TOKEN = "morpheus-capture-authorized"  # noqa: S105  # nosec B105 - gate token


class CaptureCollector(Protocol):
    def collect(self) -> DiscoveryResult: ...


class CaptureAuthorizationError(RuntimeError):
    """A capture lane was entered without explicit host authorization."""


def guarded_capture(
    collector: CaptureCollector,
    *,
    authorized: bool,
    host_name: str,
    artifact_root: Path,
    capability_profile: CapabilityProfile,
) -> str:
    """Capture and retain a privacy-checked profile, or refuse without authority."""
    if not authorized:
        raise CaptureAuthorizationError(
            "host capture requires explicit authorization for a named host"
        )
    if not host_name or "/" in host_name or "\\" in host_name or ".." in host_name:
        raise ValueError("host capture requires a bounded host name")

    result = collector.collect()
    exported = export_discovery_result(result, capability_profile, include_utilization=True)
    assert_export_is_private(exported)

    resolver = OwnedPathResolver(artifact_root)
    fingerprint = result.profile.machine_id[:16]
    destination = resolver.resolve(f"{host_name}-{fingerprint}.json")
    staged = resolver.resolve(f"{host_name}-{fingerprint}.json.staged")
    try:
        staged.write_text(json.dumps(exported, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staged.replace(destination)
    except (OSError, OwnedPathError) as error:
        with suppress(OSError):
            staged.unlink(missing_ok=True)
        raise OwnedPathError(f"cannot retain host capture: {error}") from error
    return str(destination)


def authorization_token() -> str:
    """The token an operator must explicitly supply to authorize a capture."""
    return _AUTHORIZATION_TOKEN
