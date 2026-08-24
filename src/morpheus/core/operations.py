"""Durable managed operation documents (R3, OUI-006).

A managed operation is the durable unit of workflow execution: it records
which canonical plan it belongs to, the operator confirmation, the current
step, per-step outcomes, cancellation requests, errors, and recovery
instructions. Documents are immutable value snapshots; every state change
produces a new snapshot that the persistence adapter stores atomically
before and after each durable edge.

Step plans, labels, preflight text, and recovery instructions come from the
single workflow definition registry in :mod:`morpheus.core.workflows`; this
module adds only the durable document identity, its envelope encoding, and
timestamp-free content-derived identifiers.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field, fields
from enum import StrEnum

from morpheus.core.workflows import (
    StepOutcome,
    WorkflowId,
    WorkflowState,
    WorkflowStep,
    workflow_definition,
)

SCHEMA_VERSION = 1


class ManagedOperationState(StrEnum):
    PENDING = WorkflowState.PENDING.value
    RUNNING = WorkflowState.RUNNING.value
    SUCCEEDED = WorkflowState.SUCCEEDED.value
    FAILED = WorkflowState.FAILED.value
    CANCELLED = WorkflowState.CANCELLED.value


_ACTIVE_STATES = frozenset({ManagedOperationState.PENDING, ManagedOperationState.RUNNING})


def derive_operation_id(workflow_id: WorkflowId, token: str) -> str:
    """Content-derived, timestamp-free operation id for a caller token."""
    digest = hashlib.sha256(f"{workflow_id.value}|{token}".encode()).hexdigest()
    return f"operation-{digest[:32]}"


def fresh_operation_id() -> str:
    """Caller-independent id for starts that declare no idempotency token."""
    return f"operation-{secrets.token_hex(16)}"


@dataclass(frozen=True, slots=True)
class ManagedOperation:
    operation_id: str
    workflow_id: str
    state: str = ManagedOperationState.PENDING.value
    step_index: int = 0
    step_outcomes: dict[str, str] = field(default_factory=dict)
    progress_percent: int = 0
    cancel_requested: bool = False
    confirmed: bool = False
    plan_id: str | None = None
    error: str | None = None
    recovery_instruction: str | None = None
    requested_at: str = ""
    updated_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"managed operation schema version {self.schema_version} is not supported"
            )
        try:
            WorkflowId(self.workflow_id)
        except ValueError:
            raise ValueError(
                f"unknown workflow id {self.workflow_id!r}; use a registered workflow"
            ) from None
        if self.state not in {state.value for state in ManagedOperationState}:
            raise ValueError(f"unknown managed operation state {self.state!r}")
        if self.step_index < 0 or self.step_index >= len(self._steps()):
            raise ValueError("step index escapes the workflow definition")
        if not self.requested_at:
            raise ValueError("requested_at provenance is required")

    def _steps(self) -> tuple[WorkflowStep, ...]:
        return workflow_definition(WorkflowId(self.workflow_id)).steps

    @property
    def active(self) -> bool:
        return self.state in _ACTIVE_STATES

    @property
    def current_step_id(self) -> str:
        return self._steps()[self.step_index].id

    @property
    def current_step_recovery(self) -> str:
        return self._steps()[self.step_index].recovery

    def _replace(self, **changes: object) -> ManagedOperation:
        merged = {
            field.name: getattr(self, field.name)
            for field in fields(ManagedOperation)
            if field.name != "schema_version"
        }
        merged.update(changes)
        return ManagedOperation(**merged)

    def begin(self, *, observed_at: str) -> ManagedOperation:
        if not self.active:
            return self
        return self._replace(state=ManagedOperationState.RUNNING.value, updated_at=observed_at)

    def record_outcome(
        self,
        *,
        outcome: StepOutcome,
        message: str | None = None,
        observed_at: str = "",
    ) -> ManagedOperation:
        """Record one executed step outcome and advance the durable machine."""
        steps = self._steps()
        step_id = self.current_step_id
        outcomes = dict(self.step_outcomes)
        outcomes[step_id] = outcome.value
        if outcome is StepOutcome.FAILED:
            return self._replace(
                state=ManagedOperationState.FAILED.value,
                step_outcomes=outcomes,
                error=message or f"Step {step_id} failed",
                recovery_instruction=steps[self.step_index].recovery,
                updated_at=observed_at,
            )
        if self.cancel_requested:
            return self._replace(
                state=ManagedOperationState.CANCELLED.value,
                step_outcomes=outcomes,
                error="Cancelled by operator request",
                recovery_instruction=(
                    "No partial work is trusted; re-run the workflow when ready."
                ),
                updated_at=observed_at,
            )
        if self.step_index == len(steps) - 1:
            return self._replace(
                state=ManagedOperationState.SUCCEEDED.value,
                step_outcomes=outcomes,
                progress_percent=100,
                updated_at=observed_at,
            )
        next_index = self.step_index + 1
        return self._replace(
            step_index=next_index,
            step_outcomes=outcomes,
            progress_percent=round(next_index * 100 / len(steps)),
            updated_at=observed_at,
        )

    def request_cancel(self, *, observed_at: str) -> ManagedOperation:
        if not self.active:
            return self
        return self._replace(cancel_requested=True, updated_at=observed_at)

    def fail(self, *, reason: str, recovery: str, observed_at: str) -> ManagedOperation:
        """Record an explicit failure that happened outside step execution."""
        if not self.active:
            return self
        return self._replace(
            state=ManagedOperationState.FAILED.value,
            error=reason,
            recovery_instruction=recovery,
            updated_at=observed_at,
        )

    def terminalize_interrupted(self, *, observed_at: str) -> ManagedOperation:
        """Honest post-restart disposition for an operation orphaned mid-run."""
        if not self.active:
            return self
        return self._replace(
            state=ManagedOperationState.FAILED.value,
            error=(
                f"Interrupted by restart before step '{self.current_step_id}' completed; "
                "no partial work was trusted"
            ),
            recovery_instruction=self.current_step_recovery,
            updated_at=observed_at,
        )

    def public_dict(self) -> dict[str, object]:
        definition = workflow_definition(WorkflowId(self.workflow_id))
        steps = definition.steps
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "session_id": self.operation_id,
            "workflow_id": self.workflow_id,
            "label": definition.label,
            "state": self.state,
            "current_step_id": self.current_step_id,
            "current_step_label": steps[self.step_index].label,
            "progress_percent": self.progress_percent,
            "cancel_requested": self.cancel_requested,
            "confirmed": self.confirmed,
            "plan_id": self.plan_id,
            "error": self.error,
            "recovery_instruction": self.recovery_instruction,
            # Legacy payload name for requested_at provenance.
            "started_at": self.requested_at,
            "requested_at": self.requested_at,
            "steps": [
                {
                    "id": step.id,
                    "label": step.label,
                    "description": step.description,
                    "preflight": step.preflight,
                    "recovery": step.recovery,
                    "confirm_required": step.confirm_required,
                    "outcome": self.step_outcomes.get(step.id),
                }
                for step in steps
            ],
        }

    def to_dict(self) -> dict[str, object]:
        """Legacy alias so existing payload builders keep working."""
        return self.public_dict()


def encode_operation(operation: ManagedOperation) -> bytes:
    payload = {field_.name: getattr(operation, field_.name) for field_ in fields(ManagedOperation)}
    return json.dumps(
        {
            "record_type": "managed_operation",
            "schema_version": operation.schema_version,
            "record_id": operation.operation_id,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def decode_operation(data: bytes) -> ManagedOperation:
    document = json.loads(data.decode())
    if not isinstance(document, dict):
        raise ValueError("managed operation must be a JSON object")
    if document.get("record_type") != "managed_operation":
        raise ValueError("envelope is not a managed operation")
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("managed operation payload must be an object")
    expected = {field_.name for field_ in fields(ManagedOperation)}
    if set(payload) != expected:
        raise ValueError("managed operation payload must contain exactly its declared fields")
    operation = ManagedOperation(**payload)
    if operation.schema_version != document.get("schema_version"):
        raise ValueError("managed operation schema version mismatch")
    if operation.operation_id != document.get("record_id"):
        raise ValueError("managed operation identity mismatch")
    return operation
