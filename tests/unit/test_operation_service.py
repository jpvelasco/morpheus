"""Unit tests: durable managed operation service behavior."""

from __future__ import annotations

import pytest

from morpheus.adapters.persistence.operation_store import OperationStore
from morpheus.adapters.workflows.runner import PreflightResult, StepResult
from morpheus.core.operations import (
    ManagedOperation,
    ManagedOperationState,
    WorkflowId,
    derive_operation_id,
)
from morpheus.ops.operation_service import OperationService, OperationServiceError


class FakeClock:
    def __init__(self) -> None:
        self._ticks = 0

    def utc_now(self):
        from datetime import UTC, datetime, timedelta

        self._ticks += 1
        return datetime(2026, 8, 24, tzinfo=UTC) + timedelta(seconds=self._ticks)


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record_workflow_audit(self, **fields: object) -> None:
        self.events.append(dict(fields))


class StaticExecutor:
    """Executor whose preflight/execute behavior is scriptable per test."""

    def __init__(
        self,
        *,
        preflight: PreflightResult | Exception | None = None,
        execute: StepResult | Exception | None = None,
    ) -> None:
        self._preflight = preflight or PreflightResult(ok=True)
        self._execute = execute if execute is not None else StepResult(ok=True)

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        if isinstance(self._preflight, Exception):
            raise self._preflight
        return self._preflight  # type: ignore[return-value]

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        if isinstance(self._execute, Exception):
            raise self._execute
        return self._execute  # type: ignore[return-value]


def _service(tmp_path, executor, audit=None) -> OperationService:
    return OperationService(
        executor=executor,
        store=OperationStore(tmp_path / "operations"),
        clock=FakeClock(),
        audit=audit,
    )


def _saved_operation(tmp_path, **overrides: object) -> ManagedOperation:
    from morpheus.core.operations import ManagedOperation as operation_type

    values: dict[str, object] = {
        "operation_id": "operation-seeded",
        "workflow_id": WorkflowId.BENCHMARK.value,
        "requested_at": "2026-08-24T00:00:00+00:00",
        "updated_at": "2026-08-24T00:00:00+00:00",
    }
    values.update(overrides)
    operation = operation_type(**values)
    OperationStore(tmp_path / "operations").save(operation)
    return operation


async def test_start_rejects_second_active_operation_for_same_workflow(
    tmp_path, monkeypatch
) -> None:
    _saved_operation(tmp_path, state=ManagedOperationState.RUNNING.value)
    service = _service(tmp_path, StaticExecutor())
    with pytest.raises(OperationServiceError, match="already running"):
        await service.start(WorkflowId.BENCHMARK, confirmed=True)


async def test_start_is_rejected_without_confirmation_for_confirm_workflows(
    tmp_path,
) -> None:
    service = _service(tmp_path, StaticExecutor())
    with pytest.raises(OperationServiceError, match="confirmation"):
        await service.start(WorkflowId.REMOVE, confirmed=False)


async def test_existing_token_returns_recorded_operation_without_rerunning(
    tmp_path,
) -> None:
    existing = _saved_operation(
        tmp_path,
        operation_id=derive_operation_id(WorkflowId.BENCHMARK, "tok"),
        state=ManagedOperationState.SUCCEEDED.value,
    )
    service = _service(tmp_path, StaticExecutor())
    result = await service.start(WorkflowId.BENCHMARK, confirmed=True, token="tok")
    assert result["started"] is False
    assert result["operation_id"] == existing.operation_id
    assert result["session"]["state"] == "succeeded"


async def test_preflight_crash_fails_the_operation_honestly(tmp_path) -> None:
    audit = RecordingAudit()
    service = _service(tmp_path, StaticExecutor(preflight=RuntimeError("boom")), audit)
    result = await service.start(WorkflowId.BENCHMARK, confirmed=True)
    assert result["started"] is False
    session = result["session"]
    assert session["state"] == "failed"
    assert "boom" in str(session["error"])
    assert any(event["event"] == "preflight_failed" for event in audit.events)


async def test_step_crash_is_recorded_as_a_failed_step(tmp_path) -> None:
    service = _service(tmp_path, StaticExecutor(execute=RuntimeError("step blew up")))
    result = await service.start(WorkflowId.BENCHMARK, confirmed=True)
    assert result["started"] is True
    operation = await _wait_for_state(service, {"failed"})
    assert "step blew up" in str(operation.error)
    assert operation.recovery_instruction


async def _wait_for_state(service: OperationService, states: set[str]):
    for _ in range(2000):
        operation = service.latest_for_workflow(WorkflowId.BENCHMARK)
        assert operation is not None
        if operation.state in states:
            return operation
        import asyncio

        await asyncio.sleep(0.005)
    raise AssertionError(f"operation never reached {states}")


async def test_cancel_and_session_queries_report_missing_operations(tmp_path) -> None:
    service = _service(tmp_path, StaticExecutor())
    with pytest.raises(OperationServiceError, match="no running workflow session"):
        await service.cancel(WorkflowId.BENCHMARK)
    with pytest.raises(OperationServiceError, match="no workflow session exists"):
        service.require_latest(WorkflowId.BENCHMARK)
    assert service.latest_for_workflow(WorkflowId.BENCHMARK) is None


async def test_recovery_writes_audit_rows_through_sync_sink(tmp_path) -> None:
    class SyncAudit(RecordingAudit):
        def record_workflow_audit_sync(self, **fields: object) -> None:
            self.sync_events = getattr(self, "sync_events", [])
            self.sync_events.append(dict(fields))

    _saved_operation(tmp_path, state=ManagedOperationState.RUNNING.value)
    audit = SyncAudit()
    service = _service(tmp_path, StaticExecutor(), audit)
    recovered = service.recover_interrupted()
    assert recovered == 1
    assert audit.sync_events[0]["event"] == "interrupted"

    plain = _service(tmp_path / "fresh", StaticExecutor(), RecordingAudit())
    assert plain.recover_interrupted() == 0


async def test_recovery_without_sync_capable_audit_still_terminalizes(tmp_path) -> None:
    _saved_operation(tmp_path, state=ManagedOperationState.PENDING.value)
    service = _service(tmp_path, StaticExecutor(), RecordingAudit())
    assert service.recover_interrupted() == 1
    stored = OperationStore(tmp_path / "operations").get("operation-seeded")
    assert stored is not None
    assert stored.state == ManagedOperationState.FAILED.value
