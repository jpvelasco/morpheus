from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity

pytestmark = pytest.mark.contract
NOW = datetime(2026, 7, 15, tzinfo=UTC)


def client() -> TestClient:
    inference = FakeInference(
        health_result=Evidence(
            state=HealthState.READY,
            reason_code="models_ready",
            summary="Inference API is ready",
            observed_at=NOW,
            duration=timedelta(milliseconds=2),
            source="fixture",
            expires_at=NOW + timedelta(seconds=30),
        ),
        model_results=(
            ModelIdentity(
                root="nvidia/Qwen3.6-27B-NVFP4",
                aliases=("qwen36-27b-nvfp4",),
                context_window=131072,
            ),
        ),
    )
    app = create_app(
        settings=MorpheusSettings(api_key="test-api-key"),
        inference=inference,
        clock=FakeClock(now=NOW),
    )
    return TestClient(app)


def test_SEC_001_public_health_is_minimal() -> None:
    response = client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health",
        "/api/v1/models",
        "/api/v1/capabilities",
        "/api/v1/diagnostics",
        "/api/v1/overview",
    ],
)
def test_SEC_001_sensitive_read_routes_require_authentication(path: str) -> None:
    response = client().get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_RUN_001_models_endpoint_returns_stable_schema() -> None:
    response = client().get("/api/v1/models", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
    assert response.json()["models"][0] == {
        "aliases": ["qwen36-27b-nvfp4"],
        "context_window": 131072,
        "root": "nvidia/Qwen3.6-27B-NVFP4",
    }


def test_SEC_004_responses_include_browser_security_headers_and_request_id() -> None:
    response = client().get("/healthz")
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_RUN_005_capabilities_report_disabled_features_honestly() -> None:
    response = client().get(
        "/api/v1/capabilities",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    assert response.json()["capabilities"]["core"]["state"] == "available"
    assert response.json()["capabilities"]["search"]["state"] == "disabled"


def test_UI_001_overview_consolidates_operational_state_without_fake_host_values() -> None:
    response = client().get(
        "/api/v1/overview",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["inference"]["state"] == "ready"
    assert payload["models"][0]["aliases"] == ["qwen36-27b-nvfp4"]
    assert payload["host"] == {
        "status": "unavailable",
        "reason": "runtime_agent_not_configured",
    }
    assert payload["external_controls"] == []
