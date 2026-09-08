"""Isolated R5: retention is enforced before event queries (issue #59).

Does not complete OUI-002/OUI-003. Expired rows must never appear on the
public events list even when they still exist on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.metrics_history import unit_for_signal

pytestmark = pytest.mark.contract
NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _client(tmp_path) -> TestClient:
    settings = MorpheusSettings(
        api_key="test-api-key",
        session_secret="session-test-secret",
        data_dir=tmp_path,
        events_retention_days=1,
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
    )
    return TestClient(app, base_url="https://testserver")


def test_OUI_003_expired_events_are_never_returned(tmp_path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")

    async def seed() -> None:
        await store.initialize()
        await store.record_event(
            source="api",
            severity="info",
            message="expired heartbeat",
            recorded_at="2026-07-30T12:00:00+00:00",
        )
        await store.record_event(
            source="api",
            severity="info",
            message="fresh heartbeat",
            recorded_at="2026-08-01T00:00:00+00:00",
        )

    import asyncio

    asyncio.run(seed())
    response = _client(tmp_path).get(
        "/api/v1/operations/events?limit=10",
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["events"][0]["message"] == "fresh heartbeat"
    assert all("expired" not in event["message"] for event in payload["events"])


def test_temperature_c_has_an_explicit_celsius_unit() -> None:
    assert unit_for_signal("temperature_c") == "celsius"
