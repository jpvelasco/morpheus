"""R1 acceptance: one canonical identity and plan family (RUNM-001, issue #55).

Guarantees under test (RECTIFICATION_PLAN.md section 6, R1):
- one machine/catalog/workload selection becomes one canonical deployment plan
  and retains the same IDs through the codec, repositories, API, and restart;
- lossy conversion from legacy recommendation/deployment/campaign records is
  rejected with an explicit error naming the missing identity data;
- state-changing API/agent/audit records reject a missing, observed, or
  mismatched plan/ownership identity;
- the v0.1 observe-only surface is unchanged.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.agent.app import create_agent_app
from morpheus.agent.auth import sign_request
from morpheus.api.app import create_app
from morpheus.cli import main as cli
from morpheus.config import MorpheusSettings
from morpheus.core.deployment import (
    DeploymentStore,
    LossyMigrationError,
    migrate_snapshot,
)
from morpheus.core.health import Evidence, HealthState
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    WorkloadProfile,
    decode_record,
    encode_record,
)
from morpheus.ops.planning import PlanningIdentityError, PlanningService

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"RUNM-001"})
pytestmark = pytest.mark.acceptance

DIGEST_A = "1" * 64
DIGEST_B = "2" * 64
PLAN_A = "plan-r1-libri-q4-a"
PLAN_B = "plan-r1-libri-q4-b"
CAMPAIGN_A = f"campaign-{PLAN_A}"
CAMPAIGN_B = f"campaign-{PLAN_B}"
NOW = datetime(2026, 8, 23, tzinfo=UTC)

READY_EVIDENCE = Evidence(
    state=HealthState.READY,
    reason_code="models_ready",
    summary="Inference API is ready",
    observed_at=NOW,
    duration=timedelta(milliseconds=2),
    source="fixture",
    expires_at=NOW + timedelta(seconds=30),
)


def _machine() -> MachineProfile:
    return MachineProfile(
        machine_id="machine-r1-0001",
        platform="linux",
        architecture="x86_64",
        accelerator="cpu",
        memory_bytes=4 * 1024**3,
        disk_bytes=16 * 1024**3,
    )


def _workload() -> WorkloadProfile:
    return WorkloadProfile(
        workload_id="workload-r1-0001",
        developer_profile="full-stack",
        context_tokens=2_048,
        max_concurrency=1,
        required_features=("chat",),
    )


def _model() -> ModelIdentity:
    return ModelIdentity(
        model_id="model-smollm2-135m-instruct",
        revision="f0a2b81",
        artifact_digest=DIGEST_A,
        model_format="gguf",
        quantization="q4_k_m",
        license_id="apache-2.0",
        source="huggingface",
    )


def _engine() -> EngineIdentity:
    return EngineIdentity(
        engine_id="engine-llama-cpp-r1",
        kind="llama.cpp",
        artifact_digest=DIGEST_B,
        platforms=("linux-x86_64",),
    )


def _plan(plan_id: str, context_length: int) -> DeploymentPlan:
    return DeploymentPlan(
        plan_id=plan_id,
        model=_model(),
        engine=_engine(),
        workload=_workload(),
        settings=(("context_length", context_length), ("threads", 2)),
        served_aliases=("libri-1",),
        context_tokens=2_048,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=512 * 1024**2,
        disk_estimate_bytes=256 * 1024**2,
        owned_paths=("/opt/morpheus/r1/cache",),
        ports=(8080,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-ttft-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=DIGEST_B,
    )


def _campaign(campaign_id: str, plan_id: str, state: str = "succeeded") -> BenchmarkCampaign:
    return BenchmarkCampaign(
        campaign_id=campaign_id,
        plan_id=plan_id,
        benchmark_suite_id="suite-r1-0001",
        workload_id=_workload().workload_id,
        state=state,
    )


class RecordingStageHooks:
    """Typed StageHooks port recording calls without external side effects."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def validate(self, plan: DeploymentPlan) -> tuple[str, ...]:
        self.calls.append(("validate", plan.plan_id))
        return ()

    def activate(self, plan: DeploymentPlan) -> None:
        self.calls.append(("activate", plan.plan_id))

    def deactivate(self, plan: DeploymentPlan) -> None:
        self.calls.append(("deactivate", plan.plan_id))

    def cleanup(self, plan: DeploymentPlan) -> None:
        self.calls.append(("cleanup", plan.plan_id))


