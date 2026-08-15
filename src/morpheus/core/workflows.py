"""Managed workflow definitions and session state machine (OUI-006).

Workflows are the authenticated, multi-step operations of the managed
runtime: model acquisition, engine installation, engine configuration,
benchmark, promotion, rollback, and removal. Every step carries a preflight
description, an optional confirmation requirement, and precise recovery
instructions. Sessions are cooperative: cancellation is requested by the
operator and honored at the next step boundary, and every transition is
recorded in the audit journal by the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkflowId(StrEnum):
    MODEL_ACQUIRE = "model_acquire"
    ENGINE_INSTALL = "engine_install"
    ENGINE_CONFIGURE = "engine_configure"
    BENCHMARK = "benchmark"
    PROMOTE = "promote"
    ROLLBACK = "rollback"
    REMOVE = "remove"


class WorkflowState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    id: str
    label: str
    description: str
    preflight: str
    recovery: str
    confirm_required: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_id: WorkflowId
    label: str
    description: str
    steps: tuple[WorkflowStep, ...]


@dataclass(slots=True)
class WorkflowSession:
    workflow_id: WorkflowId
    state: WorkflowState
    step_index: int
    step_outcomes: dict[str, StepOutcome]
    progress_percent: int
    cancel_requested: bool
    error: str | None
    recovery_instruction: str | None
    started_at: str
    definition: WorkflowDefinition
    session_id: str = field(default="")

    @property
    def current_step_id(self) -> str:
        return self.definition.steps[self.step_index].id

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id.value,
            "label": self.definition.label,
            "state": self.state.value,
            "current_step_id": self.current_step_id,
            "current_step_label": self.definition.steps[self.step_index].label,
            "progress_percent": self.progress_percent,
            "cancel_requested": self.cancel_requested,
            "error": self.error,
            "recovery_instruction": self.recovery_instruction,
            "started_at": self.started_at,
            "steps": [
                {
                    "id": step.id,
                    "label": step.label,
                    "description": step.description,
                    "preflight": step.preflight,
                    "recovery": step.recovery,
                    "confirm_required": step.confirm_required,
                    "outcome": (
                        self.step_outcomes[step.id].value if step.id in self.step_outcomes else None
                    ),
                }
                for step in self.definition.steps
            ],
        }


_MODEL_ACQUIRE = WorkflowDefinition(
    workflow_id=WorkflowId.MODEL_ACQUIRE,
    label="Model acquisition",
    description="Download and verify a model into the owned model store.",
    steps=(
        WorkflowStep(
            id="preflight",
            label="Preflight",
            description="Check owned model store, disk budget, and network policy.",
            preflight="Model store must be owned, writable, and within the disk budget.",
            recovery="Resolve owned-path or disk budget issues, then restart the workflow.",
        ),
        WorkflowStep(
            id="download",
            label="Download",
            description="Fetch the model archive through the qualified source.",
            preflight="The qualified model source must be reachable.",
            recovery="Retry the download; a partial archive is never used.",
        ),
        WorkflowStep(
            id="verify",
            label="Verify",
            description="Checksum and unpack the model archive.",
            preflight="The recorded digest must match the published digest.",
            recovery="Re-acquire the model; checksummed archives are never partially trusted.",
        ),
        WorkflowStep(
            id="register",
            label="Register",
            description="Record the model in the owned catalog.",
            preflight="The catalog entry must not already exist.",
            recovery="Inspect the catalog; the model may already be registered.",
        ),
    ),
)

_ENGINE_INSTALL = WorkflowDefinition(
    workflow_id=WorkflowId.ENGINE_INSTALL,
    label="Engine installation",
    description="Install a qualified engine binary into the managed runtime.",
    steps=(
        WorkflowStep(
            id="preflight",
            label="Preflight",
            description="Check deployment root ownership, disk budget, and target tier.",
            preflight="Deployment root must be owned and within the disk budget.",
            recovery="Resolve ownership or disk budget issues, then restart the workflow.",
        ),
        WorkflowStep(
            id="install",
            label="Install",
            description="Place the checksummed engine package under the deployment root.",
            preflight="The qualified engine package must be reachable and digest-matched.",
            recovery="Retry installation; failed replacement keeps the previous engine.",
        ),
        WorkflowStep(
            id="smoke",
            label="Smoke test",
            description="Verify the installed engine starts and reports a version.",
            preflight="The engine must be executable by the service user.",
            recovery="Check engine logs; reinstall or fall back to the previous engine.",
        ),
    ),
)

_ENGINE_CONFIGURE = WorkflowDefinition(
    workflow_id=WorkflowId.ENGINE_CONFIGURE,
    label="Engine configuration",
    description="Apply a validated engine configuration with a restart.",
    steps=(
        WorkflowStep(
            id="validate",
            label="Validate",
            description="Validate the proposed configuration against the schema.",
            preflight="The configuration must parse and pass schema validation.",
            recovery="Correct the configuration and restart the workflow.",
        ),
        WorkflowStep(
            id="backup",
            label="Backup",
            description="Snapshot the previous configuration.",
            preflight="The configuration store must be writable.",
            recovery="Restore the snapshot manually if the workflow is interrupted.",
        ),
        WorkflowStep(
            id="apply",
            label="Apply",
            description="Write the new configuration and restart the engine.",
            preflight="The engine must be owned and restartable.",
            recovery="Restart the engine; the previous configuration remains backed up.",
        ),
    ),
)

_BENCHMARK = WorkflowDefinition(
    workflow_id=WorkflowId.BENCHMARK,
    label="Benchmark",
    description="Run the benchmark campaign against the promoted engine.",
    steps=(
        WorkflowStep(
            id="preflight",
            label="Preflight",
            description="Check benchmark fixtures, engine readiness, and store ownership.",
            preflight="The engine must be healthy and the benchmark store owned.",
            recovery="Resolve engine health or store ownership, then restart the workflow.",
        ),
        WorkflowStep(
            id="run",
            label="Run",
            description="Execute the benchmark campaign and collect samples.",
            preflight="The qualified workload profile must be available.",
            recovery="Re-run the campaign; partial runs are not recorded as evidence.",
        ),
        WorkflowStep(
            id="record",
            label="Record",
            description="Persist the completed run in the benchmark history.",
            preflight="The run summary must pass validation.",
            recovery="Re-run the campaign if the record is incomplete.",
        ),
    ),
)

_PROMOTE = WorkflowDefinition(
    workflow_id=WorkflowId.PROMOTE,
    label="Promotion",
    description="Promote a benchmarked engine configuration to the active tier.",
    steps=(
        WorkflowStep(
            id="evidence",
            label="Evidence check",
            description="Confirm the candidate has passing benchmark evidence.",
            preflight="The candidate must have a completed benchmark run.",
            recovery="Run the benchmark workflow before promoting.",
        ),
        WorkflowStep(
            id="backup",
            label="Backup",
            description="Snapshot the active configuration.",
            preflight="The configuration store must be writable.",
            recovery="Restore the snapshot manually if the workflow is interrupted.",
        ),
        WorkflowStep(
            id="promote",
            label="Promote",
            description="Switch the active engine to the candidate configuration.",
            preflight="The candidate must be installed and smoke-tested.",
            recovery="Roll back via the rollback workflow or restore the snapshot.",
        ),
    ),
)

_ROLLBACK = WorkflowDefinition(
    workflow_id=WorkflowId.ROLLBACK,
    label="Rollback",
    description="Restore the previous engine configuration.",
    steps=(
        WorkflowStep(
            id="snapshot",
            label="Snapshot check",
            description="Confirm a rollback snapshot exists.",
            preflight="A previous configuration snapshot must exist.",
            recovery="No snapshot exists; restore from backup or reinstall the engine.",
        ),
        WorkflowStep(
            id="restore",
            label="Restore",
            description="Restore the snapshot and restart the engine.",
            preflight="The engine must be owned and restartable.",
            recovery="Retry the restore; the snapshot remains until verified.",
        ),
        WorkflowStep(
            id="verify",
            label="Verify",
            description="Confirm the engine starts with the restored configuration.",
            preflight="The engine must report healthy after restart.",
            recovery="Check engine logs; the snapshot is still in place.",
        ),
    ),
)

_REMOVE = WorkflowDefinition(
    workflow_id=WorkflowId.REMOVE,
    label="Removal",
    description="Remove a model or engine with confirmed destructive intent.",
    steps=(
        WorkflowStep(
            id="confirm",
            label="Confirmation",
            description="Operator confirms removal of the owned resource.",
            preflight="The resource must be Morpheus-owned and not the active engine.",
            recovery="Abort the workflow; nothing is removed until confirmed.",
            confirm_required=True,
        ),
        WorkflowStep(
            id="remove",
            label="Remove",
            description="Delete the owned resource and its journal entries.",
            preflight="The resource must still be owned and unused.",
            recovery="Re-run removal after resolving ownership or usage blockers.",
        ),
    ),
)

_DEFINITIONS: dict[WorkflowId, WorkflowDefinition] = {
    definition.workflow_id: definition
    for definition in (
        _MODEL_ACQUIRE,
        _ENGINE_INSTALL,
        _ENGINE_CONFIGURE,
        _BENCHMARK,
        _PROMOTE,
        _ROLLBACK,
        _REMOVE,
    )
}


def workflow_definitions() -> tuple[WorkflowDefinition, ...]:
    return tuple(_DEFINITIONS.values())


def workflow_definition(workflow_id: WorkflowId) -> WorkflowDefinition:
    return _DEFINITIONS[workflow_id]


def workflow_recovery_instruction(workflow_id: WorkflowId, step_id: str) -> str:
    definition = _DEFINITIONS[workflow_id]
    for step in definition.steps:
        if step.id == step_id:
            return step.recovery
    return definition.steps[-1].recovery


def begin_workflow(workflow_id: WorkflowId, *, observed_at: str) -> WorkflowSession:
    definition = _DEFINITIONS[workflow_id]
    return WorkflowSession(
        workflow_id=workflow_id,
        state=WorkflowState.PENDING,
        step_index=0,
        step_outcomes={},
        progress_percent=0,
        cancel_requested=False,
        error=None,
        recovery_instruction=None,
        started_at=observed_at,
        definition=definition,
    )


def request_cancellation(session: WorkflowSession, *, observed_at: str) -> WorkflowSession:
    if session.state not in {WorkflowState.PENDING, WorkflowState.RUNNING}:
        return session
    session.cancel_requested = True
    return session


def advance_step(
    session: WorkflowSession,
    *,
    step_id: str,
    outcome: StepOutcome,
    observed_at: str,
    message: str | None = None,
) -> tuple[WorkflowSession, StepOutcome | None]:
    """Record one step outcome and advance the session state machine."""
    if session.state in {WorkflowState.SUCCEEDED, WorkflowState.FAILED, WorkflowState.CANCELLED}:
        return session, None
    if session.state is WorkflowState.PENDING and step_id == session.current_step_id:
        session.state = WorkflowState.RUNNING
    if session.cancel_requested:
        session.state = WorkflowState.CANCELLED
        session.error = "Cancelled by operator request"
        session.recovery_instruction = "No partial work is trusted; re-run the workflow when ready."
        return session, None
    if step_id != session.current_step_id:
        return session, None
    session.step_outcomes[step_id] = outcome
    if outcome is StepOutcome.FAILED:
        session.state = WorkflowState.FAILED
        session.error = message or f"Step {step_id} failed"
        session.recovery_instruction = workflow_recovery_instruction(session.workflow_id, step_id)
        return session, outcome
    if session.step_index == len(session.definition.steps) - 1:
        session.state = WorkflowState.SUCCEEDED
        session.progress_percent = 100
        session.error = None
        return session, outcome
    session.step_index += 1
    session.progress_percent = round(session.step_index * 100 / len(session.definition.steps))
    return session, outcome
