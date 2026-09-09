"""Contract tests: fixture stage hooks for install, promote, rollback (R3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.adapters.runtime.stage import FixtureStageHooks
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    EngineIdentity,
    ModelIdentity,
    WorkloadProfile,
)

pytestmark = pytest.mark.contract
NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
API_KEY = "test-api-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
DIGEST = "d" * 64


def _plan(plan_id: str, *, alias: str) -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=plan_id,
        model=ModelIdentity(
            model_id=f"model-{alias}",
            revision="v1.0.0",
            artifact_digest=DIGEST,
            model_format="gguf",
            quantization="q4_k_m",
            license_id="apache-2.0",
            source="huggingface",
        ),
        engine=EngineIdentity(
            engine_id=f"engine-{alias}",
            kind="llama.cpp",
            artifact_digest=DIGEST,
            platforms=("linux-x86_64",),
        ),
        workload=WorkloadProfile(
            workload_id=f"workload-{alias}",
            developer_profile="full-stack",
            context_tokens=8192,
            max_concurrency=1,
            required_features=("tool_use",),
        ),
        settings=(("context_length", 8192),),
        served_aliases=(alias,),
        context_tokens=8192,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=1024,
        disk_estimate_bytes=1024,
        owned_paths=(f"/var/lib/morpheus/models/{alias}",),
        ports=(8080,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-ttft-latency-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST,
    )


def _seed(tmp_path: Path, *plans: DeploymentPlan) -> RecordsStore:
    store = RecordsStore(tmp_path / "records")
    for plan in plans:
        store.save_plan(plan)
        store.save_campaign(
            BenchmarkCampaign(
                campaign_id=f"campaign-{plan.plan_id}",
                plan_id=plan.plan_id,
                benchmark_suite_id="suite-r3-0001",
                workload_id=plan.workload.workload_id,
                state="succeeded",
            )
        )
    return store


def _client(tmp_path: Path) -> TestClient:
    settings = MorpheusSettings(
        api_key=API_KEY,
        session_secret="session-test-secret",
        data_dir=tmp_path,
        enable_workflows=True,
        max_requests_per_minute=10_000,
    )
    app = create_app(
        settings=settings,
        inference=FakeInference(
            health_result=Evidence(
                state=HealthState.READY,
                reason_code="ready",
                summary="ready",
                observed_at=NOW,
                duration=timedelta(milliseconds=1),
                source="fixture",
                expires_at=NOW + timedelta(seconds=30),
            ),
            model_results=(),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app, base_url="https://testserver")


def _csrf(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/session", json={"api_key": API_KEY})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get("morpheus_csrf", "")}


def _start(
    client: TestClient, csrf: dict[str, str], workflow: str, plan_id: str, token: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/operations/workflows/{workflow}/start",
        json={"confirmed": True, "plan_id": plan_id, "operation_token": token},
        headers=csrf,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wait(client: TestClient, workflow: str, operation_id: str | None = None) -> dict[str, Any]:
    deadline = datetime.now(UTC).timestamp() + 5
    last: dict[str, Any] = {}
    while datetime.now(UTC).timestamp() < deadline:
        listed = client.get("/api/v1/operations/workflows", headers=AUTH)
        sessions = listed.json().get("sessions", [])
        matches = [
            session
            for session in sessions
            if session["workflow_id"] == workflow
            and (operation_id is None or session["operation_id"] == operation_id)
        ]
        if matches:
            last = matches[0]
            if last["state"] in {"succeeded", "failed", "cancelled"}:
                return last
    raise AssertionError(f"{workflow} never finished; last={last}")


def test_fixture_hooks_stay_inside_owned_runtime_root(tmp_path: Path) -> None:
    hooks = FixtureStageHooks(tmp_path)
    plan = _plan("plan-r3-stage-a", alias="stage-a")
    marker = hooks.stage_engine(plan)
    assert marker.is_relative_to(tmp_path / "runtime")
    hooks.activate(plan)
    assert hooks.active_plan_id() == plan.plan_id
    hooks.deactivate(plan)
    assert hooks.active_plan_id() is None
    hooks.cleanup(plan)
    assert not marker.exists()


def test_engine_install_stages_without_activating(tmp_path: Path) -> None:
    plan = _plan("plan-r3-stage-a", alias="stage-a")
    _seed(tmp_path, plan)
    with _client(tmp_path) as client:
        csrf = _csrf(client)
        started = _start(client, csrf, "engine_install", plan.plan_id, "install-a")
        assert started["started"] is True
        session = _wait(client, "engine_install", started["operation_id"])
        assert session["state"] == "succeeded"
        state = client.get("/api/v1/plans/state", headers=AUTH)
        assert state.json()["active_plan_id"] is None
    assert (tmp_path / "runtime" / "plans" / plan.plan_id / "engine.json").is_file()


def test_promote_without_campaign_does_not_activate(tmp_path: Path) -> None:
    plan = _plan("plan-r3-stage-a", alias="stage-a")
    RecordsStore(tmp_path / "records").save_plan(plan)
    with _client(tmp_path) as client:
        csrf = _csrf(client)
        install = _start(client, csrf, "engine_install", plan.plan_id, "install-a")
        _wait(client, "engine_install", install["operation_id"])
        started = _start(client, csrf, "promote", plan.plan_id, "promote-a")
        session = (
            _wait(client, "promote", started["operation_id"])
            if started["started"]
            else started["session"]
        )
        assert session["state"] == "failed"
        assert client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"] is None


def test_install_promote_then_rollback_restores_previous(tmp_path: Path) -> None:
    plan_a = _plan("plan-r3-stage-a", alias="stage-a")
    plan_b = _plan("plan-r3-stage-b", alias="stage-b")
    _seed(tmp_path, plan_a, plan_b)
    with _client(tmp_path) as client:
        csrf = _csrf(client)
        install_a = _start(client, csrf, "engine_install", plan_a.plan_id, "install-a")
        assert _wait(client, "engine_install", install_a["operation_id"])["state"] == "succeeded"
        promote_a = _start(client, csrf, "promote", plan_a.plan_id, "promote-a")
        assert _wait(client, "promote", promote_a["operation_id"])["state"] == "succeeded"
        assert (
            client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"]
            == plan_a.plan_id
        )

        install_b = _start(client, csrf, "engine_install", plan_b.plan_id, "install-b")
        assert _wait(client, "engine_install", install_b["operation_id"])["state"] == "succeeded"
        promote_b = _start(client, csrf, "promote", plan_b.plan_id, "promote-b")
        assert _wait(client, "promote", promote_b["operation_id"])["state"] == "succeeded"
        assert (
            client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"]
            == plan_b.plan_id
        )

        rollback = _start(client, csrf, "rollback", plan_b.plan_id, "rollback-b")
        session = _wait(client, "rollback", rollback["operation_id"])
        assert session["state"] == "succeeded", session
        assert (
            client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"]
            == plan_a.plan_id
        )


def test_fixture_benchmark_records_a_succeeded_campaign(tmp_path: Path) -> None:
    plan = _plan("plan-r3-stage-a", alias="stage-a")
    RecordsStore(tmp_path / "records").save_plan(plan)
    with _client(tmp_path) as client:
        csrf = _csrf(client)
        started = _start(client, csrf, "benchmark", plan.plan_id, "bench-a")
        assert started["started"] is True
        session = _wait(client, "benchmark", started["operation_id"])
        assert session["state"] == "succeeded", session
        campaigns = RecordsStore(tmp_path / "records").campaigns_for_plan(plan.plan_id)
        assert campaigns
        assert campaigns[-1].state == "succeeded"
        listed = client.get("/api/v1/operations/benchmarks?limit=10", headers=AUTH)
        assert listed.status_code == 200
        assert listed.json()["count"] >= 1


def test_GATE_001_compat_health_follows_the_active_plan(tmp_path: Path) -> None:
    plan = _plan("plan-r3-stage-a", alias="stage-a")
    _seed(tmp_path, plan)
    with _client(tmp_path) as client:
        csrf = _csrf(client)
        missing = client.get("/compat/health")
        assert missing.status_code == 503
        install = _start(client, csrf, "engine_install", plan.plan_id, "install-a")
        assert _wait(client, "engine_install", install["operation_id"])["state"] == "succeeded"
        promote = _start(client, csrf, "promote", plan.plan_id, "promote-a")
        assert _wait(client, "promote", promote["operation_id"])["state"] == "succeeded"
        health = client.get("/compat/health")
        assert health.status_code == 200
        assert health.json()["plan_id"] == plan.plan_id
        models = client.get("/compat/v1/models", headers=AUTH)
        assert models.status_code == 200
        assert models.json()["data"][0]["id"] == "stage-a"
        denied = client.get("/compat/v1/models")
        assert denied.status_code == 401