class HostRuntimeAgent:
    """Runtime agent stub returning deterministic host facts."""

    def __init__(self) -> None:
        self.observations = 0

    async def inspect(self, operation: Any) -> Any:
        from morpheus.agent.protocol import AgentOperation, AgentResponse

        self.observations += 1
        result: dict[str, Any] = {"containers": []}
        if operation is AgentOperation.HOST_SUMMARY:
            result = {
                "memory": {"total_bytes": 4 * 1024**3},
                "disk": {"total_bytes": 16 * 1024**3},
            }
        elif operation is AgentOperation.GPU_SUMMARY:
            result = {"gpus": []}
        return AgentResponse(request_id="fixture", operation=operation, result=result)


def _planning(data_dir: Any) -> PlanningService:
    return PlanningService(
        records=RecordsStore(data_dir / "records"),
        plans=DeploymentStore(data_dir / "deployments"),
    )


def _app(
    data_dir: Any,
    *,
    hooks: RecordingStageHooks | None = None,
    runtime_agent: Any | None = None,
) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=data_dir,
            enable_workflows=True,
        ),
        inference=FakeInference(health_result=READY_EVIDENCE, model_results=()),
        clock=FakeClock(now=NOW),
        runtime_agent=runtime_agent,
        stage_hooks=hooks,
    )
    return TestClient(app, base_url="https://testserver")


