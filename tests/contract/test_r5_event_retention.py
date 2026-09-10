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


def test_OUI_003_bounded_search_matches_message_and_correlation(tmp_path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")

    async def seed() -> None:
        await store.initialize()
        await store.record_event(
            source="api",
            severity="info",
            message="owned control telemetry restart plan plan-r5-search",
            correlation_id="plan-r5-search",
            recorded_at="2026-08-01T00:00:00+00:00",
        )
        await store.record_event(
            source="api",
            severity="info",
            message="workflow benchmark started",
            correlation_id="plan-other",
            recorded_at="2026-08-01T00:01:00+00:00",
        )
        await store.record_event(
            source="api",
            severity="info",
            message="expired heartbeat",
            correlation_id="plan-r5-search",
            recorded_at="2026-07-30T12:00:00+00:00",
        )

    import asyncio

    asyncio.run(seed())
    client = _client(tmp_path)
    auth = {"Authorization": "Bearer test-api-key"}
    by_text = client.get("/api/v1/operations/events?q=telemetry&limit=10", headers=auth)
    assert by_text.status_code == 200, by_text.text
    messages = [entry["message"] for entry in by_text.json()["events"]]
    assert messages == ["owned control telemetry restart plan plan-r5-search"]
    by_correlation = client.get("/api/v1/operations/events?q=plan-r5-search&limit=10", headers=auth)
    assert by_correlation.status_code == 200
    assert [entry["correlation_id"] for entry in by_correlation.json()["events"]] == [
        "plan-r5-search"
    ]
    assert all("expired" not in entry["message"] for entry in by_correlation.json()["events"])


def test_OUI_003_search_cannot_bypass_privacy_or_query_limits(tmp_path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")

    async def seed() -> None:
        await store.initialize()
        await store.record_event(
            source="api",
            severity="info",
            message="token=super-secret-value workflow started",
            recorded_at="2026-08-01T00:00:00+00:00",
        )

    import asyncio

    asyncio.run(seed())
    client = _client(tmp_path)
    auth = {"Authorization": "Bearer test-api-key"}
    leaked = client.get("/api/v1/operations/events?q=super-secret-value", headers=auth)
    assert leaked.status_code == 200
    assert leaked.json()["count"] == 0
    redacted = client.get("/api/v1/operations/events?q=REDACTED", headers=auth)
    assert redacted.status_code == 200
    assert redacted.json()["count"] == 1
    assert "super-secret-value" not in redacted.json()["events"][0]["message"]
    too_long = client.get("/api/v1/operations/events?q=" + ("a" * 129), headers=auth)
    assert too_long.status_code == 400


def test_temperature_c_has_an_explicit_celsius_unit() -> None:
    assert unit_for_signal("temperature_c") == "celsius"
