"""Contract tests: operations navigation manifest and control ladder (OUI-001, UI-003)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.agent.protocol import AgentOperation, AgentResponse
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity

pytestmark = pytest.mark.contract
NOW = datetime(2026, 8, 1, tzinfo=UTC)

WORKSPACE_IDS = [
    "overview",
    "hardware",
    "models",
    "engines",
    "runtime",
    "benchmarks",
    "analytics",
    "logs_events",
    "diagnostics",
    "settings",
    "recovery",
]

EMPTY_WORKSPACES = {
    "engines",
    "benchmarks",
    "analytics",
    "logs_events",
    "settings",
    "recovery",
}

READY_EVIDENCE = Evidence(
    state=HealthState.READY,
    reason_code="models_ready",
    summary="Inference API is ready",
    observed_at=NOW,
    duration=timedelta(milliseconds=2),
    source="fixture",
    expires_at=NOW + timedelta(seconds=30),
)


class ServicesRuntimeAgent:
    def __init__(self, containers: list[dict[str, object]]) -> None:
        self._containers = containers

    async def inspect(self, operation: AgentOperation) -> AgentResponse:
        if operation is not AgentOperation.MORPHEUS_SERVICES:
            raise RuntimeError("only service evidence is expected")
        return AgentResponse(
            request_id="fixture",
            operation=operation,
            result={"containers": self._containers},
        )


class FailingModelsInference(FakeInference):
    def __init__(self) -> None:
        super().__init__(health_result=READY_EVIDENCE, model_results=())

    async def models(self) -> tuple[ModelIdentity, ...]:
        raise httpx.ConnectError("fixture discovery failure")


def client(
    *,
    runtime_agent: ServicesRuntimeAgent | None = None,
    settings: MorpheusSettings | None = None,
    health_result: Evidence | None = None,
    inference: FakeInference | None = None,
) -> TestClient:
    app = create_app(
        settings=settings
        or MorpheusSettings(api_key="test-api-key", session_secret="session-test-secret"),
        inference=inference
        or FakeInference(
            health_result=health_result or READY_EVIDENCE,
            model_results=(
                ModelIdentity(
                    root="nvidia/Qwen3.6-27B-NVFP4",
                    aliases=("qwen36-27b-nvfp4",),
                    context_window=131072,
                ),
            ),
        ),
        clock=FakeClock(now=NOW),
        runtime_agent=runtime_agent,
    )
    return TestClient(app, base_url="https://testserver")


def degraded_evidence(reason_code: str) -> Evidence:
    return Evidence(
        state=HealthState.DEGRADED,
        reason_code=reason_code,
        summary="Inference endpoint is degraded",
        observed_at=NOW,
        duration=timedelta(milliseconds=2),
        source="fixture",
        expires_at=NOW + timedelta(seconds=30),
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/operations/navigation",
        "/api/v1/operations/controls",
    ],
)
def test_OUI_001_operations_routes_require_authentication(path: str) -> None:
    response = client().get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_OUI_001_navigation_manifest_is_versioned_and_complete() -> None:
    response = client().get(
        "/api/v1/operations/navigation",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["observed_at"] == NOW.isoformat()
    assert [workspace["id"] for workspace in payload["workspaces"]] == WORKSPACE_IDS
    by_id = {workspace["id"]: workspace for workspace in payload["workspaces"]}
    for workspace in payload["workspaces"]:
        assert set(workspace) == {"id", "label", "state", "query_model"}
        assert workspace["label"]
    assert by_id["overview"]["state"] == "ready"
    assert by_id["diagnostics"]["state"] == "ready"
    assert by_id["hardware"]["state"] == "unavailable"
    assert by_id["runtime"]["state"] == "unavailable"
    assert by_id["models"]["state"] == "ready"
    assert by_id["hardware"]["query_model"] == {"schema": "host", "version": 1}
    assert by_id["runtime"]["query_model"] == {"schema": "runtime", "version": 1}
    assert by_id["models"]["query_model"] == {"schema": "models", "version": 1}
    for workspace_id in EMPTY_WORKSPACES:
        assert by_id[workspace_id]["state"] == "empty"
        assert by_id[workspace_id]["query_model"] is None


def test_OUI_001_navigation_reports_partial_hardware_and_runtime_with_evidence() -> None:
    response = client(runtime_agent=ServicesRuntimeAgent([])).get(
        "/api/v1/operations/navigation",
        headers={"Authorization": "Bearer test-api-key"},
    )
    by_id = {workspace["id"]: workspace for workspace in response.json()["workspaces"]}
    assert response.status_code == 200
    assert by_id["hardware"]["state"] == "partial"
    assert by_id["runtime"]["state"] == "partial"


def test_OUI_001_navigation_models_workspace_reflects_discovery_failure() -> None:
    response = client(inference=FailingModelsInference()).get(
        "/api/v1/operations/navigation",
        headers={"Authorization": "Bearer test-api-key"},
    )
    models_workspace = next(
        workspace for workspace in response.json()["workspaces"] if workspace["id"] == "models"
    )
    assert response.status_code == 200
    assert models_workspace["state"] == "unavailable"


def test_UI_003_controls_report_core_ladder_and_disabled_features() -> None:
    response = client().get(
        "/api/v1/operations/controls",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["observed_at"] == NOW.isoformat()
    assert payload["core_ready"] is True
    assert [entry["control"] for entry in payload["controls"]] == [
        "core",
        "search",
        "voice",
        "telemetry",
        "workflows",
        "research",
        "image_generation",
    ]
    by_control = {entry["control"]: entry for entry in payload["controls"]}
    assert by_control["core"] == {
        "control": "core",
        "state": "usable",
        "configured": True,
        "running": True,
        "healthy": True,
        "usable": True,
        "blockers": [],
    }
    for entry in by_control.values():
        assert set(entry) == {
            "control",
            "state",
            "configured",
            "running",
            "healthy",
            "usable",
            "blockers",
        }
    disabled = by_control["search"]
    assert disabled["state"] == "configured"
    assert disabled["configured"] is False
    assert disabled["usable"] is False


def test_UI_003_enabled_control_with_healthy_component_is_usable() -> None:
    response = client(
        settings=MorpheusSettings(api_key="test-api-key", enable_search=True),
        runtime_agent=ServicesRuntimeAgent(
            [{"component": "search", "state": "running", "health": "healthy"}]
        ),
    ).get(
        "/api/v1/operations/controls",
        headers={"Authorization": "Bearer test-api-key"},
    )
    search = next(entry for entry in response.json()["controls"] if entry["control"] == "search")
    assert response.status_code == 200
    assert search == {
        "control": "search",
        "state": "usable",
        "configured": True,
        "running": True,
        "healthy": True,
        "usable": True,
        "blockers": [],
    }


def test_UI_003_controls_distinguish_running_from_healthy_and_usable() -> None:
    unhealthy = client(
        settings=MorpheusSettings(api_key="test-api-key", enable_search=True),
        runtime_agent=ServicesRuntimeAgent(
            [{"component": "search", "state": "running", "health": "unhealthy"}]
        ),
    ).get(
        "/api/v1/operations/controls",
        headers={"Authorization": "Bearer test-api-key"},
    )
    unverified = client(settings=MorpheusSettings(api_key="test-api-key", enable_search=True)).get(
        "/api/v1/operations/controls",
        headers={"Authorization": "Bearer test-api-key"},
    )
    unhealthy_search = next(
        entry for entry in unhealthy.json()["controls"] if entry["control"] == "search"
    )
    unverified_search = next(
        entry for entry in unverified.json()["controls"] if entry["control"] == "search"
    )
    assert unhealthy_search == {
        "control": "search",
        "state": "running",
        "configured": True,
        "running": True,
        "healthy": False,
        "usable": False,
        "blockers": ["component_unhealthy:search"],
    }
    assert unverified_search["state"] == "configured"
    assert unverified_search["running"] is False
    assert unverified_search["blockers"] == ["runtime_agent_not_configured"]


def test_UI_003_core_gate_keeps_healthy_optional_controls_unusable() -> None:
    response = client(
        settings=MorpheusSettings(api_key="test-api-key", enable_search=True),
        health_result=degraded_evidence("network_endpoint_failed"),
        runtime_agent=ServicesRuntimeAgent(
            [{"component": "search", "state": "running", "health": "healthy"}]
        ),
    ).get(
        "/api/v1/operations/controls",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    search = next(entry for entry in payload["controls"] if entry["control"] == "search")
    core = next(entry for entry in payload["controls"] if entry["control"] == "core")
    assert response.status_code == 200
    assert payload["core_ready"] is False
    assert search == {
        "control": "search",
        "state": "healthy",
        "configured": True,
        "running": True,
        "healthy": True,
        "usable": False,
        "blockers": [],
    }
    assert core["state"] == "running"
    assert core["blockers"] == ["network_endpoint_failed"]


def test_UI_003_controls_cover_only_morpheus_owned_services() -> None:
    response = client().get(
        "/api/v1/operations/controls",
        headers={"Authorization": "Bearer test-api-key"},
    )
    controls = {entry["control"] for entry in response.json()["controls"]}
    assert response.status_code == 200
    assert controls == {
        "core",
        "search",
        "voice",
        "telemetry",
        "workflows",
        "research",
        "image_generation",
    }
