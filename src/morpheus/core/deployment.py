"""Engine-neutral managed deployment orchestration (RUNM-004, RUNM-005, RUNM-006).

Staging, campaign gating, promotion, rollback, removal, and disposable adoption
are orchestrated against typed hooks and the durable architecture state
machines. Nothing here starts load or touches a runtime directly: every
side effect is a caller-provided hook, and every durable edge is a
:class:`MachineRecord` transition so a fault at any boundary leaves the
previous record unchanged and enables recovery of the last-known-good plan.

The only semantic deployment plan is :class:`morpheus.core.records.DeploymentPlan`
(RUNM-001). This module stores lifecycle aggregates around that immutable
record; it never re-derives or re-shapes plan identity.
"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    record_from_public_dict,
)
from morpheus.core.repositories import CampaignRepository
from morpheus.core.state_machines import (
    MachineKind,
    MachineRecord,
    StateMachine,
    StateTransitionError,
)

SCHEMA_VERSION = 2


class DeploymentError(ValueError):
    """A deployment operation violates its contract or its state machine."""


class LossyMigrationError(ValueError):
    """A stored document cannot be migrated without losing identity data."""


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


def _machine_record(key: str, entry: Any) -> MachineRecord | None:
    if not entry:
        return None
    return MachineRecord(
        machine=MachineKind(entry["machine"]),
        record_id=entry["record_id"],
        state=entry["state"],
        schema_version=entry["schema_version"],
        checkpoint=entry["checkpoint"],
    )


@dataclass(frozen=True, slots=True)
class DeploymentSnapshot:
    """Durable aggregate: one canonical plan plus its machines and ownership."""

    plan: DeploymentPlan
    promotion: MachineRecord | None = None
    rollback: MachineRecord | None = None
    adoption: MachineRecord | None = None
    campaign_id: str | None = None
    active: bool = False
    previous_plan_id: str | None = None
    removed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.plan, DeploymentPlan):
            raise DeploymentError("snapshot must bind one canonical deployment plan")
        if self.campaign_id is not None:
            if not self.campaign_id or len(self.campaign_id) > 128:
                raise DeploymentError("campaign correlation must be a bounded identifier")

    @property
    def state(self) -> str:
        machine = self.promotion or self.rollback or self.adoption
        if machine is None:
            raise DeploymentError("snapshot has no machine records")
        return machine.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "plan": self.plan.public_dict(),
            "promotion": self.promotion.public_dict() if self.promotion else None,
            "rollback": self.rollback.public_dict() if self.rollback else None,
            "adoption": self.adoption.public_dict() if self.adoption else None,
            "campaign_id": self.campaign_id,
            "active": self.active,
            "previous_plan_id": self.previous_plan_id,
            "removed": self.removed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeploymentSnapshot:
        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            if version == 1:
                raise LossyMigrationError(
                    "deployment snapshot schema version 1 embeds the retired lean plan "
                    "family and cannot be migrated without losing canonical identity "
                    "(missing: model.revision, model.model_format, model.license_id, "
                    "model.source, workload_profile, settings, served_aliases, "
                    "cache_policy, owned_paths, ports, health_contract_id, "
                    "benchmark_gate_id, source_evidence_digest); migrate or invalidate "
                    "the DEV document explicitly"
                )
            raise LossyMigrationError(
                f"deployment snapshot schema version {version!r} is not supported; "
                f"expected {SCHEMA_VERSION}"
            )
        return cls(
            plan=record_from_public_dict(DeploymentPlan, payload["plan"]),
            promotion=_machine_record("promotion", payload.get("promotion")),
            rollback=_machine_record("rollback", payload.get("rollback")),
            adoption=_machine_record("adoption", payload.get("adoption")),
            campaign_id=payload.get("campaign_id"),
            active=payload["active"],
            previous_plan_id=payload.get("previous_plan_id"),
            removed=payload.get("removed", False),
        )


def migrate_snapshot(payload: dict[str, Any]) -> DeploymentSnapshot:
    """Versioned migration entry point for stored snapshot documents.

    Version 1 documents embed the retired competing plan family whose lean
    candidate cannot populate the canonical identity fields. Migration never
    silently reinterprets them: they are rejected with the exact missing
    identity data named so operators can migrate or invalidate explicitly.
    """
    return DeploymentSnapshot.from_dict(payload)


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

    def _document_path(self, plan_id: str) -> str:
        return f"deployments/{plan_id}.json"

    def get_plan(self, plan_id: str) -> DeploymentPlan | None:
        """Resolve one canonical plan by its exact identifier."""
        try:
            snapshot = self.load_by_id(plan_id)
        except DeploymentError:
            return None
        return snapshot.plan

    def load_by_id(self, plan_id: str) -> DeploymentSnapshot:
        relative = self._document_path(plan_id)
        raw = Path(self.root, relative)
        if raw.is_symlink():
            raise OwnedPathError("deployment documents must not be symbolic links")
        path = self._path(relative)
        if not path.exists():
            raise DeploymentError(f"no tracked deployment plan: {plan_id}")
        payload = self._read_json(path)
        if isinstance(payload, dict) and payload.get("schema_version") != SCHEMA_VERSION:
            return migrate_snapshot(payload)
        return DeploymentSnapshot.from_dict(payload)

    def load(self, plan: DeploymentPlan) -> DeploymentSnapshot | None:
        try:
            return self.load_by_id(plan.plan_id)
        except DeploymentError:
            return None

    def snapshots(self) -> tuple[DeploymentSnapshot, ...]:
        paths = sorted(self._path("deployments").glob("*.json"))
        snapshots: list[DeploymentSnapshot] = []
        for path in paths:
            payload = self._read_json(f"deployments/{path.name}")
            if isinstance(payload, dict) and payload.get("schema_version") != SCHEMA_VERSION:
                snapshots.append(migrate_snapshot(payload))
            else:
                snapshots.append(DeploymentSnapshot.from_dict(payload))
        return tuple(snapshots)

    def active(self) -> DeploymentSnapshot | None:
        self.initialize()
        state = self._read_json(self._path("state.json"))
        active_id = state.get("active_plan_id")
        if not active_id:
            return None
        try:
            snapshot = self.load_by_id(active_id)
        except DeploymentError:
            return None
        return snapshot if snapshot.active else None

    def last_known_good(self) -> DeploymentSnapshot | None:
        self.initialize()
        state = self._read_json(self._path("state.json"))
        previous_id = state.get("previous_plan_id")
        if not previous_id:
            return None
        try:
            return self.load_by_id(previous_id)
        except DeploymentError:
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

    def _persist(self, snapshot: DeploymentSnapshot) -> None:
        self.initialize()
        self._write_json(
            self._path(self._document_path(snapshot.plan.plan_id)), snapshot.to_dict()
        )

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
            campaign_id=snapshot.campaign_id,
            active=snapshot.active,
            previous_plan_id=snapshot.previous_plan_id,
            removed=snapshot.removed,
        )

    def _read_json(self, path: Path | str) -> dict[str, Any]:
        resolved = self._path(path) if isinstance(path, str) else path
        if resolved.is_symlink():
            raise OwnedPathError("deployment documents must not be symbolic links")
        if not resolved.exists():
            raise DeploymentError(f"deployment document missing: {resolved.name}")
        payload: dict[str, Any] = json.loads(resolved.read_text(encoding="utf-8"))
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def attach_campaign_evidence(
    store: DeploymentStore,
    plan: DeploymentPlan,
    *,
    campaign: BenchmarkCampaign,
    campaigns: CampaignRepository,
) -> DeploymentSnapshot:
    """Correlate one completed canonical campaign with the staged plan.

    Promotion beyond this point requires the campaign to reference exactly
    this plan and to have succeeded under its declared limits.
    """
    snapshot = store.load(plan)
    if snapshot is None or snapshot.state != "preflighted":
        raise DeploymentError("campaign evidence requires a preflighted plan")
    if snapshot.campaign_id is not None:
        if snapshot.campaign_id == campaign.campaign_id:
            return snapshot
        raise DeploymentError(
            f"plan already carries campaign evidence {snapshot.campaign_id}; "
            f"refusing to replace it with {campaign.campaign_id}"
        )
    if campaign.plan_id != plan.plan_id:
        raise DeploymentError(
            f"campaign {campaign.campaign_id} correlates plan {campaign.plan_id}, "
            f"not this plan {plan.plan_id}"
        )
    if campaign.state != "succeeded":
        raise DeploymentError(f"campaign gate failed: campaign state {campaign.state}")
    campaigns.save_campaign(campaign)
    updated = DeploymentSnapshot(
        plan=snapshot.plan,
        promotion=snapshot.promotion,
        rollback=snapshot.rollback,
        adoption=snapshot.adoption,
        campaign_id=campaign.campaign_id,
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
        campaign_id=promoted.campaign_id,
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
            campaign_id=previous.campaign_id,
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
                    campaign_id=previous.campaign_id,
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
        campaign_id=snapshot.campaign_id,
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
        campaign_id=previous.campaign_id,
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
        campaign_id=snapshot.campaign_id,
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
        campaign_id=snapshot.campaign_id,
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
