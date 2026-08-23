"""Unit tests: engine-neutral managed deployment orchestration (RUNM-004..006).

The only semantic deployment plan is ``morpheus.core.records.DeploymentPlan``
(RUNM-001); these tests exercise the durable machines around it, including the
v1 -> v2 snapshot migration that rejects lossy legacy documents.
"""

import json

import pytest

from morpheus.core.deployment import (
    DeploymentError,
    DeploymentSnapshot,
    DeploymentStore,
    LossyMigrationError,
    activate,
    adopt,
    attach_campaign_evidence,
    confirm,
    migrate_snapshot,
    preflight,
    propose,
    remove,
    rollback,
)
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    EngineIdentity,
    ModelIdentity,
    WorkloadProfile,
)

DIGEST = "d" * 64


class MemoryCampaigns:
    def __init__(self) -> None:
        self.saved: dict[str, BenchmarkCampaign] = {}

    def save_campaign(self, campaign: BenchmarkCampaign) -> None:
        self.saved[campaign.campaign_id] = campaign

    def campaign(self, campaign_id: str) -> BenchmarkCampaign | None:
        return self.saved.get(campaign_id)

    def campaigns_for_plan(self, plan_id: str) -> tuple[BenchmarkCampaign, ...]:
        return tuple(c for c in self.saved.values() if c.plan_id == plan_id)


def plan(model_id: str = "model-llama-3-1-8b", **overrides) -> DeploymentPlan:
    fields = {
        "model": ModelIdentity(
            model_id=model_id,
            revision="v1",
            artifact_digest=DIGEST,
            model_format="gguf",
            quantization="q4_k_m",
            license_id="apache-2.0",
            source="huggingface",
        ),
        "engine": EngineIdentity(
            engine_id="engine-llama-cpp-0001",
            kind="llama.cpp",
            artifact_digest="e" * 64,
            platforms=("linux-x86_64",),
        ),
        "workload": WorkloadProfile(
            workload_id="workload-developer-0001",
            developer_profile="full-stack",
            context_tokens=8192,
            max_concurrency=1,
            required_features=("chat",),
        ),
        "settings": (("context_length", 8192), ("threads", 2)),
        "served_aliases": ("libri-1",),
        "context_tokens": 8192,
        "max_concurrency": 1,
        "cache_policy": "owned-cache",
        "memory_estimate_bytes": 4 * 1024**3,
        "disk_estimate_bytes": 8 * 1024**3,
        "owned_paths": ("/opt/morpheus/dev/cache",),
        "ports": (8080,),
        "health_contract_id": "health-openai-compatible-0001",
        "benchmark_gate_id": "gate-ttft-0001",
        "rollback_target_plan_id": None,
        "source_evidence_digest": DIGEST,
    }
    fields.update(overrides)
    return DeploymentPlan(plan_id=f"plan-{model_id.removeprefix('model-')}-0001", **fields)


def campaign(plan: DeploymentPlan, state: str = "succeeded") -> BenchmarkCampaign:
    return BenchmarkCampaign(
        campaign_id=f"campaign-{plan.plan_id}",
        plan_id=plan.plan_id,
        benchmark_suite_id="suite-developer-0001",
        workload_id=plan.workload.workload_id,
        state=state,
    )


class RecordHooks:
    def __init__(self) -> None:
        self.validated: list[DeploymentPlan] = []
        self.activated: list[DeploymentPlan] = []
        self.deactivated: list[DeploymentPlan] = []
        self.cleaned: list[DeploymentPlan] = []
        self.fail_on_validate = False
        self.fail_validate_after: int | None = None
        self.validate_calls = 0
        self.fail_on_activate = False
        self.fail_on_deactivate = False
        self.fail_on_cleanup = False
        self.validate_violations: tuple[str, ...] = ()

    def validate(self, p: DeploymentPlan) -> tuple[str, ...]:
        self.validate_calls += 1
        self.validated.append(p)
        if self.fail_on_validate or (
            self.fail_validate_after is not None and self.validate_calls >= self.fail_validate_after
        ):
            raise RuntimeError("validate exploded")
        return self.validate_violations

    def activate(self, p: DeploymentPlan) -> None:
        self.activated.append(p)
        if self.fail_on_activate:
            raise RuntimeError("activate exploded")

    def deactivate(self, p: DeploymentPlan) -> None:
        self.deactivated.append(p)
        if self.fail_on_deactivate:
            raise RuntimeError("deactivate exploded")

    def cleanup(self, p: DeploymentPlan) -> None:
        self.cleaned.append(p)
        if self.fail_on_cleanup:
            raise RuntimeError("cleanup exploded")


