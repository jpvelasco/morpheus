"""Contract tests: engine-neutral managed deployment (RUNM-004..006).

Guarantees:
- A plan is promoted only after verified artifacts, passing preflight,
  completed benchmark acceptance under declared limits, and operator
  confirmation; every gate is durable and irreversible in record.
- Activation is exclusive: the previous plan is deactivated before the new
  plan is activated, and any hook fault recovers the last-known-good plan
  durably (recovering -> rolled_back) without touching its active ownership.
- Rollback is a durable machine: preflight faults reject, restore faults
  fail, and both leave the active plan unchanged on disk.
- Adoption captures the exact pre-state before any transfer, requires
  operator confirmation, and restores the pre-state on transfer fault;
  a restore fault is durable as failed, never as restored.
- Removed plans cannot be re-proposed and no symlink escapes the owned root
  through state.json or plan documents.
"""

import hashlib

import pytest

from morpheus.core.benchmark import BenchmarkSample, CampaignDeclaration, RunIdentity
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.campaign import CampaignAuthorizationError, authorization_token
from morpheus.core.deployment import (
    DeploymentError,
    DeploymentPlan,
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
from morpheus.core.paths import OwnedPathError

pytestmark = pytest.mark.contract

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
        self.events: list[tuple[str, str]] = []
        self.fail_on_validate = False
        self.fail_validate_after: int | None = None
        self.validate_calls = 0
        self.fail_next_validate = False
        self.fail_on_activate = False
        self.fail_on_deactivate = False
        self.fail_on_cleanup = False
        self.fail_on_transfer = False
        self.fail_on_restore = False
        self.restore_calls = 0
        self.validate_violations: tuple[str, ...] = ()

    def validate(self, p: DeploymentPlan) -> tuple[str, ...]:
        self.validate_calls += 1
        self.events.append(("validate", p.plan_id))
        if self.fail_next_validate:
            self.fail_next_validate = False
            raise RuntimeError("validate exploded")
        if self.fail_on_validate or (
            self.fail_validate_after is not None and self.validate_calls >= self.fail_validate_after
        ):
            raise RuntimeError("validate exploded")
        return self.validate_violations

    def activate(self, p: DeploymentPlan) -> None:
        self.events.append(("activate", p.plan_id))
        if self.fail_on_activate:
            self.fail_on_activate = False
            raise RuntimeError("activate exploded")

    def deactivate(self, p: DeploymentPlan) -> None:
        self.events.append(("deactivate", p.plan_id))
        if self.fail_on_deactivate:
            raise RuntimeError("deactivate exploded")

    def cleanup(self, p: DeploymentPlan) -> None:
        self.events.append(("cleanup", p.plan_id))
        if self.fail_on_cleanup:
            raise RuntimeError("cleanup exploded")

    def capture_pre_state(self, p: DeploymentPlan, root) -> None:
        self.events.append(("capture", p.plan_id))

    def transfer(self, p: DeploymentPlan) -> None:
        self.events.append(("transfer", p.plan_id))
        if self.fail_on_transfer:
            raise RuntimeError("transfer exploded")

    def restore_pre_state(self, p: DeploymentPlan, root) -> None:
        self.restore_calls += 1
        self.events.append(("restore", p.plan_id))
        if self.fail_on_restore:
            raise RuntimeError("restore exploded")


class ConfirmOperator:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted

    def confirm(self, p: DeploymentPlan) -> bool:
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
        machine_id="ubuntu-2",
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


def reload(root) -> DeploymentStore:
    return DeploymentStore(root)


def state_bytes(root, plan_id: str) -> bytes:
    return (root / "deployments" / f"{plan_id}.json").read_bytes()


@pytest.mark.parametrize("fault", ["deactivate", "activate", "validate"])
def test_activation_fault_at_every_hook_recovers_last_known_good_durably(tmp_path, fault) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    second = plan(model_id="mistral-7b-instruct")
    propose(store, second, artifacts_verified=True)
    preflight(store, second, hooks)
    benchmark_gate(
        store,
        second,
        declaration=declaration(),
        identity=identity(),
        workload=workload,
        benchmark_store=BenchmarkStore(store.root / "benchmarks"),
        authorized=authorization_token(),
        ownership_target="dev",
    )
    confirm(store, second, ConfirmOperator())
    if fault == "deactivate":
        hooks.fail_on_deactivate = True
    elif fault == "activate":
        hooks.fail_on_activate = True
    else:
        hooks.fail_next_validate = True
    hooks.fail_on_activate = True
    with pytest.raises(DeploymentError):
        activate(store, second, hooks)
    fresh = reload(tmp_path)
    assert fresh.active().plan.plan_id == first.plan_id
    assert fresh.load(second).state == "rolled_back"
    assert fresh.load(second).active is False
    assert fresh.load(first).active is True
    assert fresh.load(first).promotion.state == "active"
    assert ("activate", first.plan_id) in hooks.events


def test_exclusive_resource_ordering_deactivates_previous_before_activating_new(
    tmp_path,
) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    second = plan(model_id="mistral-7b-instruct")
    promote_to_active(store, hooks, p=second)
    order = [event for event, _ in hooks.events]
    deactivate_at = order.index("deactivate")
    activate_at = order.index("activate", deactivate_at + 1)
    assert deactivate_at < activate_at


def test_failed_activation_leaves_state_file_unchanged(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    before = (tmp_path / "state.json").read_bytes()
    for index in range(2):
        second = plan(model_id=f"mistral-7b-{index}")
        propose(store, second, artifacts_verified=True)
        preflight(store, second, hooks)
        benchmark_gate(
            store,
            second,
            declaration=declaration(),
            identity=identity(),
            workload=workload,
            benchmark_store=BenchmarkStore(store.root / "benchmarks"),
            authorized=authorization_token(),
            ownership_target="dev",
        )
        confirm(store, second, ConfirmOperator())
        hooks.fail_on_activate = True
        with pytest.raises(DeploymentError):
            activate(store, second, hooks)
        hooks.fail_on_activate = False
    assert (tmp_path / "state.json").read_bytes() == before


def test_rollback_preflight_fault_is_rejected_durably(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    second = plan(model_id="mistral-7b-instruct")
    promote_to_active(store, hooks, p=second)
    hooks.fail_on_activate = True
    with pytest.raises(DeploymentError, match="rollback rejected"):
        rollback(store, second, hooks)
    fresh = reload(tmp_path)
    assert fresh.load(second).rollback.state == "rejected"
    assert fresh.load(second).active is True
    assert fresh.load(first).active is False


def test_rollback_restore_fault_is_failed_durably(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    second = plan(model_id="mistral-7b-instruct")
    promote_to_active(store, hooks, p=second)
    hooks.validate_calls = 0
    hooks.fail_validate_after = 2
    with pytest.raises(DeploymentError, match="rollback failed"):
        rollback(store, second, hooks)
    fresh = reload(tmp_path)
    assert fresh.load(second).rollback.state == "failed"
    assert fresh.load(second).active is True
    assert fresh.load(first).active is False


def test_rollback_success_is_durable_and_exclusive(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    first = plan()
    promote_to_active(store, hooks, p=first)
    second = plan(model_id="mistral-7b-instruct")
    promote_to_active(store, hooks, p=second)
    rollback(store, second, hooks)
    fresh = reload(tmp_path)
    assert fresh.active().plan.plan_id == first.plan_id
    assert fresh.load(second).rollback.state == "completed"
    assert fresh.load(second).active is False
    assert fresh.load(first).promotion.state == "active"
    assert fresh.load(first).rollback is None
    order = [event for event, _ in hooks.events]
    deactivate_at = order.index("deactivate")
    activate_at = order.index("activate", deactivate_at + 1)
    assert deactivate_at < activate_at


def test_adoption_requires_verified_artifacts_and_exact_pre_state(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan(model_id="mistral-7b-instruct")
    with pytest.raises(DeploymentError, match="verified artifacts"):
        adopt(store, p, hooks, ConfirmOperator())
    snap = adopt(store, p, hooks, ConfirmOperator(), artifacts_verified=True)
    assert snap.state == "adopted"
    assert ("capture", p.plan_id) in hooks.events
    assert ("transfer", p.plan_id) in hooks.events
    fresh = reload(tmp_path)
    assert fresh.load(p).adoption.state == "adopted"
    order = [event for event, _ in hooks.events]
    assert order.index("capture") < order.index("transfer")


def test_adoption_transfer_fault_restores_pre_state_durably(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan(model_id="mistral-7b-instruct")
    hooks.fail_on_transfer = True
    with pytest.raises(DeploymentError, match="pre-state restored"):
        adopt(store, p, hooks, ConfirmOperator(), artifacts_verified=True)
    assert hooks.restore_calls == 1
    fresh = reload(tmp_path)
    assert fresh.load(p).adoption.state == "restored"


def test_adoption_restore_fault_is_failed_durably(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan(model_id="mistral-7b-instruct")
    hooks.fail_on_transfer = True
    hooks.fail_on_restore = True
    with pytest.raises(DeploymentError, match="pre-state restore failed"):
        adopt(store, p, hooks, ConfirmOperator(), artifacts_verified=True)
    fresh = reload(tmp_path)
    assert fresh.load(p).adoption.state == "failed"


def test_adoption_without_operator_confirmation_is_rejected_durably(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan(model_id="mistral-7b-instruct")
    snap = adopt(store, p, hooks, ConfirmOperator(accepted=False), artifacts_verified=True)
    assert snap.state == "rejected"
    assert not any(event == "transfer" for event, _ in hooks.events)
    fresh = reload(tmp_path)
    assert fresh.load(p).adoption.state == "rejected"


def test_removed_plan_is_permanently_ineligible_and_cleanup_fault_is_durable(
    tmp_path,
) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan(model_id="mistral-7b-instruct")
    propose(store, p, artifacts_verified=True)
    hooks.fail_on_cleanup = True
    with pytest.raises(DeploymentError, match="cleanup"):
        remove(store, p, hooks)
    fresh = reload(tmp_path)
    assert fresh.load(p).removed is False
    hooks.fail_on_cleanup = False
    remove(store, p, hooks)
    with pytest.raises(DeploymentError, match="removed and cannot be re-proposed"):
        propose(store, p, artifacts_verified=True)
    fresh = reload(tmp_path)
    assert fresh.load(p).removed is True


def test_symlinked_state_and_documents_are_rejected(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan()
    promote_to_active(store, hooks, p=p)
    escaped = tmp_path.parent / "outside.json"
    escaped.write_bytes(b"{}")
    (tmp_path / "state.json").unlink()
    (tmp_path / "state.json").symlink_to(escaped)
    with pytest.raises(OwnedPathError):
        reload(tmp_path).active()
    (tmp_path / "state.json").unlink()
    (tmp_path / "deployments" / f"{p.plan_id}.json").unlink()
    (tmp_path / "deployments" / f"{p.plan_id}.json").symlink_to(escaped)
    with pytest.raises(OwnedPathError):
        reload(tmp_path).load(p)


def test_benchmark_gate_requires_completed_campaign_and_records_run(tmp_path) -> None:
    store = DeploymentStore(tmp_path)
    hooks = RecordHooks()
    p = plan(model_id="mistral-7b-instruct")
    propose(store, p, artifacts_verified=True)
    preflight(store, p, hooks)

    def broken(context, index):
        return BenchmarkSample(run_id=context.run_id, sequence_index=index, error="boom")

    with pytest.raises(DeploymentError, match="run status"):
        benchmark_gate(
            store,
            p,
            declaration=declaration(stop_conditions=(("target_samples", 3), ("max_errors", 1))),
            identity=identity(),
            workload=broken,
            benchmark_store=BenchmarkStore(store.root / "benchmarks"),
            authorized=authorization_token(),
            ownership_target="dev",
        )
    with pytest.raises(CampaignAuthorizationError, match="explicit authority"):
        benchmark_gate(
            store,
            p,
            declaration=declaration(),
            identity=identity(),
            workload=workload,
            benchmark_store=BenchmarkStore(store.root / "benchmarks"),
            authorized=b"deadbeef",
            ownership_target="dev",
        )
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
    fresh = reload(tmp_path)
    assert fresh.load(p).plan.benchmark_run is not None
    assert fresh.load(p).plan.benchmark_run.startswith("campaign-")


def test_snapshot_digest_is_content_derived_and_stable(tmp_path) -> None:
    a = plan()
    b = plan()
    assert a.plan_id == b.plan_id
    changed = plan(model_id="mistral-7b-instruct")
    assert changed.plan_id != a.plan_id
    assert len(a.plan_id) == 64
    assert int(a.plan_id, 16) >= 0
    probe = plan()
    assert hashlib.sha256(probe.to_dict().__str__().encode()).hexdigest() != probe.plan_id
