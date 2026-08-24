"""Contract tests: operations navigation manifest and control ladder (OUI-001, UI-003)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.agent.protocol import AgentOperation, AgentResponse
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.benchmark import (
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import BenchmarkStore, CampaignRun
from morpheus.core.health import Evidence, HealthState
from morpheus.core.metrics_history import MetricSample
from morpheus.core.models import ServedModel
from morpheus.core.telemetry import TelemetryEvent

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"OUI-001", "OUI-004"})

pytestmark = pytest.mark.contract
NOW = datetime(2026, 8, 1, tzinfo=UTC)


def make_identity() -> RunIdentity:
    return RunIdentity(
        machine_id="fixture-machine",
        model_id="qwen2.5-7b-instruct",
        model_revision="v0.1",
        quantization="q8_0",
        engine_id="llama.cpp",
        engine_version="0.1.0",
        benchmark_revision="bench-2026.2",
        context_window=8192,
        warmup_samples=4,
    )


def make_declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="contract-campaign",
        campaign_type="coding",
        benchmark_revision="bench-2026.2",
        duration_seconds=120,
        concurrency=2,
        ownership_target="DEV",
        workload_parameters=(("temperature", "0.0"),),
        resource_envelope=(("ram", 8_589_934_592), ("vram", 12_884_901_888)),
        request_shape=(("max_tokens", "1024"),),
        stop_conditions=(("max_errors", 3), ("target_samples", 500)),
    )


def make_samples(run_id: str = "run-1") -> tuple:
    from morpheus.core.benchmark import BenchmarkSample

    return tuple(
        BenchmarkSample(
            run_id=run_id,
            started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
            sequence_index=index,
            duration_seconds=1.0,
            ttft_seconds=0.1 * (index + 1),
            tokens_per_second=10.0 + index,
            generated_tokens=32,
        )
        for index in range(4)
    )


def await_store(operation: Any) -> Any:
    return asyncio.run(operation)


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
}

DATA_WORKSPACES = {
    "benchmarks": {"schema": "benchmarks", "version": 1},
    "analytics": {"schema": "analytics", "version": 1},
    "logs_events": {"schema": "events", "version": 1},
    "settings": {"schema": "settings", "version": 1},
    "recovery": {"schema": "recovery", "version": 1},
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

    async def models(self) -> tuple[ServedModel, ...]:
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
                ServedModel(
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
        "/api/v1/operations/metrics?signal=gpu_cache_usage",
        "/api/v1/operations/events",
        "/api/v1/operations/benchmarks",
        "/api/v1/operations/analytics",
        "/api/v1/operations/settings",
        "/api/v1/operations/workflows",
        "/api/v1/operations/workflows/benchmark/session",
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
    assert by_id["settings"]["state"] == "ready"
    assert by_id["recovery"]["state"] == "empty"
    for workspace_id, query_model in DATA_WORKSPACES.items():
        assert by_id[workspace_id]["query_model"] == query_model


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
        "rag",
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
        "rag",
        "image_generation",
    }


def test_OUI_002_metrics_payload_reports_units_freshness_gaps_and_bounds(tmp_path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await_store(store.initialize())
    await_store(
        store.record_metric_samples(
            [
                MetricSample("2026-07-31T20:00:00+00:00", "vllm", "gpu_cache_usage", 10.0),
                MetricSample("2026-07-31T20:05:00+00:00", "vllm", "gpu_cache_usage", 20.0),
                MetricSample("2026-07-31T20:10:00+00:00", "vllm", "gpu_cache_usage", 30.0),
            ]
        )
    )
    response = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/metrics?signal=gpu_cache_usage&window_seconds=3600&hours=6",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["observed_at"] == NOW.isoformat()
    assert payload["signal"] == "gpu_cache_usage"
    assert payload["unit"] == "percent"
    assert payload["freshness"]["state"] == "stale"
    assert payload["freshness"]["latest_observed_at"] == "2026-07-31T20:10:00+00:00"
    assert payload["freshness"]["age_seconds"] == pytest.approx(13_800)
    assert len(payload["buckets"]) == 1
    bucket = payload["buckets"][0]
    assert bucket["start"] == "2026-07-31T20:00:00+00:00"
    assert (bucket["min"], bucket["max"], bucket["mean"]) == (10.0, 30.0, 20.0)
    assert bucket["count"] == 3
    assert payload["sample_count"] == 3
    sources = {entry["source"]: entry for entry in payload["sources"]}
    assert set(sources) == {"engine", "host"}
    assert sources["engine"]["state"] == "unavailable"
    assert sources["engine"]["reason"] == "metrics_url_not_configured"


def test_OUI_002_metrics_query_is_bounded_by_max_buckets(tmp_path) -> None:
    response = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/metrics?signal=gpu_cache_usage&window_seconds=60&hours=24",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "operations_data_error"


def test_OUI_003_events_payload_is_redacted_and_filterable(tmp_path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await_store(store.initialize())
    await_store(
        store.record_event(
            source="engine",
            severity="error",
            message="auth failed Bearer abc123xyz",
            correlation_id="corr-1",
            recorded_at="2026-07-31T23:55:00+00:00",
        )
    )
    await_store(
        store.record_event(
            source="api",
            severity="info",
            message="heartbeat",
            recorded_at="2026-08-01T00:05:00+00:00",
        )
    )
    response = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/events?limit=10",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["count"] == 2
    assert [entry["source"] for entry in payload["events"]] == ["api", "engine"]
    first = payload["events"][1]
    assert first["correlation_id"] == "corr-1"
    assert "abc123xyz" not in first["message"]

    filtered = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/events?correlation_id=corr-1",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert filtered.json()["count"] == 1
    assert filtered.json()["events"][0]["message"].startswith("auth failed")

    invalid = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/events?source=bogus",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "operations_data_error"


def test_OUI_004_benchmarks_payload_lists_runs_most_recent_first(tmp_path) -> None:
    benchmark_store = BenchmarkStore(tmp_path / "benchmarks")
    benchmark_store.initialize()
    for index in range(2):
        benchmark_store.store_run(
            CampaignRun(
                run_id=f"run-{index}",
                declaration=make_declaration(),
                identity=make_identity(),
                started_at=datetime(2026, 8, 1, 12, index, tzinfo=UTC),
                ended_at=datetime(2026, 8, 1, 12, index + 1, tzinfo=UTC),
                status="completed",
            )
        )
    response = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/benchmarks",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["count"] == 2
    assert [run["run_id"] for run in payload["runs"]] == ["run-1", "run-0"]
    assert payload["runs"][0]["status"] == "completed"


def test_OUI_004_analytics_payload_reports_usage_scorecards_and_comparisons(tmp_path) -> None:
    benchmark_store = BenchmarkStore(tmp_path / "benchmarks")
    benchmark_store.initialize()

    samples = make_samples()
    baseline = summarize_samples("run-1", samples)
    benchmark_store.store_samples(samples)
    benchmark_store.store_summary(baseline)
    candidate_samples = make_samples("run-2")
    candidate = summarize_samples("run-2", candidate_samples)
    benchmark_store.store_samples(candidate_samples)
    benchmark_store.store_summary(candidate)
    for index, run_id in enumerate(("run-1", "run-2")):
        benchmark_store.store_run(
            CampaignRun(
                run_id=run_id,
                declaration=make_declaration(),
                identity=make_identity(),
                started_at=datetime(2026, 8, 1, 12, index, tzinfo=UTC),
                ended_at=datetime(2026, 8, 1, 12, index + 1, tzinfo=UTC),
                status="completed",
            )
        )
    telemetry_store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await_store(telemetry_store.initialize())
    event = TelemetryEvent.new(correlation_id="corr-1", model_requested="alias", started_at=1)
    event.complete(2)
    await_store(telemetry_store.record_telemetry(event))

    response = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/analytics",
        headers={"Authorization": "Bearer test-api-key"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_version"] == 1
    assert payload["usage"]["requests"] == 1
    assert payload["usage"]["successes"] == 1
    assert [card["run_id"] for card in payload["scorecards"]] == ["run-1", "run-2"]
    assert len(payload["comparisons"]) == 1
    assert payload["comparisons"][0]["baseline_run_id"] == "run-1"
    assert payload["comparisons"][0]["classification"] == "COMPARABLE"


def test_OUI_001_navigation_reports_data_workspace_states_from_stores(tmp_path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await_store(store.initialize())
    await_store(store.record_event(source="api", severity="info", message="heartbeat"))
    benchmark_store = BenchmarkStore(tmp_path / "benchmarks")
    benchmark_store.initialize()
    for index in range(2):
        benchmark_store.store_run(
            CampaignRun(
                run_id=f"run-{index}",
                declaration=make_declaration(),
                identity=make_identity(),
                started_at=datetime(2026, 8, 1, 12, index, tzinfo=UTC),
                ended_at=datetime(2026, 8, 1, 12, index + 1, tzinfo=UTC),
                status="completed",
            )
        )
    response = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
        )
    ).get(
        "/api/v1/operations/navigation",
        headers={"Authorization": "Bearer test-api-key"},
    )
    by_id = {workspace["id"]: workspace for workspace in response.json()["workspaces"]}
    assert response.status_code == 200
    assert by_id["benchmarks"]["state"] == "ready"
    assert by_id["analytics"]["state"] == "ready"
    assert by_id["logs_events"]["state"] == "ready"


def _signed_in_client(tmp_path) -> tuple[TestClient, dict[str, str]]:
    test_client = client(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            enable_workflows=True,
            enable_lifecycle=True,
            lifecycle_deployment_root=tmp_path / "deploy",
        )
    )
    response = test_client.post(
        "/api/v1/session",
        json={"api_key": "test-api-key"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    csrf = test_client.cookies.get("morpheus_csrf", "")
    return test_client, {"X-CSRF-Token": csrf}


def test_OUI_005_settings_payload_reports_catalog_sources_and_journal(tmp_path) -> None:
    test_client = client(
        settings=MorpheusSettings(
            api_key="test-api-key", session_secret="session-test-secret", data_dir=tmp_path
        )
    )
    response = test_client.get(
        "/api/v1/operations/settings", headers={"Authorization": "Bearer test-api-key"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["restart_required"] is True
    assert payload["journal"]["rollback_available"] is False
    by_key = {entry["key"]: entry for entry in payload["settings"]}
    assert by_key["api_port"]["kind"] == "port"
    assert by_key["api_port"]["editable"] is True
    assert by_key["api_key"]["kind"] == "secret"
    assert by_key["api_key"]["editable"] is False
    assert by_key["api_key"]["current"] is None
    assert by_key["api_port"]["source"] == "default"


def test_OUI_005_settings_plan_validates_and_requires_csrf(tmp_path) -> None:
    test_client, csrf = _signed_in_client(tmp_path)
    without_csrf = test_client.post(
        "/api/v1/operations/settings/plan",
        json={"changes": {"api_port": 7411}},
    )
    assert without_csrf.status_code == 403
    assert without_csrf.json()["error"]["code"] == "csrf_validation_failed"
    valid = test_client.post(
        "/api/v1/operations/settings/plan",
        json={"changes": {"api_port": 7411}},
        headers=csrf,
    )
    assert valid.status_code == 200
    plan = valid.json()
    assert plan["valid"] is True
    assert plan["changes"] == [
        {
            "key": "api_port",
            "before": 7400,
            "after": 7411,
            "restart_required": True,
            "kind": "port",
        }
    ]
    invalid = test_client.post(
        "/api/v1/operations/settings/plan",
        json={"changes": {"api_port": 99_999}},
        headers=csrf,
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert invalid.json()["issues"][0]["key"] == "api_port"
    secret = test_client.post(
        "/api/v1/operations/settings/plan",
        json={"changes": {"api_key": "tampered"}},
        headers=csrf,
    )
    assert secret.json()["valid"] is False
    assert secret.json()["issues"][0]["code"] == "secret_not_editable"


def test_OUI_005_settings_apply_persists_journal_and_rollback_restores(tmp_path) -> None:
    test_client, csrf = _signed_in_client(tmp_path)
    applied = test_client.post(
        "/api/v1/operations/settings/apply",
        json={"changes": {"api_port": 7411, "llm_model": "qwen-test"}},
        headers=csrf,
    )
    assert applied.status_code == 200
    assert applied.json()["applied"] == {"api_port": "7411", "llm_model": "qwen-test"}
    assert applied.json()["restart_required"] is True
    first_journal = test_client.get(
        "/api/v1/operations/settings", headers={"Authorization": "Bearer test-api-key"}
    ).json()["journal"]
    assert first_journal["rollback_available"] is False
    assert first_journal["applied"]["api_port"] == "7411"
    assert "api_key" not in str(first_journal)
    overrides = (tmp_path / "settings" / "overrides.env").read_text(encoding="utf-8")
    assert "API_PORT=7411" in overrides
    applied_twice = test_client.post(
        "/api/v1/operations/settings/apply",
        json={"changes": {"api_port": 7412}},
        headers=csrf,
    )
    assert applied_twice.status_code == 200
    journal = test_client.get(
        "/api/v1/operations/settings", headers={"Authorization": "Bearer test-api-key"}
    ).json()["journal"]
    assert journal["rollback_available"] is True
    assert journal["applied"]["api_port"] == "7412"
    rolled_back = test_client.post("/api/v1/operations/settings/rollback", headers=csrf)
    assert rolled_back.status_code == 200
    assert rolled_back.json()["rolled_back"] is True
    restored = (tmp_path / "settings" / "overrides.env").read_text(encoding="utf-8")
    assert "API_PORT=7411" in restored
    assert "LLM_MODEL=qwen-test" in restored
    empty_journal = test_client.get(
        "/api/v1/operations/settings", headers={"Authorization": "Bearer test-api-key"}
    ).json()["journal"]
    assert empty_journal["rollback_available"] is False


def test_OUI_005_settings_apply_rejects_invalid_plans(tmp_path) -> None:
    test_client, csrf = _signed_in_client(tmp_path)
    response = test_client.post(
        "/api/v1/operations/settings/apply",
        json={"changes": {"api_port": 99_999}},
        headers=csrf,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "operations_data_error"
    assert not (tmp_path / "settings" / "overrides.env").exists()


def test_OUI_006_workflows_payload_lists_definitions_and_sessions(tmp_path) -> None:
    test_client = client(
        settings=MorpheusSettings(
            api_key="test-api-key", session_secret="session-test-secret", data_dir=tmp_path
        )
    )
    response = test_client.get(
        "/api/v1/operations/workflows", headers={"Authorization": "Bearer test-api-key"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    workflow_ids = [workflow["workflow_id"] for workflow in payload["workflows"]]
    assert workflow_ids == [
        "model_acquire",
        "engine_install",
        "engine_configure",
        "benchmark",
        "promote",
        "rollback",
        "remove",
    ]
    remove = next(
        workflow for workflow in payload["workflows"] if workflow["workflow_id"] == "remove"
    )
    assert any(step["confirm_required"] for step in remove["steps"])
    assert payload["sessions"] == []
    assert payload["audit_events"] == []


def test_OUI_006_workflow_start_requires_confirmation_and_csrf(tmp_path) -> None:
    test_client, csrf = _signed_in_client(tmp_path)
    without_csrf = test_client.post(
        "/api/v1/operations/workflows/remove/start", json={"confirmed": True}
    )
    assert without_csrf.status_code == 403
    assert without_csrf.json()["error"]["code"] == "csrf_validation_failed"
    unconfirmed = test_client.post(
        "/api/v1/operations/workflows/remove/start",
        json={"confirmed": False},
        headers=csrf,
    )
    assert unconfirmed.status_code == 400
    assert "confirmation" in unconfirmed.json()["error"]["message"]
    started = test_client.post(
        "/api/v1/operations/workflows/remove/start",
        json={"confirmed": True},
        headers=csrf,
    )
    assert started.status_code == 200
    # R3: production routes no longer simulate mutations. Without an
    # explicitly wired lifecycle-backed executor the removal workflow is
    # durably recorded and honestly refused.
    assert started.json()["started"] is False
    session = started.json()["session"]
    assert session["workflow_id"] == "remove"
    assert session["state"] == "failed"
    assert "lifecycle-backed executor" in session["error"]
    assert session["recovery_instruction"]
    recorded = test_client.get(
        "/api/v1/operations/workflows/remove/session",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert recorded.status_code == 200
    assert recorded.json()["session"]["state"] == "failed"


def test_OUI_006_benchmark_refusal_is_honest_and_audited(tmp_path) -> None:
    test_client, csrf = _signed_in_client(tmp_path)
    started = test_client.post(
        "/api/v1/operations/workflows/benchmark/start",
        json={"confirmed": True},
        headers=csrf,
    )
    assert started.status_code == 200
    # R3: no lifecycle-backed executor is wired by default; the operation is
    # recorded durably but no step pretends to have run.
    assert started.json()["started"] is False
    session = started.json()["session"]
    assert session["state"] == "failed"
    assert session["progress_percent"] == 0
    assert all(step["outcome"] is None for step in session["steps"])
    listed = test_client.get(
        "/api/v1/operations/workflows", headers={"Authorization": "Bearer test-api-key"}
    ).json()
    assert [item["workflow_id"] for item in listed["sessions"]] == ["benchmark"]
    assert any(event["event"] == "started" for event in listed["audit_events"])
    assert any(event["event"] == "preflight_failed" for event in listed["audit_events"])
    session_response = test_client.get(
        "/api/v1/operations/workflows/benchmark/session",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert session_response.status_code == 200
    assert session_response.json()["session"]["session_id"] == started.json()["operation_id"]


def test_OUI_006_workflow_unknown_id_and_missing_session_are_bounded(tmp_path) -> None:
    test_client, csrf = _signed_in_client(tmp_path)
    unknown = test_client.post(
        "/api/v1/operations/workflows/not-a-workflow/start",
        json={"confirmed": True},
        headers=csrf,
    )
    assert unknown.status_code == 400
    assert "unknown workflow" in unknown.json()["error"]["message"]
    uncancellable = test_client.post(
        "/api/v1/operations/workflows/not-a-workflow/cancel",
        headers=csrf,
    )
    assert uncancellable.status_code == 400
    assert "unknown workflow" in uncancellable.json()["error"]["message"]
    missing = test_client.get(
        "/api/v1/operations/workflows/benchmark/session",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert missing.status_code == 400
    assert "no workflow session" in missing.json()["error"]["message"]
    malformed_session = test_client.get(
        "/api/v1/operations/workflows/%20/session",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert malformed_session.status_code == 400
    assert "unknown workflow" in malformed_session.json()["error"]["message"]
