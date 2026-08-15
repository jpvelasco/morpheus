"""Engine-neutral managed deployment orchestration (RUNM-004, RUNM-005, RUNM-006).

Staging, campaign gating, promotion, rollback, removal, and disposable adoption
are orchestrated against typed hooks and the durable architecture state
machines. Nothing here starts load or touches a runtime directly: every
side effect is a caller-provided hook, and every durable edge is a
:class:`MachineRecord` transition so a fault at any boundary leaves the
previous record unchanged and enables recovery of the last-known-good plan.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from morpheus.core.benchmark import CampaignDeclaration, RunIdentity
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.campaign import Workload, run_campaign
from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.core.state_machines import (
    MachineKind,
    MachineRecord,
    StateMachine,
    StateTransitionError,
)

SCHEMA_VERSION = 1


class DeploymentError(ValueError):
    """A deployment operation violates its contract or its state machine."""


@dataclass(frozen=True, slots=True)
class ManagedCandidate:
    model_id: str
    quantization: str
    engine_id: str
    context_window: int
    concurrency: int


@dataclass(frozen=True, slots=True)
class DeploymentPlan:
    candidate: ManagedCandidate
    profile_id: str
    model_artifact: str
    engine_artifact: str
    benchmark_run: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate.model_id:
            raise DeploymentError("candidate model id must not be empty")
        if not self.candidate.engine_id:
            raise DeploymentError("candidate engine id must not be empty")
        for digest in (self.model_artifact, self.engine_artifact):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise DeploymentError("artifact references must be sha256 hex digests")
        if self.candidate.context_window <= 0:
            raise DeploymentError("candidate context window must be positive")
        if self.candidate.concurrency <= 0:
            raise DeploymentError("candidate concurrency must be positive")

    @property
    def plan_id(self) -> str:
        canonical = json.dumps(
            {
                "model_id": self.candidate.model_id,
                "quantization": self.candidate.quantization,
                "engine_id": self.candidate.engine_id,
                "context_window": self.candidate.context_window,
                "concurrency": self.candidate.concurrency,
                "profile_id": self.profile_id,
                "model_artifact": self.model_artifact,
                "engine_artifact": self.engine_artifact,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": {
                "model_id": self.candidate.model_id,
                "quantization": self.candidate.quantization,
                "engine_id": self.candidate.engine_id,
                "context_window": self.candidate.context_window,
                "concurrency": self.candidate.concurrency,
            },
            "profile_id": self.profile_id,
            "model_artifact": self.model_artifact,
            "engine_artifact": self.engine_artifact,
            "benchmark_run": self.benchmark_run,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeploymentPlan:
        candidate = payload["candidate"]
        return cls(
            candidate=ManagedCandidate(
                model_id=candidate["model_id"],
                quantization=candidate["quantization"],
                engine_id=candidate["engine_id"],
                context_window=candidate["context_window"],
                concurrency=candidate["concurrency"],
            ),
            profile_id=payload["profile_id"],
            model_artifact=payload["model_artifact"],
            engine_artifact=payload["engine_artifact"],
            benchmark_run=payload.get("benchmark_run"),
        )


@dataclass(frozen=True, slots=True)
class DeploymentSnapshot:
    """Durable record: plan plus its machine records and ownership facts."""

    plan: DeploymentPlan
    promotion: MachineRecord | None = None
    rollback: MachineRecord | None = None
    adoption: MachineRecord | None = None
    active: bool = False
    previous_plan_id: str | None = None
    removed: bool = False

    @property
    def state(self) -> str:
        machine = self.promotion or self.rollback or self.adoption
        if machine is None:
            raise DeploymentError("snapshot has no machine records")
        return machine.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "promotion": self.promotion.public_dict() if self.promotion else None,
            "rollback": self.rollback.public_dict() if self.rollback else None,
            "adoption": self.adoption.public_dict() if self.adoption else None,
            "active": self.active,
            "previous_plan_id": self.previous_plan_id,
            "removed": self.removed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeploymentSnapshot:
        def machine(key: str) -> MachineRecord | None:
            entry = payload.get(key)
            if not entry:
                return None
            return MachineRecord(
                machine=MachineKind(entry["machine"]),
                record_id=entry["record_id"],
                state=entry["state"],
                schema_version=entry["schema_version"],
                checkpoint=entry["checkpoint"],
            )

        return cls(
            plan=DeploymentPlan.from_dict(payload["plan"]),
            promotion=machine("promotion"),
            rollback=machine("rollback"),
            adoption=machine("adoption"),
            active=payload["active"],
            previous_plan_id=payload.get("previous_plan_id"),
            removed=payload.get("removed", False),
        )


class StageHooks(Protocol):
    """Engine-neutral runtime effects for a staged candidate."""

    def validate(self, plan: DeploymentPlan) -> tuple[str, ...]:
        """Return startup/API validation violations; empty means healthy."""
        ...

    def activate(self, plan: DeploymentPlan) -> None:
        """Point the active endpoint at this plan; must not serve staged plans."""
        ...

    def deactivate(self, plan: DeploymentPlan) -> None:
        """Stop serving this plan."""
        ...

    def cleanup(self, plan: DeploymentPlan) -> None:
        """Remove owned runtime state; must stay inside owned roots."""
        ...


class AdoptionHooks(Protocol):
    def capture_pre_state(self, plan: DeploymentPlan, root: Path) -> None:
        """Capture the exact pre-transfer state into an owned location."""
        ...

    def transfer(self, plan: DeploymentPlan) -> None:
        """Transfer an external runtime into Morpheus ownership."""
        ...

    def restore_pre_state(self, plan: DeploymentPlan, root: Path) -> None:
        """Restore the captured pre-transfer state after a failed transfer."""
        ...


class OperatorConfirmation(Protocol):
    def confirm(self, plan: DeploymentPlan) -> bool:
        """Operator confirmation pass before promotion takes effect."""
        ...


@dataclass(slots=True)
class DeploymentStore:
    """Owned store of deployment snapshots and the last-known-good plan."""

    root: Path
    resolver: OwnedPathResolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = OwnedPathResolver(self.root)

    def _path(self, relative: str) -> Path:
        return self.resolver.resolve_relative(relative)

    def initialize(self) -> None:
        self._path("deployments").mkdir(parents=True, exist_ok=True)
        state = self._path("state.json")
        if not state.exists():
            self._write_json(
                state,
                {
                    "schema_version": SCHEMA_VERSION,
                    "active_plan_id": None,
                    "previous_plan_id": None,
                },
            )

    def load(self, plan: DeploymentPlan) -> DeploymentSnapshot | None:
        relative = f"deployments/{plan.plan_id}.json"
        if not self._path(relative).exists():
            return None
        return DeploymentSnapshot.from_dict(self._read_document(relative))

    def snapshots(self) -> tuple[DeploymentSnapshot, ...]:
        paths = sorted(self._path("deployments").glob("*.json"))
        return tuple(
            DeploymentSnapshot.from_dict(self._read_document(f"deployments/{path.name}"))
            for path in paths
        )

    def active(self) -> DeploymentSnapshot | None:
        self.initialize()
        state = self._read_json(self._path("state.json"))
        active_id = state.get("active_plan_id")
        if not active_id:
            return None
        for snapshot in self.snapshots():
            if snapshot.plan.plan_id == active_id and snapshot.active:
                return snapshot
        return None

    def last_known_good(self) -> DeploymentSnapshot | None:
        self.initialize()
        state = self._read_json(self._path("state.json"))
        previous_id = state.get("previous_plan_id")
        if not previous_id:
            return None
        for snapshot in self.snapshots():
            if snapshot.plan.plan_id == previous_id:
                return snapshot
        return None

    def _set_active(self, plan_id: str | None, previous_id: str | None) -> None:
        self.initialize()
        self._write_json(
            self._path("state.json"),
            {
                "schema_version": SCHEMA_VERSION,
                "active_plan_id": plan_id,
                "previous_plan_id": previous_id,
            },
        )

    def _snapshot_path(self, plan: DeploymentPlan) -> Path:
        return self._path(f"deployments/{plan.plan_id}.json")

    def _persist(self, snapshot: DeploymentSnapshot) -> None:
        self._write_document(f"deployments/{snapshot.plan.plan_id}.json", snapshot.to_dict())

    def _machine(self, snapshot: DeploymentSnapshot, kind: MachineKind) -> MachineRecord:
        record = (
            snapshot.promotion
            if kind == MachineKind.PROMOTION
            else snapshot.rollback
            if kind == MachineKind.ROLLBACK
            else snapshot.adoption
        )
        if record is None:
            raise DeploymentError(f"no {kind.value} record exists for this plan")
        return record

    def _advance(
        self,
        snapshot: DeploymentSnapshot,
        kind: MachineKind,
        target: str,
    ) -> DeploymentSnapshot:
        record = self._machine(snapshot, kind)
        result = StateMachine.transition(record, target)
        if not result.accepted or result.record is None:
            raise StateTransitionError(result.audit)
        updated = {
            "promotion": snapshot.promotion,
            "rollback": snapshot.rollback,
            "adoption": snapshot.adoption,
        }
        updated[kind.value] = result.record
        return DeploymentSnapshot(
            plan=snapshot.plan,
            promotion=updated["promotion"],
            rollback=updated["rollback"],
            adoption=updated["adoption"],
            active=snapshot.active,
            previous_plan_id=snapshot.previous_plan_id,
            removed=snapshot.removed,
        )

    def _read_document(self, relative: str) -> dict[str, Any]:
        raw = Path(self.root, relative)
        if raw.is_symlink():
            raise OwnedPathError("deployment documents must not be symbolic links")
        path = self._path(relative)
        if not path.exists():
            raise DeploymentError(f"deployment document missing: {path.name}")
        return self._read_json(path)

    def _read_json(self, path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise OwnedPathError("deployment documents must not be symbolic links")
        if not path.exists():
            raise DeploymentError(f"deployment document missing: {path.name}")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_document(self, relative: str, payload: dict[str, Any]) -> None:
        self._write_json(self._path(relative), payload)


def propose(
    store: DeploymentStore,
    plan: DeploymentPlan,
    *,
    artifacts_verified: bool = False,
) -> DeploymentSnapshot:
    """Open a promotion record for a staged candidate.

    Artifacts must already be verified in the acquisition cache; staged
    candidates never receive active traffic before promotion.
    """
    if not artifacts_verified:
        raise DeploymentError("staging requires verified artifacts; acquire them before proposing")
    store.initialize()
    snapshot = store.load(plan)
    if snapshot is not None:
        if snapshot.removed:
            raise DeploymentError(f"plan was removed and cannot be re-proposed: {plan.plan_id}")
        raise DeploymentError(f"plan already tracked: {plan.plan_id}")
    record = MachineRecord(
        machine=MachineKind.PROMOTION,
        record_id=plan.plan_id,
        state="proposed",
    )
    created = DeploymentSnapshot(plan=plan, promotion=record)
    store._persist(created)
    return created


def preflight(
    store: DeploymentStore,
    plan: DeploymentPlan,
    hooks: StageHooks,
) -> DeploymentSnapshot:
    """Validate staged startup and API behavior; violations reject the plan."""
    snapshot = store.load(plan)
    if snapshot is None:
        raise DeploymentError("propose the plan before preflighting")
    violations = hooks.validate(plan)
    target = "rejected" if violations else "preflighted"
    snapshot = store._advance(snapshot, MachineKind.PROMOTION, target)
    store._persist(snapshot)
    return snapshot


def benchmark_gate(
    store: DeploymentStore,
    plan: DeploymentPlan,
    *,
    declaration: CampaignDeclaration,
    identity: RunIdentity,
    workload: Workload,
    benchmark_store: BenchmarkStore,
    authorized: bool | str,
    ownership_target: str,
) -> DeploymentSnapshot:
    """Run the declared benchmark campaign and attach its run to the plan.

    The campaign uses the BENCH-005 runner: declared limits, checkpoints,
    cancellation, and cleanup. Promotion beyond this point requires a
    completed run (acceptance gate) plus an operator confirmation pass.
    """
    snapshot = store.load(plan)
    if snapshot is None or snapshot.state != "preflighted":
        raise DeploymentError("benchmark gate requires a preflighted plan")
    run = run_campaign(
        declaration,
        identity,
        workload,
        benchmark_store,
        authorized=authorized,
        ownership_target=ownership_target,
    )
    if run.status != "completed":
        raise DeploymentError(f"benchmark gate failed: run status {run.status}")
    updated = DeploymentSnapshot(
        plan=DeploymentPlan(
            candidate=plan.candidate,
            profile_id=plan.profile_id,
            model_artifact=plan.model_artifact,
            engine_artifact=plan.engine_artifact,
            benchmark_run=run.run_id,
        ),
        promotion=snapshot.promotion,
        rollback=snapshot.rollback,
        adoption=snapshot.adoption,
        active=snapshot.active,
        previous_plan_id=snapshot.previous_plan_id,
        removed=snapshot.removed,
    )
    store._persist(updated)
    return updated


def confirm(
    store: DeploymentStore,
    plan: DeploymentPlan,
    operator: OperatorConfirmation,
) -> DeploymentSnapshot:
    """Operator confirmation pass before a plan becomes active."""
    snapshot = store.load(plan)
    if snapshot is None or snapshot.state != "preflighted":
        raise DeploymentError("confirmation requires a preflighted plan")
    if not operator.confirm(plan):
        snapshot = store._advance(snapshot, MachineKind.PROMOTION, "rejected")
        store._persist(snapshot)
        return snapshot
    snapshot = store._advance(snapshot, MachineKind.PROMOTION, "confirmed")
    store._persist(snapshot)
    return snapshot


def activate(
    store: DeploymentStore,
    plan: DeploymentPlan,
    hooks: StageHooks,
) -> DeploymentSnapshot:
    """Promote the confirmed plan to active with last-known-good recovery.

    The previous plan goes dark before the new one activates (exclusive
    resources). If activation fails, the exact previous plan is restored and
    the promotion machine ends in recovering -> rolled_back.
    """
    snapshot = store.load(plan)
    if snapshot is None or snapshot.state != "confirmed":
        raise DeploymentError("activation requires a confirmed plan")
    previous = store.active()
    snapshot = store._advance(snapshot, MachineKind.PROMOTION, "activating")
    store._persist(snapshot)
    if previous is not None:
        with suppress(Exception):
            hooks.deactivate(previous.plan)
    try:
        hooks.activate(plan)
    except Exception as exc:
        return _recover(store, snapshot, previous, hooks, exc)
    promoted = store._advance(snapshot, MachineKind.PROMOTION, "active")
    promoted = DeploymentSnapshot(
        plan=promoted.plan,
        promotion=promoted.promotion,
        rollback=promoted.rollback,
        adoption=promoted.adoption,
        active=True,
        previous_plan_id=previous.plan.plan_id if previous else None,
        removed=False,
    )
    if previous is not None:
        previous = DeploymentSnapshot(
            plan=previous.plan,
            promotion=previous.promotion,
            rollback=previous.rollback,
            adoption=previous.adoption,
            active=False,
            previous_plan_id=previous.previous_plan_id,
            removed=previous.removed,
        )
        store._persist(previous)
    store._persist(promoted)
    store._set_active(promoted.plan.plan_id, promoted.previous_plan_id)
    return promoted


def _recover(
    store: DeploymentStore,
    snapshot: DeploymentSnapshot,
    previous: DeploymentSnapshot | None,
    hooks: StageHooks,
    cause: Exception,
) -> DeploymentSnapshot:
    """Restore the exact previous plan and behavioral health after a failure."""
    recovering = store._advance(snapshot, MachineKind.PROMOTION, "recovering")
    store._persist(recovering)
    if previous is not None:
        try:
            hooks.activate(previous.plan)
            violations = hooks.validate(previous.plan)
        except Exception:
            violations = ("previous plan could not be restored",)
        if not violations:
            store._persist(
                DeploymentSnapshot(
                    plan=previous.plan,
                    promotion=previous.promotion,
                    rollback=previous.rollback,
                    adoption=previous.adoption,
                    active=True,
                    previous_plan_id=previous.previous_plan_id,
                    removed=False,
                )
            )
            store._set_active(previous.plan.plan_id, None)
    rolled_back = store._advance(recovering, MachineKind.PROMOTION, "rolled_back")
    store._persist(rolled_back)
    raise DeploymentError(f"activation failed and previous plan restored: {cause}") from cause


def rollback(
    store: DeploymentStore,
    plan: DeploymentPlan,
    hooks: StageHooks,
) -> DeploymentSnapshot:
    """Roll the active plan back to its last-known-good plan.

    The rollback machine runs requested -> preflighted -> restoring ->
    verified -> completed; any failed edge is durable and leaves the active
    plan unchanged.
    """
    snapshot = store.load(plan)
    if snapshot is None or not snapshot.active:
        raise DeploymentError("rollback requires the active plan")
    previous = store.last_known_good()
    if previous is None:
        raise DeploymentError("no last-known-good plan exists to roll back to")
    record = MachineRecord(
        machine=MachineKind.ROLLBACK,
        record_id=plan.plan_id,
        state="requested",
    )
    snapshot = DeploymentSnapshot(
        plan=snapshot.plan,
        promotion=snapshot.promotion,
        rollback=record,
        adoption=snapshot.adoption,
        active=snapshot.active,
        previous_plan_id=snapshot.previous_plan_id,
        removed=snapshot.removed,
    )
    store._persist(snapshot)
    snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "preflighted")
    store._persist(snapshot)
    try:
        hooks.deactivate(plan)
        hooks.activate(previous.plan)
        violations = hooks.validate(previous.plan)
    except Exception as exc:
        snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "rejected")
        store._persist(snapshot)
        raise DeploymentError(f"rollback rejected: {exc}") from exc
    if violations:
        snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "rejected")
        store._persist(snapshot)
        raise DeploymentError(f"rollback rejected preflight: {violations}")
    snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "restoring")
    store._persist(snapshot)
    try:
        violations = hooks.validate(previous.plan)
    except Exception as exc:
        snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "failed")
        store._persist(snapshot)
        raise DeploymentError(f"rollback failed: {exc}") from exc
    if violations:
        snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "failed")
        store._persist(snapshot)
        raise DeploymentError(f"rollback failed restore: {violations}")
    snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "verified")
    store._persist(snapshot)
    snapshot = store._advance(snapshot, MachineKind.ROLLBACK, "completed")
    restored = DeploymentSnapshot(
        plan=previous.plan,
        promotion=previous.promotion,
        rollback=None,
        adoption=previous.adoption,
        active=True,
        previous_plan_id=previous.previous_plan_id,
        removed=False,
    )
    store._persist(restored)
    old = DeploymentSnapshot(
        plan=snapshot.plan,
        promotion=snapshot.promotion,
        rollback=snapshot.rollback,
        adoption=snapshot.adoption,
        active=False,
        previous_plan_id=snapshot.previous_plan_id,
        removed=False,
    )
    store._persist(old)
    store._set_active(previous.plan.plan_id, None)
    return restored


def remove(
    store: DeploymentStore,
    plan: DeploymentPlan,
    hooks: StageHooks,
) -> DeploymentSnapshot:
    """Remove a non-active plan's owned runtime state permanently."""
    snapshot = store.load(plan)
    if snapshot is None:
        raise DeploymentError("no such plan")
    if snapshot.active:
        raise DeploymentError("cannot remove the active plan; roll back first")
    try:
        hooks.cleanup(plan)
    except Exception as exc:
        raise DeploymentError(f"removal cleanup failed: {exc}") from exc
    removed = DeploymentSnapshot(
        plan=snapshot.plan,
        promotion=snapshot.promotion,
        rollback=snapshot.rollback,
        adoption=snapshot.adoption,
        active=False,
        previous_plan_id=snapshot.previous_plan_id,
        removed=True,
    )
    store._persist(removed)
    return removed


