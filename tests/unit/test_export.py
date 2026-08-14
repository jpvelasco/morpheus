"""Unit tests for the 12.4 privacy-reviewed export and guarded capture lanes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from morpheus.capture import (
    CaptureAuthorizationError,
    authorization_token,
    guarded_capture,
)
from morpheus.core.discovery import (
    AcceleratorUtilization,
    CapabilityValue,
    DiscoveryResult,
    UtilizationSnapshot,
)
from morpheus.core.export import (
    assert_export_is_private,
    export_discovery_result,
    export_to_json,
    privacy_violations,
)
from morpheus.core.records import CapabilityProfile, HostProfile

_MACHINE_ID = "a" * 64
_NOW = datetime(2026, 8, 13, 1, tzinfo=UTC)


def _profile(hostname: str = "devbox") -> HostProfile:
    return HostProfile(
        profile_version=1,
        machine_id=_MACHINE_ID,
        platform="linux",
        architecture="x86_64",
        cpu_cores=8,
        cpu_features=("avx2",),
        memory_bytes=1_000_000,
        accelerators=(),
        storage=(),
        os_version="6.8.0",
        container_runtime="docker",
        driver_versions=(),
    )


def _result(hostname: str = "devbox") -> DiscoveryResult:
    return DiscoveryResult(
        profile=_profile(hostname),
        utilization=UtilizationSnapshot(
            observed_at=_NOW,
            load_average_1m=0.5,
            memory_available_bytes=500_000,
            free_bytes_by_storage=(("system", 200),),
            accelerators=(
                AcceleratorUtilization(
                    device_id="0", memory_used_bytes=100, utilization_percent=42
                ),
            ),
        ),
        source_states=(("memory", CapabilityValue.KNOWN.value),),
    )


def _capabilities() -> CapabilityProfile:
    return CapabilityProfile(
        machine_id=_MACHINE_ID,
        memory_state="known",
        memory_bytes=1_000_000,
        storage_state="known",
        storage_bytes=2_000_000,
        accelerator_state="unavailable",
        accelerator_count=None,
        accelerator_memory_state="unavailable",
        accelerator_memory_bytes=None,
        driver_state="unavailable",
        container_runtime="docker",
        supported_formats=("gguf",),
        features=(),
        missing_evidence=(),
    )


class _Collector:
    def __init__(self, result: DiscoveryResult) -> None:
        self._result = result

    def collect(self) -> DiscoveryResult:
        return self._result


class TestExport:
    def test_export_is_deterministic_and_private(self) -> None:
        exported = export_discovery_result(_result(), _capabilities())
        assert export_discovery_result(_result(), _capabilities()) == exported
        assert privacy_violations(exported) == ()
        assert_export_is_private(exported)

    def test_json_document_is_canonical(self) -> None:
        document = export_to_json(_result(), _capabilities())
        parsed = json.loads(document)
        assert parsed["schema_version"] == 1
        assert parsed["profile"]["os_version"] == "6.8.0"

    def test_utilization_can_be_omitted(self) -> None:
        exported = export_discovery_result(_result(), _capabilities(), include_utilization=False)
        assert exported["utilization"] is None

    def test_export_never_contains_env_or_secret_values(self) -> None:
        exported = export_discovery_result(_result(), _capabilities())
        blob = json.dumps(exported)
        assert "api_key" not in blob and "token" not in blob and "password" not in blob

    def test_privacy_check_flags_secret_shaped_keys(self) -> None:
        assert privacy_violations({"api_key": "abc"}) == ("api_key looks like a secret value",)
        assert privacy_violations({"nested": {"auth_token": ""}}) == ()
        assert privacy_violations({"nested": {"auth_token": "x"}}) != ()

    def test_privacy_check_allows_empty_and_none(self) -> None:
        assert privacy_violations({"api_key": None, "token": "", "list": []}) == ()


class TestGuardedCapture:
    def test_refuses_without_explicit_authorization(self, tmp_path: Path) -> None:
        with pytest.raises(CaptureAuthorizationError):
            guarded_capture(
                _Collector(_result()),
                authorized=False,
                host_name="batwing",
                artifact_root=tmp_path,
                capability_profile=_capabilities(),
            )

    def test_refuses_unbounded_host_names(self, tmp_path: Path) -> None:
        for bad in ("", "../up", "a/b", "a\\b"):
            with pytest.raises(ValueError):
                guarded_capture(
                    _Collector(_result()),
                    authorized=True,
                    host_name=bad,
                    artifact_root=tmp_path,
                    capability_profile=_capabilities(),
                )

    def test_authorized_capture_retains_private_document(self, tmp_path: Path) -> None:
        path = guarded_capture(
            _Collector(_result()),
            authorized=True,
            host_name="batwing",
            artifact_root=tmp_path,
            capability_profile=_capabilities(),
        )
        assert Path(path).is_file()
        assert Path(path).suffix == ".json"
        exported = json.loads(Path(path).read_text(encoding="utf-8"))
        assert privacy_violations(exported) == ()

    def test_capture_is_repeatable_across_runs(self, tmp_path: Path) -> None:
        first = guarded_capture(
            _Collector(_result()),
            authorized=True,
            host_name="batmobile",
            artifact_root=tmp_path,
            capability_profile=_capabilities(),
        )
        second = guarded_capture(
            _Collector(_result()),
            authorized=True,
            host_name="batmobile",
            artifact_root=tmp_path,
            capability_profile=_capabilities(),
        )
        assert first == second

    def test_secret_leaking_collector_aborts_capture(self, tmp_path: Path) -> None:
        from dataclasses import replace

        class LeakyProfile:
            def public_dict(self) -> dict[str, object]:
                return {"api_key": "secret", "fine": 1}

        result = replace(_result(), profile=LeakyProfile())  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            guarded_capture(
                _Collector(result),
                authorized=True,
                host_name="batmobile",
                artifact_root=tmp_path,
                capability_profile=_capabilities(),
            )
        assert not list(tmp_path.rglob("*.json"))

    def test_write_failure_cleans_staged_and_raises_owned_error(self, tmp_path: Path) -> None:
        from morpheus.core.paths import OwnedPathError

        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        with pytest.raises(OwnedPathError):
            guarded_capture(
                _Collector(_result()),
                authorized=True,
                host_name="batmobile",
                artifact_root=blocker,
                capability_profile=_capabilities(),
            )
        assert not list(tmp_path.rglob("*.staged"))

    def test_authorization_token_is_constant(self) -> None:
        assert authorization_token() == "morpheus-capture-authorized"
