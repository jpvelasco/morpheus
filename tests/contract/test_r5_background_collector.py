"""Isolated R5: metrics persist without a dashboard GET (issue #59)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState

pytestmark = pytest.mark.contract
NOW = datetime(2026, 8, 1, tzinfo=UTC)


class HostRuntimeAgent:
    async def inspect(self, operation):
        from morpheus.agent.protocol import AgentOperation, AgentResponse

        if operation is AgentOperation.HOST_SUMMARY:
            result = {
                "memory": {"available_bytes": 8 * 1024**3},
                "disk": {"free_bytes": 64 * 1024**3},
            }
        elif operation is AgentOperation.GPU_SUMMARY:
            result = {
                "gpus": [
                    {
                        "temperature_c": 42,
                        "utilization_percent": 10,
                        "memory_used_mib": 512,
                    }
                ]
            }
        else:
            result = {"containers": []}
        return AgentResponse(request_id="fixture", operation=operation, result=result)


def test_OUI_002_background_collector_persists_without_metrics_get(tmp_path) -> None:
    settings = MorpheusSettings(
        api_key="test-api-key",
        session_secret="session-test-secret",
        data_dir=tmp_path,
        metrics_collection_interval_seconds=5,
    )
    app = create_app(
        settings=settings,
        inference=FakeInference(
            health_result=Evidence(
                state=HealthState.READY,
                reason_code="ready",
                summary="ready",
                observed_at=NOW,
                duration=timedelta(milliseconds=1),
                source="fixture",
                expires_at=NOW + timedelta(seconds=30),
            ),
            model_results=(),
        ),
        clock=FakeClock(now=NOW),
        runtime_agent=HostRuntimeAgent(),
    )
    with TestClient(app, base_url="https://testserver"):
        collector = app.state.metrics_collector
        deadline = time.monotonic() + 10
        while collector.last_count is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert collector.last_count is not None
        assert collector.last_count >= 1
        assert collector.last_error is None
    store = SqliteStore(tmp_path / "morpheus.sqlite3", owned_root=tmp_path)

    async def read() -> int:
        await store.initialize()
        samples = await store.metric_samples(
            signal="temperature_c",
            start="2026-08-01T00:00:00+00:00",
            end="2026-08-01T23:59:59+00:00",
            limit=10,
        )
        return len(samples)

    assert __import__("asyncio").run(read()) >= 1
