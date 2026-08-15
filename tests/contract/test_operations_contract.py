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
from morpheus.core.models import ModelIdentity
from morpheus.core.telemetry import TelemetryEvent

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
    "settings",
    "recovery",
}

DATA_WORKSPACES = {
    "benchmarks": {"schema": "benchmarks", "version": 1},
    "analytics": {"schema": "analytics", "version": 1},
    "logs_events": {"schema": "events", "version": 1},
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
        "/api/v1/operations/metrics?signal=gpu_cache_usage",
        "/api/v1/operations/events",
        "/api/v1/operations/benchmarks",
        "/api/v1/operations/analytics",
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
    for workspace_id, query_model in DATA_WORKSPACES.items():
        assert by_id[workspace_id]["state"] == "empty"
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
