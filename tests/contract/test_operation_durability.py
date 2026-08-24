"""Contract tests: durable managed operations (R3, OUI-006).

The operation service owns workflow execution outside the request task,
persists every durable edge, starts idempotently by operation token, and
recovers interrupted operations after an API restart. These tests compose
the real public boundary (``create_app`` + ``TestClient``) with explicitly
injected step executors, mirroring how production wires lifecycle-backed
executors instead of the retired in-request DEV runner.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.workflows.runner import PreflightResult, StepResult
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.workflows import WorkflowId

pytestmark = pytest.mark.contract

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
API_KEY = "test-api-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


def _ready_evidence() -> Evidence:
    return Evidence(
        state=HealthState.READY,
        reason_code="ready",
        summary="ready",
        observed_at=NOW,
        duration=timedelta(milliseconds=1),
        source="fixture",
        expires_at=NOW + timedelta(seconds=30),
    )


class ScriptedExecutor:
    """Step executor with per-step release gates for interruption scenarios."""

    def __init__(self, *, gates: dict[str, threading.Event] | None = None) -> None:
        self.executed: list[tuple[str, str]] = []
        self._gates = gates or {}
        self._lock = threading.Lock()

    async def preflight(self, workflow_id: WorkflowId) -> PreflightResult:
        return PreflightResult(ok=True)

    async def execute(self, step_id: str, workflow_id: WorkflowId) -> StepResult:
        gate = self._gates.get(step_id)
        if gate is not None:
            await _await_gate(gate)
        with self._lock:
            self.executed.append((workflow_id.value, step_id))
        return StepResult(ok=True)


async def _await_gate(gate: threading.Event) -> None:
    await __import__("asyncio").to_thread(gate.wait, 30)


def _client(tmp_path, executor: ScriptedExecutor | None = None):
    settings = MorpheusSettings(
        api_key=API_KEY, session_secret="session-test-secret", data_dir=tmp_path
    )
    app = create_app(
        settings=settings,
        inference=FakeInference(health_result=_ready_evidence(), model_results=()),
        clock=FakeClock(now=NOW),
        workflow_executor=executor,
    )
    return app


def _signed_in(test_client: TestClient) -> dict[str, str]:
    response = test_client.post("/api/v1/session", json={"api_key": API_KEY})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": test_client.cookies.get("morpheus_csrf", "")}


def _start(test_client: TestClient, csrf: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    response = test_client.post(
        "/api/v1/operations/workflows/benchmark/start", json=body, headers=csrf
    )
    assert response.status_code == 200, response.text
    return response.json()


def _session(test_client: TestClient) -> dict[str, Any] | None:
    response = test_client.get("/api/v1/operations/workflows/benchmark/session", headers=AUTH)
    if response.status_code != 200:
        return None
    return response.json()["session"]


def _wait_for_state(
    test_client: TestClient, states: set[str], *, attempts: int = 400
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(attempts):
        found = _session(test_client)
        if found is not None:
            last = found
            if found["state"] in states:
                return found
        time.sleep(0.01)
    raise AssertionError(f"operation never reached {states}; last={last}")


def test_start_returns_before_completion_and_tracks_progress(tmp_path) -> None:
    gate = threading.Event()
    executor = ScriptedExecutor(gates={"preflight": gate})
    with TestClient(_client(tmp_path, executor), base_url="https://testserver") as test_client:
        csrf = _signed_in(test_client)

        result = _start(test_client, csrf, {"confirmed": True})
        session = result["session"]
        assert result["started"] is True
        assert result["operation_id"]
        assert session["state"] == "running"
        assert executor.executed == []

        gate.set()
        final = _wait_for_state(test_client, {"succeeded"})
        assert final["progress_percent"] == 100


def test_same_operation_token_is_idempotent(tmp_path) -> None:
    release = threading.Event()
    executor = ScriptedExecutor(gates={"run": release})
    with TestClient(_client(tmp_path, executor), base_url="https://testserver") as test_client:
        csrf = _signed_in(test_client)

        first = _start(test_client, csrf, {"confirmed": True, "operation_token": "tok-1"})
        deadline = time.monotonic() + 10
        while not executor.executed:
            if time.monotonic() > deadline:
                raise AssertionError("driver never started executing")
            time.sleep(0.01)
        after_first = list(executor.executed)
        second = _start(test_client, csrf, {"confirmed": True, "operation_token": "tok-1"})

        assert second["operation_id"] == first["operation_id"]
        assert second["session"]["session_id"] == first["session"]["session_id"]
        assert executor.executed == after_first

        release.set()
        final = _wait_for_state(test_client, {"succeeded"})
        assert final["session_id"] == first["session"]["session_id"]

        listed = test_client.get("/api/v1/operations/workflows", headers=AUTH).json()
        sessions_for_operation = [
            item
            for item in listed["sessions"]
            if item["session_id"] == first["session"]["session_id"]
        ]
        assert len(sessions_for_operation) == 1
        started_rows = [
            event
            for event in listed["audit_events"]
            if event["event"] == "started" and event["session_id"] == first["session"]["session_id"]
        ]
        assert len(started_rows) == 1


def test_completed_operation_survives_api_restart(tmp_path) -> None:
    with TestClient(_client(tmp_path, ScriptedExecutor()), base_url="https://testserver") as tc:
        csrf = _signed_in(tc)
        result = _start(tc, csrf, {"confirmed": True})
        session_id = result["session"]["session_id"]
        _wait_for_state(tc, {"succeeded"})

    with TestClient(_client(tmp_path, ScriptedExecutor()), base_url="https://testserver") as tc2:
        response = tc2.get("/api/v1/operations/workflows/benchmark/session", headers=AUTH)
        assert response.status_code == 200
        recovered = response.json()["session"]
        assert recovered["session_id"] == session_id
        assert recovered["state"] == "succeeded"


def test_interrupted_operation_is_terminalized_after_restart(tmp_path) -> None:
    gate = threading.Event()
    executor = ScriptedExecutor(gates={"preflight": gate})
    try:
        with TestClient(_client(tmp_path, executor), base_url="https://testserver") as tc:
            csrf = _signed_in(tc)
            result = _start(tc, csrf, {"confirmed": True})
            session_id = result["session"]["session_id"]
    finally:
        gate.set()

    with TestClient(_client(tmp_path, ScriptedExecutor()), base_url="https://testserver") as tc2:
        response = tc2.get("/api/v1/operations/workflows/benchmark/session", headers=AUTH)
        assert response.status_code == 200
        recovered = response.json()["session"]
        assert recovered["session_id"] == session_id
        assert recovered["state"] == "failed"
        assert "interrupted" in recovered["error"].lower()
        assert recovered["recovery_instruction"]

        listed = tc2.get("/api/v1/operations/workflows", headers=AUTH).json()
        assert any(event["event"] == "interrupted" for event in listed["audit_events"])


def test_cancellation_is_cooperative_between_steps(tmp_path) -> None:
    release = threading.Event()
    executor = ScriptedExecutor(gates={"run": release})
    with TestClient(_client(tmp_path, executor), base_url="https://testserver") as test_client:
        csrf = _signed_in(test_client)

        started = _start(test_client, csrf, {"confirmed": True})
        deadline = time.monotonic() + 10
        while "preflight" not in [step for _, step in executor.executed]:
            if time.monotonic() > deadline:
                raise AssertionError("preflight never executed")
            time.sleep(0.01)

        cancelled = test_client.post("/api/v1/operations/workflows/benchmark/cancel", headers=csrf)
        assert cancelled.status_code == 200

        release.set()
        final = _wait_for_state(test_client, {"cancelled"}, attempts=600)
        assert final["cancel_requested"] is True
        assert final["session_id"] == started["session"]["session_id"]
