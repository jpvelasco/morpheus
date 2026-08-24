"""Durable managed operation service (R3).

Owns workflow execution for production routes. Long operations run outside
the request task under a bounded concurrency limit; every durable edge —
acceptance, step start, step outcome, terminal state, cancellation request,
restart recovery — is persisted as it happens so an API restart never loses
or silently rewinds operator work.

Starts are idempotent by caller-declared operation token: the token joins a
timestamp-free content-derived operation identity, and replaying a token
returns the already-recorded operation without re-executing any step.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from morpheus.adapters.persistence.operation_store import OperationStore
from morpheus.adapters.workflows.runner import (
    PreflightResult,
    StepResult,
    WorkflowExecutor,
)
from morpheus.core.operations import (
    ManagedOperation,
    ManagedOperationState,
    derive_operation_id,
    fresh_operation_id,
)
from morpheus.core.workflows import StepOutcome, WorkflowId, workflow_definition
from morpheus.ports.protocols import Clock


class OperationServiceError(RuntimeError):
    """Raised when an operation cannot be accepted, cancelled, or found."""


class OperationAuditSink(Protocol):
    async def record_workflow_audit(self, **fields: object) -> None: ...


_MAX_LIST = 50


def _task_exception_guard(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        asyncio.get_running_loop().call_exception_handler(
            {
                "message": "managed operation driver failed",
                "exception": task.exception(),
            }
        )


class OperationService:
    """Composes executor ports into durable, restart-safe operations."""

    def __init__(
        self,
        *,
        executor: WorkflowExecutor,
        store: OperationStore,
        clock: Clock,
        audit: OperationAuditSink | None = None,
        max_concurrent: int = 2,
    ) -> None:
        self._executor = executor
        self._store = store
        self._clock = clock
        self._audit = audit
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self._tasks: set[asyncio.Task[None]] = set()
        # Current durable snapshot per live operation. All mutation happens
        # in synchronous sections on the event loop, so readers never see a
        # torn state and a cancel request can never be lost to a stale copy.
        self._live: dict[str, ManagedOperation] = {}

    # ------------------------------------------------------------------ queries

    def _now(self) -> str:
        return self._clock.utc_now().isoformat()

    def list_operations(self) -> tuple[ManagedOperation, ...]:
        return self._store.list_all()[:_MAX_LIST]

    def latest_for_workflow(self, workflow_id: WorkflowId) -> ManagedOperation | None:
        newest: ManagedOperation | None = None
        for operation in self._store.list_all():
            if operation.workflow_id != workflow_id.value:
                continue
            if newest is None or operation.updated_at > newest.updated_at:
                newest = operation
        return newest

    def require_latest(self, workflow_id: WorkflowId) -> ManagedOperation:
        operation = self.latest_for_workflow(workflow_id)
        if operation is None:
            raise OperationServiceError("no workflow session exists")
        return operation

    def require_active(self, workflow_id: WorkflowId) -> ManagedOperation:
        operation = self.latest_for_workflow(workflow_id)
        if operation is None or not operation.active:
            raise OperationServiceError("no running workflow session exists for this id")
        return operation

    # ------------------------------------------------------------------ mutation

    async def start(
        self,
        workflow_id: WorkflowId,
        *,
        confirmed: bool,
        token: str | None = None,
        plan_id: str | None = None,
    ) -> dict[str, object]:
        definition = workflow_definition(workflow_id)
        if not confirmed and any(step.confirm_required for step in definition.steps):
            raise OperationServiceError("workflow requires operator confirmation")

        operation_id = derive_operation_id(workflow_id, token) if token else fresh_operation_id()
        existing = self._store.get(operation_id)
        if existing is not None:
            return self._result(existing, started=False)

        for operation in self.list_operations():
            if operation.active and operation.workflow_id == workflow_id.value:
                raise OperationServiceError("a workflow is already running for this id")

        now = self._now()
        operation = ManagedOperation(
            operation_id=operation_id,
            workflow_id=workflow_id.value,
            confirmed=confirmed,
            plan_id=plan_id,
            requested_at=now,
            updated_at=now,
        )
        self._persist(operation)
        await self._audit_event(operation, event="started", step_id=None, message=None)

        try:
            preflight: PreflightResult = await self._executor.preflight(workflow_id)
        except Exception as error:
            failed = operation.fail(
                reason=f"preflight crashed: {error}",
                recovery=definition.steps[0].recovery,
                observed_at=self._now(),
            )
            self._persist(failed)
            await self._audit_event(
                failed, event="preflight_failed", step_id=None, message=failed.error
            )
            return self._result(failed, started=False)

        if not preflight.ok:
            failed = operation.fail(
                reason=preflight.reason or "preflight failed",
                recovery=definition.steps[0].recovery,
                observed_at=self._now(),
            )
            self._persist(failed)
            await self._audit_event(
                failed, event="preflight_failed", step_id=None, message=failed.error
            )
            return self._result(failed, started=False)

        running = operation.begin(observed_at=self._now())
        self._persist(running)
        self._schedule(running.operation_id)
        return self._result(running, started=True)

    async def cancel(self, workflow_id: WorkflowId) -> dict[str, object]:
        operation = self.require_active(workflow_id)
        requested = operation.request_cancel(observed_at=self._now())
        self._persist(requested)
        await self._audit_event(requested, event="cancel_requested", step_id=None, message=None)
        return {"cancelled": True, "session": requested.public_dict()}

    # ------------------------------------------------------------------ engine

    @staticmethod
    def _result(operation: ManagedOperation, *, started: bool) -> dict[str, object]:
        return {
            "started": started,
            "operation_id": operation.operation_id,
            "session": operation.public_dict(),
        }

    def _schedule(self, operation_id: str) -> None:
        task = asyncio.create_task(self._drive(operation_id))
        self._tasks.add(task)
        task.add_done_callback(_task_exception_guard)
        task.add_done_callback(self._tasks.discard)

    def _persist(self, operation: ManagedOperation) -> None:
        self._store.save(operation)
        self._live[operation.operation_id] = operation

    async def _drive(self, operation_id: str) -> None:
        async with self._semaphore:
            while True:
                current = self._live.get(operation_id)
                if current is None or not current.active:
                    return
                step_id = current.current_step_id
                await self._audit_event(
                    current, event="step_started", step_id=step_id, message=None
                )
                try:
                    result: StepResult = await self._executor.execute(
                        step_id, WorkflowId(current.workflow_id)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    result = StepResult(ok=False, message=str(error))
                outcome = StepOutcome.SUCCEEDED if result.ok else StepOutcome.FAILED
                # Re-read the shared live document so a cancel requested while
                # the step executed is honored at this boundary.
                updated = (self._live.get(operation_id) or current).record_outcome(
                    outcome=outcome,
                    message=result.message,
                    observed_at=self._now(),
                )
                self._persist(updated)
                event = (
                    "step_succeeded"
                    if updated.state == ManagedOperationState.RUNNING.value
                    else "step_failed"
                    if updated.state == ManagedOperationState.FAILED.value
                    else "succeeded"
                    if updated.state == ManagedOperationState.SUCCEEDED.value
                    else "cancelled"
                )
                await self._audit_event(
                    updated, event=event, step_id=step_id, message=result.message
                )

    # ------------------------------------------------------------------ recovery

    def recover_interrupted(self) -> int:
        """Terminalize operations orphaned by a process restart.

        Called synchronously during application composition, before any
        request can observe a stale ``running`` state. The interrupted
        document keeps its full history plus an explicit failure reason
        and the current step's recovery instruction.
        """
        recovered = 0
        for operation in self._store.list_all():
            if not operation.active:
                continue
            terminalized = operation.terminalize_interrupted(observed_at=self._now())
            self._persist(terminalized)
            sink = getattr(self._audit, "record_workflow_audit_sync", None)
            if sink is not None:
                sink(
                    recorded_at=self._now(),
                    session_id=terminalized.operation_id,
                    workflow_id=terminalized.workflow_id,
                    event="interrupted",
                    step_id=None,
                    message=terminalized.error,
                    plan_id=terminalized.plan_id,
                    ownership="managed" if terminalized.plan_id else None,
                )
            recovered += 1
        return recovered

    # ------------------------------------------------------------------ audit

    async def _audit_event(
        self,
        operation: ManagedOperation,
        *,
        event: str,
        step_id: str | None,
        message: str | None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record_workflow_audit(
            recorded_at=self._now(),
            session_id=operation.operation_id,
            workflow_id=operation.workflow_id,
            event=event,
            step_id=step_id,
            message=message,
            plan_id=operation.plan_id,
            ownership="managed" if operation.plan_id else None,
        )