def _signed_in(api: TestClient) -> dict[str, str]:
    response = api.post(
        "/api/v1/session",
        json={"api_key": "test-api-key"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    csrf = api.cookies.get("morpheus_csrf", "")
    return {"X-CSRF-Token": csrf}


_AUTH = {"Authorization": "Bearer test-api-key"}


# ---------------------------------------------------------------------------
# Criterion 1: one recommendation becomes one canonical plan; IDs survive the
# codec, the repositories, the API, and an application restart.
# ---------------------------------------------------------------------------


def test_RUNM_001_selection_identity_survives_codec_repository_and_service_restart(
    tmp_path: Any,
) -> None:
    service = _planning(tmp_path)
    machine, workload = _machine(), _workload()
    catalog = (_plan(PLAN_A, 2_048), _plan(PLAN_B, 1_024))

    recommendation = service.select_plan(machine=machine, workload=workload, catalog=catalog)

    assert recommendation.plan_ids == (PLAN_A, PLAN_B)
    assert recommendation.machine_id == machine.machine_id

    stored_plan = service.plan(PLAN_A)
    assert stored_plan is not None
    assert decode_record(encode_record(stored_plan)) == stored_plan
    assert decode_record(encode_record(recommendation)).record_id == recommendation.record_id

    reopened = _planning(tmp_path)
    assert reopened.plan(PLAN_A) == stored_plan
    assert reopened.latest_recommendation().record_id == recommendation.record_id


def test_RUNM_001_selection_through_api_keeps_one_plan_id_across_restart(tmp_path: Any) -> None:
    first = _app(tmp_path)
    csrf = _signed_in(first)
    selected = first.post(
        "/api/v1/plans/select",
        json={
            "machine_profile": _machine().public_dict(),
            "workload_profile": _workload().public_dict(),
            "catalog": [_plan(PLAN_A, 2_048).public_dict(), _plan(PLAN_B, 1_024).public_dict()],
        },
        headers={**_AUTH, **csrf},
    )
    assert selected.status_code == 200, selected.text
    payload = selected.json()
    assert payload["selected_plan_id"] == PLAN_A
    assert payload["recommendation"]["plan_ids"] == [PLAN_A, PLAN_B]
    assert payload["plans"][0]["plan_id"] == PLAN_A
    recommendation_id = payload["recommendation"]["recommendation_id"]

    fetched = first.get(f"/api/v1/plans/{PLAN_A}", headers=_AUTH)
    assert fetched.status_code == 200
    assert fetched.json()["plan"]["plan_id"] == PLAN_A

    restarted = _app(tmp_path)
    again = restarted.get(f"/api/v1/plans/{PLAN_A}", headers=_AUTH)
    assert again.status_code == 200
    assert again.json() == fetched.json()

    latest = restarted.get("/api/v1/recommendations/latest", headers=_AUTH)
    assert latest.status_code == 200
    assert latest.json()["recommendation"]["record_id"] == recommendation_id


def test_RUNM_001_promotion_and_rollback_cross_an_application_restart_with_one_plan_id(
    tmp_path: Any,
) -> None:
    hooks = RecordingStageHooks()
    first = _app(tmp_path, hooks=hooks)
    csrf = _signed_in(first)
    select_headers = {**_AUTH, **csrf}

    selected = first.post(
        "/api/v1/plans/select",
        json={
            "machine_profile": _machine().public_dict(),
            "workload_profile": _workload().public_dict(),
            "catalog": [_plan(PLAN_A, 2_048).public_dict(), _plan(PLAN_B, 1_024).public_dict()],
        },
        headers=select_headers,
    )
    assert selected.status_code == 200, selected.text
    for campaign in (_campaign(CAMPAIGN_A, PLAN_A), _campaign(CAMPAIGN_B, PLAN_B)):
        stored = first.post(
            "/api/v1/plans/campaigns",
            json={"campaign": campaign.public_dict()},
            headers=select_headers,
        )
        assert stored.status_code == 200, stored.text

    promoted_a = first.post(
        f"/api/v1/plans/{PLAN_A}/promote",
        json={"confirmed": True, "artifacts_verified": True, "campaign_id": CAMPAIGN_A},
        headers=select_headers,
    )
    assert promoted_a.status_code == 200, promoted_a.text
    assert promoted_a.json()["state"] == "active"

    promoted_b = first.post(
        f"/api/v1/plans/{PLAN_B}/promote",
        json={"confirmed": True, "artifacts_verified": True, "campaign_id": CAMPAIGN_B},
        headers=select_headers,
    )
    assert promoted_b.status_code == 200, promoted_b.text
    assert promoted_b.json()["state"] == "active"

    # Restart: a brand-new application instance with fresh hooks must resolve
    # the exact same identities from durable state alone.
    restarted_hooks = RecordingStageHooks()
    restarted = _app(tmp_path, hooks=restarted_hooks)
    restart_csrf = _signed_in(restarted)
    state = restarted.get("/api/v1/plans/state", headers=_AUTH)
    assert state.status_code == 200
    assert state.json()["active_plan_id"] == PLAN_B
    assert state.json()["last_known_good_plan_id"] == PLAN_A

    rolled_back = restarted.post(
        f"/api/v1/plans/{PLAN_B}/rollback",
        json={"confirmed": True},
        headers={**_AUTH, **restart_csrf},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["state"] == "completed"

    final = _app(tmp_path).get("/api/v1/plans/state", headers=_AUTH)
    assert final.json()["active_plan_id"] == PLAN_A
    assert final.json()["last_known_good_plan_id"] is None

    audits = _app(tmp_path).get("/api/v1/operations/workflows", headers=_AUTH).json()
    plan_events = [
        event for event in audits["audit_events"] if event.get("workflow_id") == "plan_promote"
    ]
    assert plan_events, "promotion must write auditable records"
    assert all(event.get("plan_id") in {PLAN_A, PLAN_B} for event in plan_events)
    assert all(event.get("ownership") == "managed" for event in plan_events)


# ---------------------------------------------------------------------------
# Criterion 2: lossy conversion from any legacy record is rejected.
# ---------------------------------------------------------------------------


def _legacy_snapshot_v1() -> dict[str, Any]:
    """A v1 snapshot document embedding the retired lean plan family."""
    return {
        "schema_version": 1,
        "plan": {
            "candidate": {
                "model_id": "llama-3.1-8b-instruct",
                "quantization": "q4_k_m",
                "engine_id": "llama.cpp",
                "context_window": 8192,
                "concurrency": 1,
            },
            "profile_id": "developer-default",
            "model_artifact": DIGEST_A,
            "engine_artifact": DIGEST_B,
            "benchmark_run": None,
        },
        "promotion": {
            "machine": "promotion",
            "record_id": "legacy-plan",
            "state": "proposed",
            "schema_version": 1,
            "checkpoint": 0,
        },
        "rollback": None,
        "adoption": None,
        "active": False,
        "previous_plan_id": None,
        "removed": False,
    }


def test_RUNM_001_lossy_legacy_deployment_snapshot_is_rejected(tmp_path: Any) -> None:
    store = DeploymentStore(tmp_path / "deployments")

    with pytest.raises(LossyMigrationError) as error:
        migrate_snapshot(_legacy_snapshot_v1())

    message = str(error.value)
    assert "license_id" in message or "model" in message
    assert store.snapshots() == ()
    store.initialize()
    assert store.active() is None


def test_RUNM_001_lossy_legacy_recommendation_is_rejected(tmp_path: Any) -> None:
    service = _planning(tmp_path)
    legacy = {
        "record_id": "a" * 64,
        "schema_version": 1,
        "created_at": "2026-08-01T00:00:00+00:00",
        "profile": {
            "id": "developer-default",
            "version": "2026.2",
            "name": "Developer default",
            "weights": [["coding_correctness", 1.0]],
            "features": ["tool_calling"],
            "context_tokens": 8192,
            "concurrency": 1,
        },
        "operator": None,
        "reference_machine_id": "2026-08-01T00:00:00+00:00",
        "budget": {"ram_bytes": 1, "vram_bytes": 0, "storage_bytes": 1, "accelerator": "cpu"},
        "ranked": [
            {
                "candidate": {
                    "model_id": "llama-3.1-8b-instruct",
                    "quantization": "q4_k_m",
                    "engine_id": "llama.cpp",
                    "context_window": 8192,
                    "concurrency": 1,
                },
                "score": 0.5,
                "contributions": [],
                "summary": "top: llama",
            }
        ],
        "excluded": [],
        "summary": "legacy ranking record",
    }

    with pytest.raises(LossyMigrationError) as error:
        service.canonical_recommendation_from_legacy(legacy)

    assert "plan" in str(error.value).lower()


def test_RUNM_001_campaign_binding_rejects_missing_or_mismatched_plans(tmp_path: Any) -> None:
    service = _planning(tmp_path)
    service.select_plan(
        machine=_machine(),
        workload=_workload(),
        catalog=(_plan(PLAN_A, 2_048),),
    )

    with pytest.raises(PlanningIdentityError, match="plan_id"):
        service.register_campaign(_campaign(CAMPAIGN_A, ""))
    with pytest.raises(PlanningIdentityError, match=PLAN_B):
        service.register_campaign(_campaign(CAMPAIGN_A, PLAN_B))

    service.register_campaign(_campaign(CAMPAIGN_A, PLAN_A))
    assert service.campaign(CAMPAIGN_A) == _campaign(CAMPAIGN_A, PLAN_A)


# ---------------------------------------------------------------------------
# Criterion 3: state-changing API/agent/audit records reject missing, observed,
# or mismatched plan/ownership identity.
# ---------------------------------------------------------------------------


def _selected_api(tmp_path: Any) -> tuple[TestClient, dict[str, str]]:
    api = _app(tmp_path, hooks=RecordingStageHooks())
    csrf = _signed_in(api)
    selected = api.post(
        "/api/v1/plans/select",
        json={
            "machine_profile": _machine().public_dict(),
            "workload_profile": _workload().public_dict(),
            "catalog": [_plan(PLAN_A, 2_048).public_dict()],
        },
        headers={**_AUTH, **csrf},
    )
    assert selected.status_code == 200, selected.text
    return api, csrf


@pytest.mark.parametrize(
    ("body", "missing"),
    [
        ({"confirmed": True, "artifacts_verified": True}, "campaign_id"),
        ({"confirmed": True, "artifacts_verified": True, "campaign_id": ""}, "campaign_id"),
        (
            {
                "confirmed": True,
                "artifacts_verified": True,
                "campaign_id": "campaign-unknown-plan",
            },
            "mismatch",
        ),
    ],
)
def test_RUNM_001_promotion_rejects_missing_or_mismatched_campaign_identity(
    tmp_path: Any, body: dict[str, Any], missing: str
) -> None:
    api, csrf = _selected_api(tmp_path)

    response = api.post(
        f"/api/v1/plans/{PLAN_A}/promote",
        json=body,
        headers={**_AUTH, **csrf},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "planning_identity_error"
    state = api.get("/api/v1/plans/state", headers=_AUTH).json()
    assert state["active_plan_id"] is None
    audits = api.get("/api/v1/operations/workflows", headers=_AUTH).json()["audit_events"]
    assert not [event for event in audits if event.get("workflow_id") == "plan_promote"]


def test_RUNM_001_managed_actions_reject_observed_ownership(tmp_path: Any) -> None:
    api, csrf = _selected_api(tmp_path)

    response = api.post(
        f"/api/v1/plans/{PLAN_A}/promote",
        json={
            "confirmed": True,
            "artifacts_verified": True,
            "campaign_id": CAMPAIGN_A,
            "ownership": "external_observed",
        },
        headers={**_AUTH, **csrf},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "planning_identity_error"
    assert "observed" in response.json()["error"]["message"]
    assert api.get("/api/v1/plans/state", headers=_AUTH).json()["active_plan_id"] is None


def test_RUNM_001_unknown_plan_identity_is_rejected_before_any_state_changes(
    tmp_path: Any,
) -> None:
    api, csrf = _selected_api(tmp_path)

    response = api.post(
        "/api/v1/plans/plan-does-not-exist/promote",
        json={"confirmed": True, "artifacts_verified": True, "campaign_id": CAMPAIGN_A},
        headers={**_AUTH, **csrf},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "plan_not_found"


def test_RUNM_001_audit_sink_rejects_missing_observed_or_mismatched_plan_identity(
    tmp_path: Any,
) -> None:
    service = _planning(tmp_path)
    service.select_plan(
        machine=_machine(),
        workload=_workload(),
        catalog=(_plan(PLAN_A, 2_048),),
    )

    with pytest.raises(PlanningIdentityError, match="plan_id"):
        service.audit_event(event="started", plan_id=None, ownership="managed")
    with pytest.raises(PlanningIdentityError, match="observed"):
        service.audit_event(event="started", plan_id=PLAN_A, ownership="external_observed")
    with pytest.raises(PlanningIdentityError, match=PLAN_B):
        service.audit_event(event="started", plan_id="plan-not-stored", ownership="managed")


KEY = b"runtime-agent-r1-key"


def _agent_client() -> TestClient:
    class Inspector:
        def inspect(self, operation: object) -> dict[str, Any]:
            return {"operation": str(operation)}

    class Lifecycle:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def execute(self, request: Any) -> Any:
            self.requests.append(request)

            class Result:
                def as_dict(self) -> dict[str, object]:
                    return {"outcome": "already_satisfied"}

            return Result()

    client = TestClient(
        create_agent_app(
            settings=MorpheusSettings(agent_key=KEY.decode(), enable_lifecycle=True),
            inspector=Inspector(),  # type: ignore[arg-type]
            lifecycle=Lifecycle(),  # type: ignore[arg-type]
        )
    )
    return client


def _agent_post(api: TestClient, payload: dict[str, Any]) -> httpx.Response:
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    nonce = f"nonce-{timestamp}-{len(body)}"
    return api.post(
        "/v1/lifecycle",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Morpheus-Timestamp": timestamp,
            "X-Morpheus-Nonce": nonce,
            "X-Morpheus-Signature": sign_request(KEY, timestamp=timestamp, nonce=nonce, body=body),
        },
    )


def test_RUNM_001_agent_lifecycle_rejects_observed_or_unbounded_plan_identity() -> None:
    api = _agent_client()

    observed = _agent_post(
        api,
        {
            "request_id": "req-1",
            "action": "validate",
            "version": "current",
            "confirmation": "",
            "plan_id": "external_observed",
        },
    )
    malformed = _agent_post(
        api,
        {
            "request_id": "req-2",
            "action": "validate",
            "version": "current",
            "confirmation": "",
            "plan_id": "not a bounded id",
        },
    )

    assert observed.status_code == 422
    assert observed.json()["error"]["code"] == "invalid_request"
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# Criterion 4: the v0.1 observe-only surface is unchanged.
# ---------------------------------------------------------------------------


def test_RUNM_001_v01_observe_only_surface_is_unchanged(tmp_path: Any) -> None:
    api = _app(tmp_path, runtime_agent=HostRuntimeAgent())

    healthz = api.get("/healthz")
    assert healthz.status_code == 200
    diagnostics = api.get("/api/v1/diagnostics", headers=_AUTH)
    assert diagnostics.status_code == 200
    payload = diagnostics.json()
    assert {"inference", "host", "configuration"} <= set(payload)

    def routed_get(url: str, **kwargs: object) -> httpx.Response:
        assert url.endswith("/api/v1/diagnostics")
        return httpx.Response(
            200,
            json={"inference": {"state": "ready"}, "configuration": {}},
            request=httpx.Request("GET", url),
        )

    original_get = cli.httpx.get
    cli.httpx.get = routed_get
    try:
        result = CliRunner().invoke(cli.app, ["doctor", "--json"])
    finally:
        cli.httpx.get = original_get
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "ready"


def test_RUNM_001_recommendation_records_exact_machine_identity_not_observation_time(
    tmp_path: Any,
) -> None:
    agent = HostRuntimeAgent()
    early = _app(tmp_path, runtime_agent=agent)

    csrf = _signed_in(early)
    first = early.post(
        "/api/v1/recommendations",
        json={"profile": "developer-default"},
        headers={**_AUTH, **csrf},
    )
    assert first.status_code == 200, first.text
    reference = first.json()["recommendation"]["reference_machine_id"]

    assert reference.startswith("machine-")
    assert "2026-08-23" not in reference
    assert "T00:00:00" not in reference

    planning = _planning(tmp_path)
    profile = planning.machine(reference)
    assert profile is not None
    assert profile.memory_bytes == 4 * 1024**3
    assert profile.disk_bytes == 16 * 1024**3

    second_app = _app(tmp_path, runtime_agent=agent)
    second_csrf = _signed_in(second_app)
    second = second_app.post(
        "/api/v1/recommendations",
        json={"profile": "developer-default"},
        headers={**_AUTH, **second_csrf},
    )
    assert second.status_code == 200
    assert second.json()["recommendation"]["reference_machine_id"] == reference
