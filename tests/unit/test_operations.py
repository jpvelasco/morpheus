"""Unit tests: durable managed operation documents and their store."""

from __future__ import annotations

import pytest

from morpheus.adapters.persistence.operation_store import (
    OperationStore,
    OperationStoreError,
)
from morpheus.core.operations import (
    SCHEMA_VERSION,
    ManagedOperation,
    ManagedOperationState,
    StepOutcome,
    WorkflowId,
    decode_operation,
    derive_operation_id,
    encode_operation,
    fresh_operation_id,
)
from morpheus.core.workflows import workflow_definition


def _operation(**overrides: object) -> ManagedOperation:
    values: dict[str, object] = {
        "operation_id": "operation-abc123",
        "workflow_id": WorkflowId.BENCHMARK.value,
        "requested_at": "2026-08-24T00:00:00+00:00",
        "updated_at": "2026-08-24T00:00:00+00:00",
    }
    values.update(overrides)
    return ManagedOperation(**values)


def test_operation_id_is_timestamp_free_and_deterministic() -> None:
    first = derive_operation_id(WorkflowId.BENCHMARK, "tok-1")
    second = derive_operation_id(WorkflowId.BENCHMARK, "tok-1")
    other = derive_operation_id(WorkflowId.PROMOTE, "tok-1")
    assert first == second
    assert first != other
    assert first.startswith("operation-")
    assert fresh_operation_id() != fresh_operation_id()


def test_operation_rejects_unknown_workflow_state_and_bad_index() -> None:
    with pytest.raises(ValueError, match="unknown workflow id"):
        _operation(workflow_id="not-a-workflow")
    with pytest.raises(ValueError, match="unknown managed operation state"):
        _operation(state="teleporting")
    with pytest.raises(ValueError, match="step index"):
        _operation(step_index=99)
    with pytest.raises(ValueError, match="schema version"):
        _operation(schema_version=SCHEMA_VERSION + 1)
    with pytest.raises(ValueError, match="requested_at"):
        _operation(requested_at="")


def test_step_outcomes_advance_to_terminal_states() -> None:
    steps = workflow_definition(WorkflowId.BENCHMARK).steps
    running = _operation().begin(observed_at="t1")
    assert running.state == ManagedOperationState.RUNNING.value
    assert running.current_step_id == steps[0].id

    mid = running.record_outcome(outcome=StepOutcome.SUCCEEDED, observed_at="t2")
    assert mid.step_index == 1
    assert mid.progress_percent == round(100 / len(steps))
    assert mid.step_outcomes[steps[0].id] == "succeeded"

    done = mid.record_outcome(outcome=StepOutcome.SUCCEEDED, observed_at="t3")
    done = done.record_outcome(outcome=StepOutcome.SUCCEEDED, observed_at="t4")
    assert done.state == ManagedOperationState.SUCCEEDED.value
    assert done.progress_percent == 100
    # Terminal documents ignore further mutations.
    assert done.begin(observed_at="t5") is done


def test_failure_and_cancel_paths_carry_recovery_instructions() -> None:
    failed = (
        _operation()
        .begin(observed_at="t1")
        .record_outcome(outcome=StepOutcome.FAILED, message="engine exploded", observed_at="t2")
    )
    assert failed.state == ManagedOperationState.FAILED.value
    assert failed.error == "engine exploded"
    assert failed.recovery_instruction

    cancelled = (
        _operation()
        .begin(observed_at="t1")
        .request_cancel(observed_at="t2")
        .record_outcome(outcome=StepOutcome.SUCCEEDED, observed_at="t3")
    )
    assert cancelled.state == ManagedOperationState.CANCELLED.value
    assert cancelled.cancel_requested is True
    assert cancelled.recovery_instruction


def test_fail_records_explicit_out_of_band_failure_once() -> None:
    operation = _operation().fail(reason="preflight failed", recovery="fix it", observed_at="t1")
    assert operation.state == ManagedOperationState.FAILED.value
    again = operation.fail(reason="again", recovery="nope", observed_at="t2")
    assert again is operation


def test_interrupted_terminalization_only_touches_active_documents() -> None:
    interrupted = _operation().begin(observed_at="t1").terminalize_interrupted(observed_at="t2")
    assert interrupted.state == ManagedOperationState.FAILED.value
    assert "interrupted" in str(interrupted.error).lower()
    assert interrupted.current_step_id
    succeeded = _operation(state=ManagedOperationState.SUCCEEDED.value)
    assert succeeded.terminalize_interrupted(observed_at="t2") is succeeded


def test_envelope_round_trip_is_exact() -> None:
    operation = (
        _operation(plan_id="plan-1")
        .begin(observed_at="t1")
        .record_outcome(outcome=StepOutcome.SUCCEEDED, observed_at="t2")
    )
    decoded = decode_operation(encode_operation(operation))
    assert decoded == operation
    assert decoded.public_dict()["plan_id"] == "plan-1"


def test_decode_rejects_foreign_or_tampered_envelopes() -> None:
    import json

    document = json.loads(decode_operation.__module__ and "{}")  # guard import style
    assert isinstance(document, dict)

    payload = json.loads(encode_operation(_operation()).decode())
    foreign = dict(payload, record_type="something_else")
    with pytest.raises(ValueError, match="not a managed operation"):
        decode_operation(json.dumps(foreign).encode())

    missing_field = dict(payload)
    missing_field["payload"] = {
        key: value for key, value in payload["payload"].items() if key != "confirmed"
    }
    with pytest.raises(ValueError, match="exactly its declared fields"):
        decode_operation(json.dumps(missing_field).encode())

    identity_swap = dict(payload, record_id="operation-other")
    with pytest.raises(ValueError, match="identity mismatch"):
        decode_operation(json.dumps(identity_swap).encode())


def test_store_save_get_list_round_trip(tmp_path) -> None:
    store = OperationStore(tmp_path / "operations")
    first = _operation(operation_id="operation-one")
    second = _operation(operation_id="operation-two", updated_at="later")
    store.save(first)
    store.save(second)

    assert store.get("operation-one") == first
    assert store.get("missing") is None
    listed = store.list_all()
    assert [operation.operation_id for operation in listed] == [
        "operation-two",
        "operation-one",
    ]


def test_store_overwrites_are_atomic_replaces_not_duplicates(tmp_path) -> None:
    store = OperationStore(tmp_path / "operations")
    operation = _operation()
    store.save(operation)
    advanced = operation.begin(observed_at="t1")
    store.save(advanced)
    assert store.get(operation.operation_id) == advanced


def test_store_rejects_unreadable_documents_and_bad_ids(tmp_path) -> None:
    store = OperationStore(tmp_path / "operations")
    store.root.mkdir(parents=True)
    (store.root / "operation-broken.json").write_bytes(b"{ not json")

    with pytest.raises(OperationStoreError, match="unreadable"):
        store.list_all()
    with pytest.raises(OperationStoreError, match="storable document name"):
        store.get("../escape")


def test_public_dict_matches_legacy_session_shape() -> None:
    payload = _operation().public_dict()
    assert payload["session_id"] == payload["operation_id"]
    assert payload["started_at"] == payload["requested_at"]
    assert payload["current_step_label"]
    assert all(step["outcome"] is None for step in payload["steps"])
