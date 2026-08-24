"""Explicit executor implementations for managed operations.

``UnavailableWorkflowExecutor`` is the production default: it performs no
work and refuses every step with a precise unavailability reason. The R3
exit rule forbids production routes from advertising simulated mutations,
so workflows whose lifecycle-backed executors are not yet wired must fail
honestly rather than pretend pure steps succeeded.
"""

from __future__ import annotations

from morpheus.adapters.workflows.runner import PreflightResult, StepResult
from morpheus.core.workflows import WorkflowId


class UnavailableWorkflowExecutor:
    """Honest refusal for workflows without a wired lifecycle executor."""

    def __init__(self, *, reason: str = "no lifecycle-backed executor is configured") -> None:
        self._reason = reason

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        return PreflightResult(ok=False, reason=self._reason)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        return StepResult(ok=False, message=self._reason)