def adopt(
    store: DeploymentStore,
    plan: DeploymentPlan,
    hooks: AdoptionHooks,
    operator: OperatorConfirmation,
    *,
    artifacts_verified: bool = False,
) -> DeploymentSnapshot:
    """Adopt an existing external runtime with exact pre-state capture.

    The adoption workflow requires explicit ownership transfer and a tested
    restoration path; a failed transfer restores the captured pre-state.
    """
    if not artifacts_verified:
        raise DeploymentError("adoption requires verified artifacts")
    store.initialize()
    snapshot = store.load(plan)
    if snapshot is not None:
        if snapshot.removed:
            raise DeploymentError(f"plan was removed and cannot be re-proposed: {plan.plan_id}")
        raise DeploymentError(f"plan already tracked: {plan.plan_id}")
    record = MachineRecord(
        machine=MachineKind.ADOPTION,
        record_id=plan.plan_id,
        state="proposed",
    )
    snapshot = DeploymentSnapshot(plan=plan, promotion=None, adoption=record)
    store._persist(snapshot)
    snapshot = store._advance(snapshot, MachineKind.ADOPTION, "pre_state_captured")
    store._persist(snapshot)
    try:
        hooks.capture_pre_state(plan, store.resolver.root)
    except Exception as exc:
        snapshot = store._advance(snapshot, MachineKind.ADOPTION, "rejected")
        store._persist(snapshot)
        raise DeploymentError(f"pre-state capture failed: {exc}") from exc
    snapshot = store._advance(snapshot, MachineKind.ADOPTION, "preflighted")
    store._persist(snapshot)
    if not operator.confirm(plan):
        snapshot = store._advance(snapshot, MachineKind.ADOPTION, "rejected")
        store._persist(snapshot)
        return snapshot
    snapshot = store._advance(snapshot, MachineKind.ADOPTION, "confirmed")
    store._persist(snapshot)
    snapshot = store._advance(snapshot, MachineKind.ADOPTION, "transferring")
    store._persist(snapshot)
    try:
        hooks.transfer(plan)
        snapshot = store._advance(snapshot, MachineKind.ADOPTION, "validating")
        store._persist(snapshot)
        snapshot = store._advance(snapshot, MachineKind.ADOPTION, "adopted")
        store._persist(snapshot)
        return snapshot
    except Exception as exc:
        snapshot = store._advance(snapshot, MachineKind.ADOPTION, "restoring")
        store._persist(snapshot)
        try:
            hooks.restore_pre_state(plan, store.resolver.root)
        except Exception as restore_exc:
            snapshot = store._advance(snapshot, MachineKind.ADOPTION, "failed")
            store._persist(snapshot)
            raise DeploymentError(
                f"adoption transfer failed and pre-state restore failed: {exc}; {restore_exc}"
            ) from exc
        snapshot = store._advance(snapshot, MachineKind.ADOPTION, "restored")
        store._persist(snapshot)
        raise DeploymentError(f"adoption transfer failed; pre-state restored: {exc}") from exc
