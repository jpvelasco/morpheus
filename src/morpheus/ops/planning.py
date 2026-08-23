"""Planning application service: one canonical identity chain (RUNM-001).

The service is the only composition point where machine profiles, workload
records, catalog snapshots, recommendations, plans, campaigns, operations,
and audit records meet. Every state-changing call persists before it returns
and rejects missing, observed, or mismatched plan/ownership identity instead
of reinterpreting it. Domain logic stays dependency-free; durability lives
behind the repository protocols.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from morpheus.core.deployment import (
    DeploymentSnapshot,
    DeploymentStore,
    LossyMigrationError,
    StageHooks,
    activate,
    attach_campaign_evidence,
    preflight,
    propose,
    rollback,
)
from morpheus.core.deployment import (
    confirm as confirm_edge,
)
from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    MachineProfile,
    Recommendation,
    WorkloadProfile,
)
from morpheus.core.repositories import OperationRecord
from morpheus.core.solver import HardwareBudget
from morpheus.ports.protocols import Clock

MANAGED_OWNERSHIP = "managed"
_OBSERVED_MARKERS = ("observed", "external")


class PlanningIdentityError(ValueError):
    """A request carries a missing, observed, or mismatched identity."""


class PlanningRepositories(Protocol):
    """Canonical record repositories the planning service composes over."""

    def save_machine_profile(self, profile: MachineProfile) -> None: ...

    def machine_profile(self, machine_id: str) -> MachineProfile | None: ...

    def save_workload(self, workload: WorkloadProfile) -> None: ...

    def workload(self, workload_id: str) -> WorkloadProfile | None: ...

    def save_plan(self, plan: DeploymentPlan) -> None: ...

    def plan(self, plan_id: str) -> DeploymentPlan | None: ...

    def plans(self) -> tuple[DeploymentPlan, ...]: ...

    def save_recommendation(self, recommendation: Recommendation) -> None: ...

    def recommendation(self, recommendation_id: str) -> Recommendation | None: ...

    def recommendations(self) -> tuple[Recommendation, ...]: ...

    def save_campaign(self, campaign: BenchmarkCampaign) -> None: ...

    def campaign(self, campaign_id: str) -> BenchmarkCampaign | None: ...

    def campaigns_for_plan(self, plan_id: str) -> tuple[BenchmarkCampaign, ...]: ...

    def save_operation(self, operation: OperationRecord) -> None: ...

    def operations_for_plan(self, plan_id: str) -> tuple[OperationRecord, ...]: ...


class AuditSink(Protocol):
    async def record_workflow_audit(self, **fields: object) -> None: ...


def require_managed_ownership(ownership: str | None) -> str:
    """Ordinary managed actions never accept observed/external identities."""
    if ownership is None or not ownership.strip():
        raise PlanningIdentityError("ownership identity is required for managed actions")
    normalized = ownership.strip().lower()
    if any(marker in normalized for marker in _OBSERVED_MARKERS):
        raise PlanningIdentityError(
            f"ownership {ownership!r} is an observed/external identity; "
            "managed actions require Morpheus-owned targets (INV-007)"
        )
    if normalized != MANAGED_OWNERSHIP:
        raise PlanningIdentityError(
            f"unsupported ownership mode {ownership!r}; expected {MANAGED_OWNERSHIP!r}"
        )
    return MANAGED_OWNERSHIP


@dataclass(frozen=True, slots=True)
class PlanningService:
    """Owns selection and promotion/rollback identity across boundaries."""

    records: PlanningRepositories
    plans: DeploymentStore
    clock: Clock | None = None
    audit: AuditSink | None = None

    # -- selection -----------------------------------------------------------

    def select_plan(
        self,
        *,
        machine: MachineProfile,
        workload: WorkloadProfile,
        catalog: tuple[DeploymentPlan, ...],
    ) -> Recommendation:
        if not catalog:
            raise PlanningIdentityError("selection requires at least one canonical plan")
        self.records.save_machine_profile(machine)
        self.records.save_workload(workload)
        for plan in catalog:
            self.records.save_plan(plan)
        selected = _select_viable(machine=machine, workload=workload, catalog=catalog)
        recommendation = Recommendation(
            recommendation_id=_recommendation_id(machine, workload, selected),
            machine_id=machine.machine_id,
            plan_ids=tuple(plan.plan_id for plan in selected),
            evidence_ranked=True,
            weights=(("deterministic-fit", 1.0),),
        )
        self.records.save_recommendation(recommendation)
        return recommendation

    def latest_recommendation(self) -> Recommendation | None:
        recommendations = self.records.recommendations()
        if not recommendations:
            return None
        return recommendations[-1]

    def machine(self, machine_id: str) -> MachineProfile | None:
        return self.records.machine_profile(machine_id)

    def plan(self, plan_id: str) -> DeploymentPlan | None:
        return self.records.plan(plan_id)

    def selections(self) -> tuple[Recommendation, ...]:
        return self.records.recommendations()

    # -- campaigns -------------------------------------------------------------

    def register_campaign(self, campaign: BenchmarkCampaign) -> BenchmarkCampaign:
        if not campaign.plan_id:
            raise PlanningIdentityError(
                "campaign records require an exact plan_id correlation; got an empty value"
            )
        known = self.plan(campaign.plan_id)
        if known is None:
            raise PlanningIdentityError(
                f"campaign {campaign.campaign_id} correlates unknown plan {campaign.plan_id!r}"
            )
        self.records.save_campaign(campaign)
        return campaign

    def campaign(self, campaign_id: str) -> BenchmarkCampaign | None:
        return self.records.campaign(campaign_id)

    # -- legacy conversion -------------------------------------------------------

    @staticmethod
    def canonical_recommendation_from_legacy(payload: dict[str, Any]) -> Recommendation:
        """Convert a legacy ranking record; reject lossy conversions explicitly.

        Legacy ranking candidates are model/engine tuples, not canonical plan
        identities, so they can only convert when the record already carries
        canonical ``plan_ids``. Anything else raises naming the missing
        identity instead of inventing one.
        """
        plan_ids = payload.get("plan_ids")
        if not plan_ids:
            ranked = payload.get("ranked") or []
            raise LossyMigrationError(
                "legacy ranking records carry model/engine candidate tuples that are not "
                f"canonical plan identities ({len(ranked)} ranked entries cannot map); "
                "rebuild the recommendation from retained evidence instead"
            )
        machine_id = payload.get("reference_machine_id") or payload.get("machine_id")
        if not machine_id:
            raise LossyMigrationError("legacy record is missing its machine profile identity")
        weights = payload.get("weights") or ()
        return Recommendation(
            recommendation_id=payload["record_id"],
            machine_id=str(machine_id),
            plan_ids=tuple(str(plan_id) for plan_id in plan_ids),
            evidence_ranked=bool(payload.get("evidence_ranked", True)),
            weights=tuple((str(key), float(value)) for key, value in weights),
        )

    # -- promotion / rollback ------------------------------------------------------

    async def promote(
        self,
        *,
        plan: DeploymentPlan,
        hooks: StageHooks,
        confirmed: bool,
        artifacts_verified: bool,
        campaign_id: str,
    ) -> DeploymentSnapshot:
        ownership = require_managed_ownership(MANAGED_OWNERSHIP)
        self.require_known_plan(plan.plan_id)
        campaign = self.require_campaign_for_plan(campaign_id, plan.plan_id)
        if not confirmed:
            raise PlanningIdentityError("promotion requires explicit operator confirmation")
        snapshot = self.plans.load(plan)
        if snapshot is None:
            if not artifacts_verified:
                raise PlanningIdentityError(
                    "promotion requires verified artifacts; acquire them first"
                )
            propose(self.plans, plan, artifacts_verified=True)
        preflight(self.plans, plan, hooks)
        attach_campaign_evidence(self.plans, plan, campaign=campaign, campaigns=self.records)
        confirmed_snapshot = confirm_edge(self.plans, plan, _OperatorConfirmed())
        promoted = activate(self.plans, plan, hooks)
        del confirmed_snapshot
        operation = self._record_operation(
            action="promote",
            plan_id=plan.plan_id,
            ownership=ownership,
            state=promoted.state,
        )
        await self._write_audit(event=operation.action, plan_id=plan.plan_id, ownership=ownership)
        return promoted

    async def rollback_plan(
        self,
        *,
        plan: DeploymentPlan,
        hooks: StageHooks,
        confirmed: bool,
    ) -> DeploymentSnapshot:
        ownership = require_managed_ownership(MANAGED_OWNERSHIP)
        self.require_known_plan(plan.plan_id)
        if not confirmed:
            raise PlanningIdentityError("rollback requires explicit operator confirmation")
        restored = rollback(self.plans, plan, hooks)
        operation = self._record_operation(
            action="rollback",
            plan_id=plan.plan_id,
            ownership=ownership,
            state=restored.state,
        )
        await self._write_audit(event=operation.action, plan_id=plan.plan_id, ownership=ownership)
        return restored

    # -- identity enforcement -----------------------------------------------

    def require_known_plan(self, plan_id: str | None) -> DeploymentPlan:
        if plan_id is None or not str(plan_id).strip():
            raise PlanningIdentityError("plan identity is missing; an exact plan_id is required")
        known = self.plan(str(plan_id))
        if known is None:
            raise PlanningIdentityError(f"unknown plan identity: {plan_id!r}")
        return known

    def require_campaign_for_plan(self, campaign_id: str, plan_id: str) -> BenchmarkCampaign:
        if not campaign_id:
            raise PlanningIdentityError(
                "campaign evidence identity is missing; promotion requires one succeeded "
                "campaign bound to this exact plan"
            )
        campaign = self.records.campaign(campaign_id)
        if campaign is None:
            raise PlanningIdentityError(f"unknown campaign identity: {campaign_id!r}")
        if campaign.plan_id != plan_id:
            raise PlanningIdentityError(
                f"campaign {campaign_id!r} correlates plan {campaign.plan_id!r}, "
                f"which mismatches the requested plan {plan_id!r}"
            )
        if campaign.state != "succeeded":
            raise PlanningIdentityError(
                f"campaign {campaign_id!r} has not succeeded (state {campaign.state!r})"
            )
        return campaign

    async def audit_event(
        self,
        *,
        event: str,
        plan_id: str | None,
        ownership: str | None,
        detail: str | None = None,
    ) -> dict[str, object]:
        """Validate identity, then persist one auditable operation record."""
        checked = require_managed_ownership(ownership)
        known = self.require_known_plan(plan_id)
        operation = self._record_operation(
            action=event,
            plan_id=known.plan_id,
            ownership=checked,
            state="audited",
            detail=detail,
        )
        await self._write_audit(event=event, plan_id=known.plan_id, ownership=checked)
        return operation.public_dict()

    # -- internals -----------------------------------------------------------

    def _operation_id(self, action: str, plan_id: str, sequence: int) -> str:
        digest_input = json.dumps(
            {"action": action, "plan_id": plan_id, "sequence": sequence}, sort_keys=True
        ).encode()
        return f"operation-{hashlib.sha256(digest_input).hexdigest()[:32]}"

    def _record_operation(
        self,
        *,
        action: str,
        plan_id: str,
        ownership: str,
        state: str,
        detail: str | None = None,
    ) -> OperationRecord:
        sequence = len(self.records.operations_for_plan(plan_id))
        last_error: Exception | None = None
        for attempt in range(64):
            operation = OperationRecord(
                operation_id=self._operation_id(action, plan_id, sequence + attempt),
                plan_id=plan_id,
                action=action,
                ownership=ownership,
                state=state,
                requested_at=self._now(),
                detail=detail,
            )
            try:
                self.records.save_operation(operation)
                return operation
            except Exception as error:  # id collision: derive the next sequence
                last_error = error
        raise last_error if last_error else RuntimeError("operation recording failed")

    async def _write_audit(self, *, event: str, plan_id: str, ownership: str) -> None:
        if self.audit is None:
            return
        coroutine = self.audit.record_workflow_audit(
            recorded_at=self._now().isoformat(),
            session_id="planning",
            workflow_id=f"plan_{event}",
            event=event,
            step_id=None,
            message=None,
            plan_id=plan_id,
            ownership=ownership,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            await coroutine
            return
        if loop.is_running():
            task = loop.create_task(coroutine)
            await task

    def _now(self) -> datetime:
        if self.clock is None:
            return datetime.now(UTC)
        return self.clock.utc_now()


class _OperatorConfirmed:
    def confirm(self, _plan: DeploymentPlan) -> bool:
        return True


def _select_viable(
    *,
    machine: MachineProfile,
    workload: WorkloadProfile,
    catalog: tuple[DeploymentPlan, ...],
) -> tuple[DeploymentPlan, ...]:
    """Deterministic fit filter shared by the API and the VSLICE fixture."""
    platform = f"{machine.platform}-{machine.architecture}"
    viable = [
        plan
        for plan in catalog
        if platform in plan.engine.platforms
        and plan.memory_estimate_bytes <= machine.memory_bytes
        and plan.disk_estimate_bytes <= machine.disk_bytes
        and workload.max_concurrency <= plan.max_concurrency
        and workload.context_tokens <= plan.context_tokens
    ]
    if not viable:
        raise PlanningIdentityError("no viable deployment plan for this machine and workload")
    return tuple(viable)


def _recommendation_id(
    machine: MachineProfile, workload: WorkloadProfile, selected: tuple[DeploymentPlan, ...]
) -> str:
    payload = json.dumps(
        {
            "machine_id": machine.machine_id,
            "workload_id": workload.workload_id,
            "plan_ids": [plan.plan_id for plan in selected],
            "evidence_ranked": True,
            "weights": [["deterministic-fit", 1.0]],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def machine_profile_from_budget(budget: HardwareBudget) -> MachineProfile:
    """Derive the exact machine identity from host budget evidence.

    The identifier is content-derived from the observed capacity facts only;
    observation time never participates (RUNM-001). Platform details stay
    ``local`` until the retained-profile work lands (R2); the full profile is
    persisted so later records reference the same machine identity.
    """
    digest = hashlib.sha256(
        json.dumps(
            {
                "accelerator": budget.accelerator,
                "memory_bytes": budget.ram_bytes,
                "storage_bytes": budget.storage_bytes,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return MachineProfile(
        machine_id=f"machine-{digest[:16]}",
        platform="local",
        architecture="local",
        accelerator=budget.accelerator,
        memory_bytes=budget.ram_bytes,
        disk_bytes=budget.storage_bytes,
    )


__all__ = [
    "MANAGED_OWNERSHIP",
    "PlanningIdentityError",
    "PlanningService",
    "machine_profile_from_budget",
    "require_managed_ownership",
]
