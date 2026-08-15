from __future__ import annotations

from morpheus.core.workflows import (
    StepOutcome,
    WorkflowId,
    WorkflowState,
    advance_step,
    begin_workflow,
    request_cancellation,
    workflow_definition,
    workflow_definitions,
    workflow_recovery_instruction,
)


def test_workflow_registry_defines_all_seven_managed_workflows() -> None:
    definitions = workflow_definitions()
    assert {definition.workflow_id for definition in definitions} == {
        WorkflowId.MODEL_ACQUIRE,
        WorkflowId.ENGINE_INSTALL,
        WorkflowId.ENGINE_CONFIGURE,
        WorkflowId.BENCHMARK,
        WorkflowId.PROMOTE,
        WorkflowId.ROLLBACK,
        WorkflowId.REMOVE,
    }
    for definition in definitions:
        assert definition.steps
        assert definition.description
        assert definition.workflow_id.value == definition.workflow_id.value


def test_workflow_steps_carry_labels_preflight_confirm_and_recovery() -> None:
    definition = workflow_definition(WorkflowId.ENGINE_INSTALL)
    for step in definition.steps:
        assert step.label
        assert step.preflight
        assert step.recovery
        assert step.id
    assert any(step.confirm_required for step in workflow_definition(WorkflowId.REMOVE).steps)


def test_begin_workflow_creates_pending_session_at_first_step() -> None:
    session = begin_workflow(WorkflowId.BENCHMARK, observed_at="2026-08-15T10:00:00+00:00")
    assert session.state is WorkflowState.PENDING
    assert session.progress_percent == 0
    assert session.current_step_id == session.definition.steps[0].id
    assert session.error is None
    assert session.cancel_requested is False


def test_advance_step_moves_progress_and_records_outcome() -> None:
    session = begin_workflow(WorkflowId.BENCHMARK, observed_at="2026-08-15T10:00:00+00:00")
    definition = session.definition
    step = definition.steps[0]
    advanced, outcome = advance_step(
        session,
        step_id=step.id,
        outcome=StepOutcome.SUCCEEDED,
        observed_at="2026-08-15T10:00:05+00:00",
        message="started",
    )
    assert advanced.state is WorkflowState.RUNNING
    assert advanced.current_step_id == definition.steps[1].id
    assert advanced.progress_percent == 33
    assert advanced.step_outcomes == {step.id: StepOutcome.SUCCEEDED}
    assert outcome is StepOutcome.SUCCEEDED


def test_advance_last_step_succeeds_workflow() -> None:
    session = begin_workflow(WorkflowId.ENGINE_CONFIGURE, observed_at="2026-08-15T10:00:00+00:00")
    definition = session.definition
    for index, step in enumerate(definition.steps):
        session, _ = advance_step(
            session,
            step_id=step.id,
            outcome=StepOutcome.SUCCEEDED,
            observed_at="2026-08-15T10:00:00+00:00",
        )
        if index == len(definition.steps) - 1:
            assert session.state is WorkflowState.SUCCEEDED
            assert session.progress_percent == 100
        else:
            assert session.state is WorkflowState.RUNNING
            assert session.progress_percent == round((index + 1) * 100 / len(definition.steps))


def test_failed_step_stops_workflow_with_error_and_recovery() -> None:
    session = begin_workflow(WorkflowId.MODEL_ACQUIRE, observed_at="2026-08-15T10:00:00+00:00")
    step = session.definition.steps[0]
    advanced, _ = advance_step(
        session,
        step_id=step.id,
        outcome=StepOutcome.FAILED,
        observed_at="2026-08-15T10:00:05+00:00",
        message="download failed",
    )
    assert advanced.state is WorkflowState.FAILED
    assert advanced.error == "download failed"
    assert advanced.recovery_instruction == workflow_recovery_instruction(
        WorkflowId.MODEL_ACQUIRE, step.id
    )
    assert workflow_recovery_instruction(WorkflowId.MODEL_ACQUIRE, step.id)


def test_cancellation_is_cooperative_and_honored_between_steps() -> None:
    session = begin_workflow(WorkflowId.BENCHMARK, observed_at="2026-08-15T10:00:00+00:00")
    session = request_cancellation(session, observed_at="2026-08-15T10:00:01+00:00")
    assert session.cancel_requested is True
    step = session.definition.steps[0]
    advanced, _ = advance_step(
        session,
        step_id=step.id,
        outcome=StepOutcome.SUCCEEDED,
        observed_at="2026-08-15T10:00:05+00:00",
    )
    assert advanced.state is WorkflowState.CANCELLED
    assert advanced.error == "Cancelled by operator request"


def test_advance_unknown_step_is_rejected() -> None:
    session = begin_workflow(WorkflowId.BENCHMARK, observed_at="2026-08-15T10:00:00+00:00")
    advanced, _ = advance_step(
        session,
        step_id="not-a-step",
        outcome=StepOutcome.SUCCEEDED,
        observed_at="2026-08-15T10:00:05+00:00",
    )
    assert advanced is session


def test_advance_finished_session_is_rejected() -> None:
    session = begin_workflow(WorkflowId.ENGINE_CONFIGURE, observed_at="2026-08-15T10:00:00+00:00")
    for step in session.definition.steps:
        session, _ = advance_step(
            session,
            step_id=step.id,
            outcome=StepOutcome.SUCCEEDED,
            observed_at="2026-08-15T10:00:00+00:00",
        )
    unchanged, _ = advance_step(
        session,
        step_id=session.definition.steps[0].id,
        outcome=StepOutcome.SUCCEEDED,
        observed_at="2026-08-15T10:00:06+00:00",
    )
    assert unchanged is session


def test_failed_session_records_error_and_does_not_advance() -> None:
    session = begin_workflow(WorkflowId.BENCHMARK, observed_at="2026-08-15T10:00:00+00:00")
    step = session.definition.steps[0]
    failed, _ = advance_step(
        session,
        step_id=step.id,
        outcome=StepOutcome.FAILED,
        observed_at="2026-08-15T10:00:05+00:00",
        message="boom",
    )
    after, _ = advance_step(
        failed,
        step_id=step.id,
        outcome=StepOutcome.SUCCEEDED,
        observed_at="2026-08-15T10:00:06+00:00",
    )
    assert after is failed
    assert failed.state is WorkflowState.FAILED


def test_workflow_session_payload_round_trip() -> None:
    session = begin_workflow(WorkflowId.REMOVE, observed_at="2026-08-15T10:00:00+00:00")
    payload = session.to_dict()
    assert payload["workflow_id"] == "remove"
    assert payload["state"] == "pending"
    assert payload["steps"][0]["id"] == session.definition.steps[0].id
    assert payload["steps"][0]["confirm_required"] is True
    assert payload["steps"][1]["confirm_required"] is False
