"""Workflow runner: preflight, cooperative execution, cancellation, audit.

Retired from production composition by the R3 durable operation service
(``morpheus.ops.operation_service``); retained only for explicit test and
development injection. The runner drives a workflow definition through its
steps against an executor adapter. It records every transition in the audit
sink, honors cancellation at step boundaries, and never trusts partial work:
a failed workflow ends in ``FAILED`` with the step's recovery instruction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from morpheus.core.workflows import (
    StepOutcome,
    WorkflowId,
    WorkflowSession,
    WorkflowState,
    advance_step,
    begin_workflow,
    request_cancellation,
    workflow_definition,
)


class WorkflowRunnerError(RuntimeError):
    """Raised when a workflow cannot start or be cancelled."""


@dataclass(frozen=True, slots=True)
class PreflightResult:
    ok: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    ok: bool
    message: str | None = None


class WorkflowExecutor(Protocol):
    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult: ...

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult: ...


class AuditSink(Protocol):
    async def record_workflow_audit(self, **fields: object) -> None: ...


class JsonlAuditSink:
    """Append-only JSONL audit sink for workflows."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def record_workflow_audit(self, **fields: object) -> None:
        def write() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(fields) + "\n")

        import asyncio

        await asyncio.to_thread(write)


class LazyAuditStore:
    """Initializes an async store before its first audit record."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._initialized = False

    async def record_workflow_audit(self, **fields: object) -> None:
        if not self._initialized:
            await self._store.initialize()
            self._initialized = True
        await self._store.record_workflow_audit(**fields)

    def record_workflow_audit_sync(self, **fields: object) -> None:
        """Composition-time passthrough for restart recovery audit rows."""
        sync_writer = getattr(self._store, "record_workflow_audit_sync", None)
        if sync_writer is None:
            raise TypeError("audit store does not support synchronous recovery writes")
        sync_writer(**fields)


class WorkflowRunner:
    """Runs at most one active workflow at a time per workflow id."""

    def __init__(
        self,
        *,
        executor: WorkflowExecutor,
        audit: AuditSink | None = None,
    ) -> None:
        self._executor = executor
        self._audit = audit
        self._sessions: dict[WorkflowId, WorkflowSession] = {}

    async def start(
        self,
        workflow_id: WorkflowId,
        *,
        confirmed: bool,
        session_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        definition = workflow_definition(workflow_id)
        if not confirmed and any(step.confirm_required for step in definition.steps):
            raise WorkflowRunnerError("workflow requires operator confirmation")
        if workflow_id in self._sessions and self._sessions[workflow_id].state in {
            "pending",
            "running",
        }:
            raise WorkflowRunnerError("a workflow is already running for this id")
        session = begin_workflow(workflow_id, observed_at=observed_at)
        session.session_id = session_id
        await self._record_audit(
            recorded_at=observed_at,
            session_id=session_id,
            workflow_id=workflow_id.value,
            event="started",
            step_id=None,
            message=None,
        )
        preflight = await self._executor.preflight(workflow_id)
        if not preflight.ok:
            session.state = WorkflowState.FAILED
            session.error = preflight.reason or "preflight failed"
            session.recovery_instruction = definition.steps[0].recovery
            self._sessions[workflow_id] = session
            await self._record_audit(
                recorded_at=observed_at,
                session_id=session_id,
                workflow_id=workflow_id.value,
                event="preflight_failed",
                step_id=None,
                message=session.error,
            )
            return {"started": False, "session": session.to_dict()}
        self._sessions[workflow_id] = session
        for step in definition.steps:
            if session.state is WorkflowState.CANCELLED:
                break
            await self._record_audit(
                recorded_at=observed_at,
                session_id=session_id,
                workflow_id=workflow_id.value,
                event="step_started",
                step_id=step.id,
                message=None,
            )
            result = await self._executor.execute(step.id, workflow_id)
            session, outcome = advance_step(
                session,
                step_id=step.id,
                outcome=StepOutcome.SUCCEEDED if result.ok else StepOutcome.FAILED,
                observed_at=observed_at,
                message=result.message,
            )
            await self._record_audit(
                recorded_at=observed_at,
                session_id=session_id,
                workflow_id=workflow_id.value,
                event=(
                    "step_succeeded"
                    if outcome is StepOutcome.SUCCEEDED
                    else "step_failed"
                    if outcome is StepOutcome.FAILED
                    else "cancelled"
                ),
                step_id=step.id,
                message=result.message,
            )
            if session.state in {WorkflowState.FAILED, WorkflowState.CANCELLED}:
                break
        await self._record_audit(
            recorded_at=observed_at,
            session_id=session_id,
            workflow_id=workflow_id.value,
            event=session.state.value,
            step_id=None,
            message=session.error,
        )
        return {"started": True, "session": session.to_dict()}

    async def cancel(self, workflow_id: WorkflowId, *, observed_at: str) -> bool:
        session = self._sessions.get(workflow_id)
        if session is None:
            raise WorkflowRunnerError("no workflow session exists")
        session = request_cancellation(session, observed_at=observed_at)
        self._sessions[workflow_id] = session
        if self._audit is not None:
            await self._record_audit(
                recorded_at=observed_at,
                session_id=session.session_id,
                workflow_id=workflow_id.value,
                event="cancel_requested",
                step_id=None,
                message=None,
            )
        return True

    async def session(self, workflow_id: WorkflowId) -> WorkflowSession | None:
        return self._sessions.get(workflow_id)

    async def _record_audit(self, **fields: object) -> None:
        if self._audit is not None:
            await self._audit.record_workflow_audit(**fields)
