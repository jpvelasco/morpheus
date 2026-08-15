from __future__ import annotations

import asyncio
import json

import pytest

from morpheus.adapters.workflows.runner import (
    JsonlAuditSink,
    PreflightResult,
    StepResult,
    WorkflowRunner,
    WorkflowRunnerError,
)
from morpheus.core.workflows import WorkflowId, WorkflowState


class FailingExecutor:
    def __init__(self, *, fail_step: str | None = None) -> None:
        self.fail_step = fail_step
        self.executed: list[str] = []

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        if workflow_id is WorkflowId.REMOVE and not self.executed:
            return PreflightResult(ok=False, reason="resource not owned")
        return PreflightResult(ok=True, reason=None)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        self.executed.append(step_id)
        if self.fail_step == step_id:
            return StepResult(ok=False, message=f"{step_id} exploded")
        return StepResult(ok=True, message=None)


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record_workflow_audit(self, **fields: object) -> None:
        self.events.append(fields)


@pytest.mark.asyncio
async def test_runner_runs_all_steps_and_audits_them(tmp_path) -> None:
    audit = RecordingAudit()
    runner = WorkflowRunner(executor=FailingExecutor(), audit=audit)
    result = await runner.start(
        WorkflowId.BENCHMARK,
        confirmed=True,
        session_id="session-1",
        observed_at="2026-08-15T10:00:00+00:00",
    )
    session = await runner.session(WorkflowId.BENCHMARK)
    assert session.state is WorkflowState.SUCCEEDED
    assert session.progress_percent == 100
    assert result["started"] is True
    assert len(audit.events) == 8
    assert audit.events[0]["event"] == "started"
    assert "step_succeeded" in {event["event"] for event in audit.events}
    assert audit.events[-1]["event"] == "succeeded"


@pytest.mark.asyncio
async def test_runner_failed_step_records_error_and_recovery(tmp_path) -> None:
    audit = RecordingAudit()
    runner = WorkflowRunner(executor=FailingExecutor(fail_step="run"), audit=audit)
    await runner.start(
        WorkflowId.BENCHMARK,
        confirmed=True,
        session_id="session-1",
        observed_at="2026-08-15T10:00:00+00:00",
    )
    session = await runner.session(WorkflowId.BENCHMARK)
    assert session.state is WorkflowState.FAILED
    assert session.error == "run exploded"
    assert session.recovery_instruction
    assert audit.events[-1]["event"] == "failed"


@pytest.mark.asyncio
async def test_runner_rejects_unconfirmed_start(tmp_path) -> None:
    runner = WorkflowRunner(executor=FailingExecutor(), audit=RecordingAudit())
    with pytest.raises(WorkflowRunnerError, match="confirmation"):
        await runner.start(
            WorkflowId.REMOVE,
            confirmed=False,
            session_id="session-1",
            observed_at="2026-08-15T10:00:00+00:00",
        )


@pytest.mark.asyncio
async def test_runner_preflight_failure_is_honest(tmp_path) -> None:
    runner = WorkflowRunner(executor=FailingExecutor(), audit=RecordingAudit())
    result = await runner.start(
        WorkflowId.REMOVE,
        confirmed=True,
        session_id="session-1",
        observed_at="2026-08-15T10:00:00+00:00",
    )
    assert result["started"] is False
    session = await runner.session(WorkflowId.REMOVE)
    assert session.state is WorkflowState.FAILED
    assert "not owned" in (session.error or "")


@pytest.mark.asyncio
async def test_runner_rejects_second_start_while_active_and_allows_restart(tmp_path) -> None:
    class SlowExecutor(FailingExecutor):
        async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
            await asyncio.sleep(0.05)
            return await super().execute(step_id, workflow_id)

    runner = WorkflowRunner(executor=SlowExecutor(), audit=RecordingAudit())
    task = asyncio.create_task(
        runner.start(
            WorkflowId.BENCHMARK,
            confirmed=True,
            session_id="session-1",
            observed_at="2026-08-15T10:00:00+00:00",
        )
    )
    await asyncio.sleep(0.02)
    with pytest.raises(WorkflowRunnerError, match="already running"):
        await runner.start(
            WorkflowId.BENCHMARK,
            confirmed=True,
            session_id="session-2",
            observed_at="2026-08-15T10:00:00+00:00",
        )
    await task
    restarted = await runner.start(
        WorkflowId.BENCHMARK,
        confirmed=True,
        session_id="session-3",
        observed_at="2026-08-15T10:00:10+00:00",
    )
    assert restarted["started"] is True
    session = await runner.session(WorkflowId.BENCHMARK)
    assert session.session_id == "session-3"


@pytest.mark.asyncio
async def test_runner_cancels_between_steps(tmp_path) -> None:
    class SlowExecutor(FailingExecutor):
        async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
            await asyncio.sleep(0.02)
            return await super().execute(step_id, workflow_id)

    runner = WorkflowRunner(executor=SlowExecutor(), audit=RecordingAudit())
    task = asyncio.create_task(
        runner.start(
            WorkflowId.BENCHMARK,
            confirmed=True,
            session_id="session-1",
            observed_at="2026-08-15T10:00:00+00:00",
        )
    )
    await asyncio.sleep(0.03)
    await runner.cancel(WorkflowId.BENCHMARK, observed_at="2026-08-15T10:00:03+00:00")
    await task
    session = await runner.session(WorkflowId.BENCHMARK)
    assert session.state is WorkflowState.CANCELLED
    assert session.cancel_requested is True


@pytest.mark.asyncio
async def test_runner_jsonl_audit_sink_writes_bounded_events(tmp_path) -> None:
    sink = JsonlAuditSink(tmp_path / "audit.jsonl")
    await sink.record_workflow_audit(
        recorded_at="2026-08-15T10:00:00+00:00",
        session_id="session-1",
        workflow_id="benchmark",
        event="started",
        step_id=None,
        message=None,
    )
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["event"] == "started"


@pytest.mark.asyncio
async def test_runner_audits_via_sqlite_store_shape(tmp_path) -> None:
    store = RecordingAudit()
    runner = WorkflowRunner(executor=FailingExecutor(), audit=store)
    await runner.start(
        WorkflowId.ENGINE_CONFIGURE,
        confirmed=True,
        session_id="session-1",
        observed_at="2026-08-15T10:00:00+00:00",
    )
    assert len(store.events) == 8
    assert store.events[0]["event"] == "started"
    assert store.events[-1]["event"] == "succeeded"