class ConfirmOperator:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[DeploymentPlan] = []

    def confirm(self, p: DeploymentPlan) -> bool:
        self.calls.append(p)
        return self.accepted


def promote_to_active(store, hooks, operator=None, p=None):
    p = p or plan()
    campaigns = MemoryCampaigns()
    propose(store, p, artifacts_verified=True)
    preflight(store, p, hooks)
    attach_campaign_evidence(store, p, campaign=campaign(p), campaigns=campaigns)
    confirm(store, p, operator or ConfirmOperator())
    return activate(store, p, hooks)


def test_plan_identity_is_exact_and_immutable_across_the_store(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    promote_to_active(store, hooks, p=p)
    stored = store.get_plan(p.plan_id)
    assert stored == p
    assert stored.plan_id == p.plan_id


def _legacy_v1_document() -> dict:
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
            "model_artifact": DIGEST,
            "engine_artifact": "e" * 64,
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


def test_v1_snapshots_are_rejected_as_lossy_not_reinterpreted(tmp_path) -> None:
    with pytest.raises(LossyMigrationError) as error:
        migrate_snapshot(_legacy_v1_document())
    message = str(error.value)
    assert "license_id" in message
    assert "cannot be migrated without losing canonical identity" in message


def test_unknown_snapshot_versions_are_rejected() -> None:
    document = _legacy_v1_document()
    document["schema_version"] = 99
    with pytest.raises(LossyMigrationError, match="99"):
        migrate_snapshot(document)


def test_tampered_plan_documents_never_load(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    promote_to_active(store, hooks, p=p)
    document_path = tmp_path / "deployments" / f"{p.plan_id}.json"
    payload = json.loads(document_path.read_text(encoding="utf-8"))
    del payload["plan"]["owned_paths"]
    document_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):  # exact-field rebuild rejects mutated payloads
        store.load_by_id(p.plan_id)


def test_propose_requires_verified_artifacts(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    with pytest.raises(DeploymentError, match="verified artifacts"):
        propose(store, plan())
    propose(store, plan(), artifacts_verified=True)
    assert store.load(plan()).state == "proposed"
    with pytest.raises(DeploymentError, match="already tracked"):
        propose(store, plan(), artifacts_verified=True)


def test_preflight_rejects_on_violations(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    propose(store, p, artifacts_verified=True)
    hooks.validate_violations = ("engine llama.cpp requires cpu",)
    snapshot = preflight(store, p, hooks)
    assert snapshot.state == "rejected"
    with pytest.raises(DeploymentError, match="preflighted plan"):
        attach_campaign_evidence(store, p, campaign=campaign(p), campaigns=MemoryCampaigns())


def test_campaign_evidence_requires_same_plan_and_success(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    propose(store, p, artifacts_verified=True)
    preflight(store, p, hooks)
    other = plan(model_id="model-mistral-7b")
    with pytest.raises(DeploymentError, match="correlates plan"):
        attach_campaign_evidence(store, p, campaign=campaign(other), campaigns=MemoryCampaigns())
    with pytest.raises(DeploymentError, match="campaign gate failed"):
        attach_campaign_evidence(
            store,
            p,
            campaign=campaign(p, state="aborted"),
            campaigns=MemoryCampaigns(),
        )
    snapshot = attach_campaign_evidence(store, p, campaign=campaign(p), campaigns=MemoryCampaigns())
    assert snapshot.campaign_id == f"campaign-{p.plan_id}"
    assert store.load(p).state == "preflighted"


def test_confirmation_pass_is_required(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    propose(store, p, artifacts_verified=True)
    preflight(store, p, hooks)
    snapshot = confirm(store, p, ConfirmOperator(accepted=False))
    assert snapshot.state == "rejected"
    with pytest.raises(DeploymentError, match="confirmed"):
        activate(store, p, hooks)


def test_full_promotion_makes_plan_active_and_records_lkg(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan(model_id="model-llama-3-1-8b")
    second = plan(model_id="model-mistral-7b")
    promote_to_active(store, hooks, p=first)
    promote_to_active(store, hooks, p=second)
    active = store.active()
    assert active.plan.plan_id == second.plan_id
    assert active.previous_plan_id == first.plan_id
    assert store.last_known_good().plan.plan_id == first.plan_id
    first_snapshot = store.load(first)
    assert first_snapshot.active is False


def test_activation_failure_restores_previous_plan(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan(model_id="model-llama-3-1-8b")
    second = plan(model_id="model-mistral-7b")
    promote_to_active(store, hooks, p=first)
    campaigns = MemoryCampaigns()
    propose(store, second, artifacts_verified=True)
    preflight(store, second, hooks)
    attach_campaign_evidence(store, second, campaign=campaign(second), campaigns=campaigns)
    confirm(store, second, ConfirmOperator())
    hooks.fail_on_activate = True
    with pytest.raises(DeploymentError, match="restored"):
        activate(store, second, hooks)
    assert store.active().plan.plan_id == first.plan_id
    failed = store.load(second)
    assert failed.state == "rolled_back"
    assert sum(1 for p in hooks.activated if p.plan_id == first.plan_id) >= 2


def test_rollback_returns_to_last_known_good(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan(model_id="model-llama-3-1-8b")
    second = plan(model_id="model-mistral-7b")
    promote_to_active(store, hooks, p=first)
    promote_to_active(store, hooks, p=second)
    restored = rollback(store, second, hooks)
    assert restored.plan.plan_id == first.plan_id
    assert store.active().plan.plan_id == first.plan_id
    assert store.load(second).active is False
    assert store.load(second).rollback.state == "completed"


def test_rollback_failure_is_durable(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan(model_id="model-llama-3-1-8b")
    second = plan(model_id="model-mistral-7b")
    promote_to_active(store, hooks, p=first)
    promote_to_active(store, hooks, p=second)
    hooks.fail_on_activate = True
    with pytest.raises(DeploymentError, match="rollback rejected"):
        rollback(store, second, hooks)
    assert store.load(second).rollback.state == "rejected"
    assert store.load(second).active is True


def test_rollback_restore_failure_is_durable(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan(model_id="model-llama-3-1-8b")
    second = plan(model_id="model-mistral-7b")
    promote_to_active(store, hooks, p=first)
    promote_to_active(store, hooks, p=second)
    hooks.validate_calls = 0
    hooks.fail_validate_after = 2
    with pytest.raises(DeploymentError, match="rollback failed"):
        rollback(store, second, hooks)
    assert store.load(second).rollback.state == "failed"
    assert store.load(second).active is True


def test_rollback_without_lkg_is_rejected(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    with pytest.raises(DeploymentError, match="last-known-good"):
        rollback(store, first, hooks)


def test_remove_requires_non_active_and_cleanup(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    promote_to_active(store, hooks, p=p)
    with pytest.raises(DeploymentError, match="active"):
        remove(store, p, hooks)
    candidate = plan(model_id="model-mistral-7b")
    propose(store, candidate, artifacts_verified=True)
    removed = remove(store, candidate, hooks)
    assert removed.removed is True
    assert hooks.cleaned == [candidate]
    with pytest.raises(DeploymentError, match="removed and cannot be re-proposed"):
        propose(store, candidate, artifacts_verified=True)


def test_adoption_captures_pre_state_and_restores_on_failure(tmp_path) -> None:
    class AdoptionHooks:
        def __init__(self) -> None:
            self.captured = False
            self.transferred = False
            self.restored = False
            self.fail_on_transfer = False

        def capture_pre_state(self, p, root) -> None:
            self.captured = True
            (root / "pre-state.json").write_text("{}", encoding="utf-8")

        def transfer(self, p) -> None:
            self.transferred = True
            if self.fail_on_transfer:
                raise RuntimeError("transfer exploded")

        def restore_pre_state(self, p, root) -> None:
            self.restored = True
            assert (root / "pre-state.json").exists()

    hooks = AdoptionHooks()
    store = DeploymentStore(tmp_path / "deployments")
    p = plan()
    snapshot = adopt(store, p, hooks, ConfirmOperator(), artifacts_verified=True)
    assert snapshot.state == "adopted"
    assert hooks.captured and hooks.transferred
    hooks.fail_on_transfer = True
    with pytest.raises(DeploymentError, match="pre-state restored"):
        adopt(
            store,
            plan(model_id="model-mistral-7b"),
            hooks,
            ConfirmOperator(),
            artifacts_verified=True,
        )
    assert hooks.restored


def test_adoption_requires_operator_confirmation(tmp_path) -> None:
    class AdoptionHooks:
        def capture_pre_state(self, p, root) -> None:
            pass

        def transfer(self, p) -> None:
            pass

        def restore_pre_state(self, p, root) -> None:
            pass

    store = DeploymentStore(tmp_path)
    snapshot = adopt(
        store, plan(), AdoptionHooks(), ConfirmOperator(accepted=False), artifacts_verified=True
    )
    assert snapshot.state == "rejected"


def test_snapshots_round_trip(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    promote_to_active(store, hooks, p=p)
    snapshot = store.load(p)
    payload = snapshot.to_dict()
    rebuilt = DeploymentSnapshot.from_dict(payload)
    assert rebuilt == snapshot
    assert rebuilt.plan == snapshot.plan
