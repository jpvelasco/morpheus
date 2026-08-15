"""Unit tests: engine-neutral managed deployment orchestration (RUNM-004..006)."""

import pytest

from morpheus.core.benchmark import BenchmarkSample, CampaignDeclaration, RunIdentity
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.campaign import authorization_token
from morpheus.core.deployment import (
    DeploymentError,
    DeploymentPlan,
    DeploymentSnapshot,
    DeploymentStore,
    ManagedCandidate,
    activate,
    adopt,
    benchmark_gate,
    confirm,
    preflight,
    propose,
    remove,
    rollback,
)

DIGEST = "d" * 64


def plan(model_id: str = "llama-3.1-8b-instruct", **overrides) -> DeploymentPlan:
    return DeploymentPlan(
        candidate=ManagedCandidate(
            model_id=model_id,
            quantization="q4_k_m",
            engine_id="llama.cpp",
            context_window=8192,
            concurrency=1,
        ),
        profile_id="developer-default",
        model_artifact=DIGEST,
        engine_artifact="e" * 64,
        **overrides,
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


def declaration(**overrides) -> CampaignDeclaration:
    fields = {
        "name": "phase-15.2-gate",
        "campaign_type": "speed",
        "benchmark_revision": "2026.2",
        "duration_seconds": 60,
        "concurrency": 1,
        "ownership_target": "dev",
        "stop_conditions": (("target_samples", 3),),
    }
    fields.update(overrides)
    return CampaignDeclaration(**fields)


def identity() -> RunIdentity:
    return RunIdentity(
        machine_id="batmobile",
        model_id="llama-3.1-8b-instruct",
        model_revision="main",
        quantization="q4_k_m",
        engine_id="llama.cpp",
        engine_version="b6000",
        benchmark_revision="2026.2",
    )


def workload(context, index):
    return BenchmarkSample(run_id=context.run_id, sequence_index=index)


def promote_to_active(store, hooks, operator=None, p=None):
    p = p or plan()
    propose(store, p, artifacts_verified=True)
    preflight(store, p, hooks)
    benchmark_gate(
        store,
        p,
        declaration=declaration(),
        identity=identity(),
        workload=workload,
        benchmark_store=BenchmarkStore(store.root / "benchmarks"),
        authorized=authorization_token(),
        ownership_target="dev",
    )
    confirm(store, p, operator or ConfirmOperator())
    return activate(store, p, hooks)


def test_plan_id_is_deterministic_and_sensitive() -> None:
    assert plan().plan_id == plan().plan_id
    assert plan().plan_id != plan(model_id="mistral-7b-instruct").plan_id


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
    with pytest.raises(DeploymentError, match="preflight"):
        benchmark_gate(
            store,
            p,
            declaration=declaration(),
            identity=identity(),
            workload=workload,
            benchmark_store=BenchmarkStore(tmp_path / "benchmarks"),
            authorized=authorization_token(),
            ownership_target="dev",
        )


def test_benchmark_gate_requires_completed_campaign(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    propose(store, p, artifacts_verified=True)
    preflight(store, p, hooks)
    with pytest.raises(DeploymentError, match="run status"):
        benchmark_gate(
            store,
            p,
            declaration=CampaignDeclaration(
                name="phase-15.2-gate",
                campaign_type="speed",
                benchmark_revision="2026.2",
                duration_seconds=60,
                concurrency=1,
                ownership_target="dev",
                stop_conditions=(("target_samples", 3), ("max_errors", 1)),
            ),
            identity=identity(),
            workload=lambda context, index: (_ for _ in ()).throw(RuntimeError("sample boom")),
            benchmark_store=BenchmarkStore(tmp_path / "benchmarks"),
            authorized=authorization_token(),
            ownership_target="dev",
        )
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
    first = plan(model_id="llama-3.1-8b-instruct")
    second = plan(model_id="mistral-7b-instruct")
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
    first = plan(model_id="llama-3.1-8b-instruct")
    second = plan(model_id="mistral-7b-instruct")
    promote_to_active(store, hooks, p=first)
    propose(store, second, artifacts_verified=True)
    preflight(store, second, hooks)
    benchmark_gate(
        store,
        second,
        declaration=declaration(),
        identity=identity(),
        workload=workload,
        benchmark_store=BenchmarkStore(tmp_path / "benchmarks"),
        authorized=authorization_token(),
        ownership_target="dev",
    )
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
    first = plan(model_id="llama-3.1-8b-instruct")
    second = plan(model_id="mistral-7b-instruct")
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
    first = plan(model_id="llama-3.1-8b-instruct")
    second = plan(model_id="mistral-7b-instruct")
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
    first = plan(model_id="llama-3.1-8b-instruct")
    second = plan(model_id="mistral-7b-instruct")
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
    candidate = plan(model_id="mistral-7b-instruct")
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
            plan(model_id="mistral-7b-instruct"),
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
