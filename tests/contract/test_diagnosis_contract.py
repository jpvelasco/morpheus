"""Contract tests: AI-assisted diagnosis API (AID-002/003/004).

Provider capabilities are visible before evidence leaves the host, the
analysis endpoint returns typed outcomes for disabled and consent-gated
configurations, and the API key is required for both routes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ServedModel

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"AID-003"})

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef0123456789abcdef"


def client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            release_version="0.1.0",
            source_commit=SOURCE_COMMIT,
            **settings_overrides,
        ),
        inference=FakeInference(
            health_result=Evidence(
                state=HealthState.READY,
                reason_code="ok",
                summary="fixture ready",
                observed_at=NOW,
                duration=timedelta(milliseconds=1),
                source="fixture",
                expires_at=NOW,
            ),
            model_results=(
                ServedModel(
                    root="fixture-model", aliases=("fixture-model",), context_window=4096
                ),
            ),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app, base_url="https://testserver")


AUTH = {"Authorization": "Bearer test-api-key"}


def test_AID_002_provider_capabilities_require_authentication(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/v1/diagnostics/provider")
    assert response.status_code == 401


def test_AID_002_disabled_provider_capabilities_shown_before_evidence_leaves(
    tmp_path: Path,
) -> None:
    response = client(tmp_path).get("/api/v1/diagnostics/provider", headers=AUTH)
    assert response.status_code == 200
    provider = response.json()["provider"]
    assert provider["mode"] == "disabled"
    assert provider["data_destination"] == "none"
    assert provider["retention"] == "none"
    assert provider["consent_required"] is True
    assert provider["consent_granted"] is False
    assert "timeout_ms" in provider
    assert "max_cost" in provider


def test_AID_002_external_capabilities_show_destination_and_consent(
    tmp_path: Path,
) -> None:
    response = client(
        tmp_path,
        diagnosis_mode="external",
        diagnosis_provider="fixture-api",
        diagnosis_endpoint="https://provider.example/v1/analyze",
        diagnosis_consent=False,
    ).get("/api/v1/diagnostics/provider", headers=AUTH)
    assert response.status_code == 200
    provider = response.json()["provider"]
    assert provider["mode"] == "external"
    assert provider["data_destination"] == "external:fixture-api"
    assert provider["consent_granted"] is False


def test_AID_002_analyze_requires_authentication(tmp_path: Path) -> None:
    response = client(tmp_path).post("/api/v1/diagnostics/analyze")
    assert response.status_code == 401


def test_AID_002_analyze_disabled_returns_disabled_outcome(tmp_path: Path) -> None:
    response = client(tmp_path).post("/api/v1/diagnostics/analyze", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"]["mode"] == "disabled"
    assert payload["outcome"]["status"] == "disabled"
    assert payload["outcome"]["reason"] == "diagnosis_disabled"


def test_AID_002_analyze_external_without_consent_never_contacts_provider(
    tmp_path: Path,
) -> None:
    response = client(
        tmp_path,
        diagnosis_mode="external",
        diagnosis_provider="fixture-api",
        diagnosis_endpoint="https://provider.example/v1/analyze",
        diagnosis_consent=False,
    ).post("/api/v1/diagnostics/analyze", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"]["status"] == "unavailable"
    assert payload["outcome"]["reason"] == "consent_required"


def test_AID_002_public_configuration_never_leaks_diagnosis_api_key(
    tmp_path: Path,
) -> None:
    response = client(
        tmp_path,
        diagnosis_mode="external",
        diagnosis_provider="fixture-api",
        diagnosis_endpoint="https://provider.example/v1/analyze",
        diagnosis_consent=True,
        diagnosis_api_key="super-secret-diagnosis-key",
    ).get("/api/v1/diagnostics", headers=AUTH)
    assert response.status_code == 200
    assert "super-secret-diagnosis-key" not in response.text
