from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.agent.protocol import AgentOperation, AgentResponse
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity

pytestmark = pytest.mark.contract
NOW = datetime(2026, 7, 15, tzinfo=UTC)


class PartialRuntimeAgent:
    async def inspect(self, operation: AgentOperation) -> AgentResponse:
        if operation is AgentOperation.GPU_SUMMARY:
            raise RuntimeError("fixture GPU probe failed")
        result = (
            {
                "memory": {"total_bytes": 1000, "available_bytes": 600},
                "disk": {"total_bytes": 2000, "used_bytes": 750, "free_bytes": 1250},
                "process": {"load_average_1m": 0.2, "uptime_seconds": 60},
                "clock": {"observed_at": NOW.isoformat()},
            }
            if operation is AgentOperation.HOST_SUMMARY
            else {"containers": [{"Names": "morpheus-api"}]}
        )
        return AgentResponse(request_id="fixture", operation=operation, result=result)


class FullRuntimeAgent:
    async def inspect(self, operation: AgentOperation) -> AgentResponse:
        if operation is AgentOperation.HOST_SUMMARY:
            result = {
                "memory": {"total_bytes": 1000, "available_bytes": 600},
                "disk": {"total_bytes": 2000, "used_bytes": 750, "free_bytes": 1250},
                "process": {"load_average_1m": 0.2, "uptime_seconds": 60},
                "clock": {"observed_at": NOW.isoformat()},
            }
        elif operation is AgentOperation.GPU_SUMMARY:
            result = {"gpus": []}
        else:
            result = {
                "containers": [
                    {
                        "image_id": "sha256:" + "a" * 64,
                        "source_commit": "b" * 40,
                        "release_version": "0.1.0",
                    }
                ]
            }
        return AgentResponse(request_id="fixture", operation=operation, result=result)


def client(
    *,
    runtime_agent: PartialRuntimeAgent | FullRuntimeAgent | None = None,
    settings: MorpheusSettings | None = None,
) -> TestClient:
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
        settings=settings or MorpheusSettings(api_key="test-api-key"),
        inference=inference,
        clock=FakeClock(now=NOW),
        runtime_agent=runtime_agent,
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
        "observed_at": NOW.isoformat(),
        "checks": {},
    }
    assert payload["external_controls"] == []


def test_RUN_004_runtime_agent_partial_failure_preserves_independent_evidence() -> None:
    response = client(runtime_agent=PartialRuntimeAgent()).get(
        "/api/v1/overview",
        headers={"Authorization": "Bearer test-api-key"},
    )
    host = response.json()["host"]
    assert response.status_code == 200
    assert host["status"] == "degraded"
    assert host["memory"] == {"total_bytes": 1000, "available_bytes": 600}
    assert host["services"] == [{"Names": "morpheus-api"}]
    assert host["checks"]["gpu_summary"]["status"] == "fail"
    assert "gpu" not in host


def test_RUN_006_diagnostics_report_each_required_check_with_remediation() -> None:
    response = client(runtime_agent=PartialRuntimeAgent()).get(
        "/api/v1/diagnostics",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    checks = {check["code"]: check for check in payload["checks"]}
    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert set(checks) == {
        "configuration",
        "network_endpoint",
        "service_contract",
        "storage",
        "clock",
        "image_pin",
        "runtime_agent",
    }
    assert checks["storage"]["status"] == "pass"
    assert checks["runtime_agent"]["next_action"]


def test_RUN_006_image_pin_check_matches_every_running_service_to_candidate() -> None:
    response = client(
        runtime_agent=FullRuntimeAgent(),
        settings=MorpheusSettings(
            api_key="test-api-key",
            release_version="0.1.0",
            source_commit="b" * 40,
        ),
    ).get(
        "/api/v1/diagnostics",
        headers={"Authorization": "Bearer test-api-key"},
    )
    checks = {check["code"]: check for check in response.json()["checks"]}
    assert response.json()["status"] == "ready"
    assert checks["image_pin"]["status"] == "pass"
    assert checks["image_pin"]["next_action"] is None
