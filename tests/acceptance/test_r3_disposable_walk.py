"""R3 acceptance: disposable managed-operation walk (issue 57 increment).

Composes the production OperationService at the public API boundary:

authenticated start
  -> verified acquisition
  -> stage engine
  -> configure
  -> bounded benchmark
  -> promote / activate
  -> observe
  -> rollback last-known-good
  -> reconnect after API restart

Uses fixture StageHooks and an owned acquire source. No external runtime.
Does not complete the R3 package: owned-service actions remain open.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.records import DeploymentPlan, EngineIdentity, ModelIdentity, WorkloadProfile

pytestmark = pytest.mark.acceptance
MORPHEUS_OWNED_REQUIREMENTS = frozenset({"OUI-006", "RUNM-003", "GATE-001"})
NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
API_KEY = "test-api-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
FIXTURE_BLOB = b"r3-walk-model"
DIGEST = hashlib.sha256(FIXTURE_BLOB).hexdigest()


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
    payload = response.json()
    assert payload["started"] is True, payload
    return payload


def _wait(client: TestClient, workflow: str, operation_id: str) -> dict[str, Any]:
    deadline = datetime.now(UTC).timestamp() + 8
    last: dict[str, Any] = {}
    while datetime.now(UTC).timestamp() < deadline:
        listed = client.get("/api/v1/operations/workflows", headers=AUTH)
        sessions = listed.json().get("sessions", [])
        matches = [
            session
            for session in sessions
            if session["workflow_id"] == workflow and session["operation_id"] == operation_id
        ]
        if matches:
            last = matches[0]
            if last["state"] in {"succeeded", "failed", "cancelled"}:
                return last
    raise AssertionError(f"{workflow} never finished; last={last}")


def _run(
    client: TestClient, csrf: dict[str, str], workflow: str, plan_id: str, token: str
) -> dict[str, Any]:
    started = _start(client, csrf, workflow, plan_id, token)
    session = _wait(client, workflow, started["operation_id"])
    assert session["state"] == "succeeded", session
    return session


def test_r3_disposable_walk_survives_restart(tmp_path: Path) -> None:
    plan_a = _plan("plan-r3-walk-a", alias="walk-a")
    plan_b = _plan("plan-r3-walk-b", alias="walk-b")
    store = RecordsStore(tmp_path / "records")
    store.save_plan(plan_a)
    store.save_plan(plan_b)
    source = tmp_path / "acquire-source" / DIGEST
    source.parent.mkdir(parents=True)
    source.write_bytes(FIXTURE_BLOB)

    with _client(tmp_path) as client:
        csrf = _csrf(client)
        preview = client.post(
            "/api/v1/operations/settings/plan",
            json={"changes": {"api_port": 7411}},
            headers=csrf,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["valid"] is True

        _run(client, csrf, "model_acquire", plan_a.plan_id, "acquire-a")
        _run(client, csrf, "engine_install", plan_a.plan_id, "install-a")
        _run(client, csrf, "engine_configure", plan_a.plan_id, "configure-a")
        _run(client, csrf, "benchmark", plan_a.plan_id, "bench-a")
        _run(client, csrf, "promote", plan_a.plan_id, "promote-a")
        assert (
            client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"]
            == plan_a.plan_id
        )
        health = client.get("/compat/health")
        assert health.status_code == 200
        assert health.json()["plan_id"] == plan_a.plan_id

        _run(client, csrf, "engine_install", plan_b.plan_id, "install-b")
        _run(client, csrf, "engine_configure", plan_b.plan_id, "configure-b")
        _run(client, csrf, "benchmark", plan_b.plan_id, "bench-b")
        _run(client, csrf, "promote", plan_b.plan_id, "promote-b")
        assert (
            client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"]
            == plan_b.plan_id
        )

        _run(client, csrf, "rollback", plan_b.plan_id, "rollback-b")
        assert (
            client.get("/api/v1/plans/state", headers=AUTH).json()["active_plan_id"]
            == plan_a.plan_id
        )

    with _client(tmp_path) as restarted:
        state = restarted.get("/api/v1/plans/state", headers=AUTH)
        assert state.status_code == 200
        assert state.json()["active_plan_id"] == plan_a.plan_id
        health = restarted.get("/compat/health")
        assert health.status_code == 200
        assert health.json()["plan_id"] == plan_a.plan_id
        listed = restarted.get("/api/v1/operations/workflows", headers=AUTH)
        assert listed.status_code == 200
        workflow_ids = {session["workflow_id"] for session in listed.json()["sessions"]}
        assert {
            "model_acquire",
            "engine_install",
            "benchmark",
            "promote",
            "rollback",
        } <= workflow_ids
