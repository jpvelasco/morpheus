"""Explicit executor implementations for managed operations.

``ManagedLifecycleExecutor`` is the production default. It runs the
workflows that have a wired lifecycle (currently ``model_acquire``) and
honestly refuses every other workflow. The R3 exit rule forbids production
routes from advertising simulated mutations.
"""

from __future__ import annotations

from pathlib import Path

from morpheus.adapters.workflows.runner import PreflightResult, StepResult
from morpheus.core.acquisition import (
    AcquisitionCache,
    AcquisitionError,
    AcquisitionPlan,
    AcquisitionPolicy,
    CacheQuota,
)
from morpheus.core.operations import ManagedOperation
from morpheus.core.records import DeploymentPlan
from morpheus.core.workflows import WorkflowId
from morpheus.ops.planning import PlanningService


class UnavailableWorkflowExecutor:
    """Honest refusal for workflows without a wired lifecycle executor."""

    def __init__(self, *, reason: str = "no lifecycle-backed executor is configured") -> None:
        self._reason = reason

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        return PreflightResult(ok=False, reason=self._reason)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        return StepResult(ok=False, message=self._reason)


class ManagedLifecycleExecutor:
    """Per-workflow production executor with honest fallback."""

    def __init__(
        self,
        *,
        planning: PlanningService,
        data_dir: Path,
        fallback: UnavailableWorkflowExecutor | None = None,
    ) -> None:
        self._planning = planning
        self._data_dir = Path(data_dir)
        self._fallback = fallback or UnavailableWorkflowExecutor()
        self._bound: dict[str, ManagedOperation] = {}
        self._acquire: dict[str, AcquisitionPlan] = {}

    def bind(self, operation: ManagedOperation) -> None:
        self._bound[operation.workflow_id] = operation
        self._acquire.pop(operation.workflow_id, None)

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        if workflow_id is not WorkflowId.MODEL_ACQUIRE:
            return await self._fallback.preflight(workflow_id)
        try:
            self._acquire[workflow_id.value] = self._acquisition_plan(workflow_id)
        except (AcquisitionError, ValueError) as error:
            return PreflightResult(ok=False, reason=str(error))
        return PreflightResult(ok=True)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        if workflow_id is not WorkflowId.MODEL_ACQUIRE:
            return await self._fallback.execute(step_id, workflow_id)
        try:
            plan = self._acquire.get(workflow_id.value) or self._acquisition_plan(workflow_id)
            self._acquire[workflow_id.value] = plan
            cache = AcquisitionCache(self._data_dir / "acquisition")
            cache.initialize()
            handler = {
                "preflight": self._reserve,
                "download": self._download,
                "verify": self._verify,
                "register": self._register,
            }.get(step_id)
            if handler is None:
                return StepResult(ok=False, message=f"unknown acquire step {step_id!r}")
            return handler(cache, plan)
        except (AcquisitionError, OSError, ValueError) as error:
            return StepResult(ok=False, message=str(error))

    def _reserve(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        cache.begin(
            plan,
            policy=AcquisitionPolicy(permitted_sources=(str(self._data_dir / "acquire-source"),)),
            free_bytes=plan.declared_size_bytes * 4,
            quota=CacheQuota(max_bytes=plan.declared_size_bytes * 4),
        )
        return StepResult(ok=True, message="owned cache reserved")

    def _download(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        cache.append_chunk(plan, Path(plan.source_url).read_bytes())
        return StepResult(ok=True, message="artifact staged")

    def _verify(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        cache.verify(plan)
        return StepResult(ok=True, message="digest verified")

    def _register(self, cache: AcquisitionCache, plan: AcquisitionPlan) -> StepResult:
        record = cache.lookup(plan.expected_sha256)
        if record is None:
            return StepResult(ok=False, message="verified artifact is not registered")
        return StepResult(ok=True, message=record.record_id)

    def _acquisition_plan(self, workflow_id: WorkflowId) -> AcquisitionPlan:
        bound = self._bound.get(workflow_id.value)
        if bound is None or not bound.plan_id:
            raise ValueError("model acquire requires a bound canonical plan")
        known: DeploymentPlan = self._planning.require_known_plan(bound.plan_id)
        source = self._data_dir / "acquire-source" / known.model.artifact_digest
        if not source.is_file():
            raise ValueError(f"acquire source is missing: {source}")
        size = source.stat().st_size
        return AcquisitionPlan(
            entry_id=known.model.model_id,
            kind="model",
            revision=known.model.revision,
            source_url=str(source),
            expected_sha256=known.model.artifact_digest,
            declared_size_bytes=size,
            license=known.model.license_id,
        )
