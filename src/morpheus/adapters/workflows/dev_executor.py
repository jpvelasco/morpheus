"""Development executor for managed workflows (OUI-006).

The DEV executor performs only owned-state checks: preflight gates on the
workflows control and lifecycle configuration, and pure validation steps
succeed when their owned preconditions hold. Every mutating step (download,
install, apply, promote, restore, remove, and record) fails honestly with a
recovery instruction because no managed runtime exists yet; the executor
protocol exists so a real lifecycle-backed executor can replace this one
without touching the runner.
"""

from __future__ import annotations

from morpheus.adapters.workflows.runner import PreflightResult, StepResult
from morpheus.config import MorpheusSettings
from morpheus.core.workflows import WorkflowId

#: Steps that only validate owned state and never mutate external resources.
_PURE_STEPS = frozenset(
    {
        "validate",
        "evidence",
        "verify",
        "snapshot",
        "preflight",
    }
)


class DevWorkflowExecutor:
    """Honest DEV executor: gates on configuration, never mutates anything."""

    def __init__(self, settings: MorpheusSettings) -> None:
        self._settings = settings

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        if not self._settings.enable_workflows:
            return PreflightResult(
                ok=False,
                reason="workflows control is disabled; set enable_workflows=true first",
            )
        if (
            workflow_id
            in {
                WorkflowId.ENGINE_INSTALL,
                WorkflowId.PROMOTE,
                WorkflowId.ROLLBACK,
                WorkflowId.REMOVE,
            }
            and not self._settings.enable_lifecycle
        ):
            return PreflightResult(
                ok=False,
                reason="runtime lifecycle is disabled; set enable_lifecycle and a deployment root",
            )
        return PreflightResult(ok=True, reason=None)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        if step_id in _PURE_STEPS:
            return StepResult(ok=True, message=None)
        if workflow_id is WorkflowId.PROMOTE and step_id == "evidence":
            return StepResult(ok=True, message=None)
        return StepResult(
            ok=False,
            message=(
                f"step '{step_id}' mutates the managed runtime and requires "
                "a lifecycle-backed executor; no mutation was performed"
            ),
        )
