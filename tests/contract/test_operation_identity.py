"""Contract tests: managed operations require a known managed plan (R3).

State-changing workflow starts must reject a missing, observed, or unknown
plan identity before writing an operation document. A known managed plan
carries through the durable session and the R1 operation record family.
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
from morpheus.core.records import (
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    WorkloadProfile,
)

pytestmark = pytest.mark.contract
MORPHEUS_OWNED_REQUIREMENTS = frozenset({"RUNM-003", "OUI-006"})

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
API_KEY = "test-api-key"
PLAN_ID = "plan-r3-acquire-0001"
FIXTURE_BLOB = b"r3-fixture-model"
DIGEST = hashlib.sha256(FIXTURE_BLOB).hexdigest()


def _plan() -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=PLAN_ID,
        model=ModelIdentity(
            model_id="model-r3-fixture",
            revision="v1.0.0",
            artifact_digest=DIGEST,
            model_format="gguf",
            quantization="q4_k_m",
            license_id="apache-2.0",
            source="huggingface",
        ),
        engine=EngineIdentity(
            engine_id="engine-r3-fixture",
            kind="llama.cpp",
            artifact_digest=DIGEST,
            platforms=("linux-x86_64",),
        ),
        workload=WorkloadProfile(
            workload_id="workload-r3-0001",
            developer_profile="full-stack",
            context_tokens=8192,
            max_concurrency=1,
            required_features=("tool_use",),
        ),
        settings=(("context_length", 8192), ("threads", 2)),
        served_aliases=("r3-fixture",),
        context_tokens=8192,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=1024**3,
        disk_estimate_bytes=64,
        owned_paths=("/var/lib/morpheus/models/r3-fixture",),
        ports=(8080,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-ttft-latency-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST,
    )


def _client(tmp_path: Path, *, seed_plan: bool = False) -> TestClient:
    settings = MorpheusSettings(
        api_key=API_KEY,
        session_secret="session-test-secret",
        data_dir=tmp_path,
        enable_workflows=True,
        max_requests_per_minute=10_000,
    )
    if seed_plan:
        RecordsStore(settings.data_dir / "records").save_plan(_plan())
        RecordsStore(settings.data_dir / "records").save_machine_profile(
            MachineProfile(
                machine_id="machine-r3-0001",
                platform="linux",
                architecture="x86_64",
                accelerator="cpu",
                memory_bytes=8 * 1024**3,
                disk_bytes=64 * 1024**3,
            )
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


def _start(client: TestClient, csrf: dict[str, str], body: dict[str, Any]):
    return client.post("/api/v1/operations/workflows/model_acquire/start", json=body, headers=csrf)


def test_RUNM_003_start_without_plan_id_writes_no_operation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    csrf = _csrf(client)
    response = _start(client, csrf, {"confirmed": True})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "planning_identity_error"
    listed = client.get(
        "/api/v1/operations/workflows", headers={"Authorization": f"Bearer {API_KEY}"}
    )
    assert listed.json()["sessions"] == []


def test_RUNM_003_observed_plan_id_is_rejected_before_persist(tmp_path: Path) -> None:
    client = _client(tmp_path)
    csrf = _csrf(client)
    response = _start(client, csrf, {"confirmed": True, "plan_id": "external_observed"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "planning_identity_error"
    listed = client.get(
        "/api/v1/operations/workflows", headers={"Authorization": f"Bearer {API_KEY}"}
    )
    assert listed.json()["sessions"] == []


def test_RUNM_003_unknown_plan_id_is_rejected_before_persist(tmp_path: Path) -> None:
    client = _client(tmp_path)
    csrf = _csrf(client)
    response = _start(client, csrf, {"confirmed": True, "plan_id": "plan-not-stored"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "planning_identity_error"
    listed = client.get(
        "/api/v1/operations/workflows", headers={"Authorization": f"Bearer {API_KEY}"}
    )
    assert listed.json()["sessions"] == []


def test_RUNM_003_known_plan_acquire_succeeds_and_correlates_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "acquire-source" / DIGEST
    source.parent.mkdir(parents=True)
    source.write_bytes(FIXTURE_BLOB)
    with _client(tmp_path, seed_plan=True) as client:
        csrf = _csrf(client)
        response = _start(
            client,
            csrf,
            {
                "confirmed": True,
                "plan_id": PLAN_ID,
                "operation_token": "acquire-1",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["started"] is True
        assert payload["session"]["plan_id"] == PLAN_ID

        deadline = datetime.now(UTC).timestamp() + 5
        session = payload["session"]
        while datetime.now(UTC).timestamp() < deadline and session["state"] == "running":
            found = client.get(
                "/api/v1/operations/workflows/model_acquire/session",
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            assert found.status_code == 200, found.text
            session = found.json()["session"]
        assert session["state"] == "succeeded", session
        assert session["plan_id"] == PLAN_ID
        assert all(step["outcome"] == "succeeded" for step in session["steps"])

    cache = tmp_path / "acquisition" / "cache" / "model" / DIGEST
    assert cache.is_file()
    assert cache.read_bytes() == FIXTURE_BLOB

    records = RecordsStore(tmp_path / "records")
    operations = records.operations_for_plan(PLAN_ID)
    assert operations
    assert operations[-1].plan_id == PLAN_ID
    assert operations[-1].ownership == "managed"
    assert operations[-1].action == "model_acquire"
