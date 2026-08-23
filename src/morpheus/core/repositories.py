"""Typed repository ports over the canonical identity/plan family (RUNM-001).

Repositories are the only durable writers of canonical records. Domain logic
stays dependency-free behind these protocols; adapters implement them over
owned roots (JSON documents under ``OwnedPathResolver`` or SQLite). Every
protocol is total over its record family: saving is idempotent by exact
record id, reads return ``None`` when absent, and no method re-derives,
renames, or partially maps an identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from morpheus.core.records import (
    BenchmarkCampaign,
    DeploymentPlan,
    MachineProfile,
    Recommendation,
    WorkloadProfile,
)


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """One state-changing managed operation bound to one canonical plan."""

    operation_id: str
    plan_id: str
    action: str
    ownership: str
    state: str
    requested_at: datetime
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.operation_id or len(self.operation_id) > 128:
            raise ValueError("operation_id must be a bounded identifier")
        if not self.plan_id or len(self.plan_id) > 128:
            raise ValueError("operation records require an exact plan_id")
        if self.ownership != "managed":
            raise ValueError(
                "managed operations must record managed ownership; "
                f"got {self.ownership!r}"
            )
        if self.requested_at.tzinfo is None:
            raise ValueError("operation timestamps must be timezone-aware")

    def public_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "plan_id": self.plan_id,
            "action": self.action,
            "ownership": self.ownership,
            "state": self.state,
            "requested_at": self.requested_at.isoformat(),
            "detail": self.detail,
        }


class MachineProfileRepository(Protocol):
    def save_machine_profile(self, profile: MachineProfile) -> None: ...

    def machine_profile(self, machine_id: str) -> MachineProfile | None: ...


class CatalogSnapshotRepository(Protocol):
    def save_catalog_snapshot(self, digest: str, collection: dict[str, Any]) -> None: ...

    def catalog_snapshot(self, digest: str) -> dict[str, Any] | None: ...


class WorkloadRepository(Protocol):
    def save_workload(self, workload: WorkloadProfile) -> None: ...

    def workload(self, workload_id: str) -> WorkloadProfile | None: ...


class RecommendationRepository(Protocol):
    def save_recommendation(self, recommendation: Recommendation) -> None: ...

    def recommendation(self, recommendation_id: str) -> Recommendation | None: ...

    def latest_recommendation(self) -> Recommendation | None: ...


class PlanRepository(Protocol):
    def save_plan(self, plan: DeploymentPlan) -> None: ...

    def plan(self, plan_id: str) -> DeploymentPlan | None: ...

    def plans(self) -> tuple[DeploymentPlan, ...]: ...


class CampaignRepository(Protocol):
    def save_campaign(self, campaign: BenchmarkCampaign) -> None: ...

    def campaign(self, campaign_id: str) -> BenchmarkCampaign | None: ...

    def campaigns_for_plan(self, plan_id: str) -> tuple[BenchmarkCampaign, ...]: ...


class OperationRepository(Protocol):
    def save_operation(self, operation: OperationRecord) -> None: ...

    def operation(self, operation_id: str) -> OperationRecord | None: ...

    def operations_for_plan(self, plan_id: str) -> tuple[OperationRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class ActivePlanState:
    active_plan_id: str | None
    last_known_good_plan_id: str | None


class ActivePlanRepository(Protocol):
    def active_state(self) -> ActivePlanState: ...

    def set_active_state(self, active_plan_id: str | None, previous_plan_id: str | None) -> None:
        ...
