from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.core.metrics_history import MetricSample
from morpheus.core.paths import OwnedPathError
from morpheus.core.telemetry import TelemetryEvent

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"REL-004"})
pytestmark = pytest.mark.integration


def _sample(
    observed_at: str, *, source: str = "vllm", signal: str = "gpu_cache_usage", value: float
) -> MetricSample:
    return MetricSample(observed_at=observed_at, source=source, signal=signal, value=value)


@pytest.mark.asyncio
async def test_TEL_002_sqlite_persists_only_bounded_metadata(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    event = TelemetryEvent.new(correlation_id="corr-1", model_requested="alias", started_at=1)
    event.complete(2)
    await store.record_telemetry(event)

    records = await store.telemetry(limit=10)
    assert len(records) == 1
    assert records[0]["correlation_id"] == "corr-1"
    assert {"prompt_body", "response_body", "content"}.isdisjoint(records[0])
    assert "private-content-canary" not in str(records)


@pytest.mark.asyncio
async def test_TEL_002_retention_prunes_old_records(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    for index in range(3):
        event = TelemetryEvent.new(
            correlation_id=f"corr-{index}", model_requested="alias", started_at=float(index)
        )
        event.complete(float(index + 1))
        await store.record_telemetry(event, recorded_at=f"2026-01-0{index + 1}T00:00:00+00:00")
    assert await store.prune_telemetry(before="2026-01-03T00:00:00+00:00") == 2
    assert len(await store.telemetry(limit=10)) == 1


@pytest.mark.asyncio
async def test_database_backup_is_logically_equivalent(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    destination = tmp_path / "backup.sqlite3"
    await store.backup(destination)
    restored = SqliteStore(destination)
    await restored.initialize()
    assert await restored.schema_version() == await store.schema_version()


def test_SEC_006_sqlite_store_rejects_a_database_outside_its_owned_root(tmp_path: Path) -> None:
    owned = tmp_path / "owned"

    with pytest.raises(OwnedPathError, match="escapes"):
        SqliteStore(tmp_path / "outside.sqlite3", owned_root=owned)


@pytest.mark.asyncio
async def test_OUI_002_metric_samples_persist_and_round_trip(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_metric_samples(
        [
            _sample("2026-08-15T12:00:00+00:00", value=10.0),
            _sample("2026-08-15T12:01:00+00:00", value=20.0),
            _sample(
                "2026-08-15T12:02:00+00:00",
                source="host",
                signal="utilization_percent",
                value=55.0,
            ),
        ]
    )
    samples = await store.metric_samples(
        signal="gpu_cache_usage",
        start="2026-08-15T12:00:00+00:00",
        end="2026-08-15T12:02:00+00:00",
        limit=10,
    )
    assert len(samples) == 2
    assert [sample.value for sample in samples] == [10.0, 20.0]


@pytest.mark.asyncio
async def test_OUI_002_metric_query_is_range_bounded(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_metric_samples(
        [
            _sample("2026-08-15T12:00:00+00:00", value=1.0),
            _sample("2026-08-15T12:01:00+00:00", value=2.0),
            _sample("2026-08-15T12:02:00+00:00", value=3.0),
        ]
    )
    samples = await store.metric_samples(
        signal="gpu_cache_usage",
        start="2026-08-15T12:01:00+00:00",
        end="2026-08-15T12:03:00+00:00",
        limit=10,
    )
    assert [sample.value for sample in samples] == [2.0, 3.0]


@pytest.mark.asyncio
async def test_OUI_002_metric_limit_is_capped(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_metric_samples(
        [_sample("2026-08-15T12:00:00+00:00", value=float(index)) for index in range(3)]
    )
    assert (
        len(
            await store.metric_samples(
                signal="gpu_cache_usage",
                start="2000-01-01T00:00:00+00:00",
                end="2100-01-01T00:00:00+00:00",
                limit=2,
            )
        )
        == 2
    )


@pytest.mark.asyncio
async def test_OUI_002_metric_retention_prunes_old_samples(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_metric_samples(
        [
            _sample("2026-01-01T00:00:00+00:00", value=1.0),
            _sample("2026-01-02T00:00:00+00:00", value=2.0),
            _sample("2026-01-03T00:00:00+00:00", value=3.0),
        ]
    )
    assert await store.prune_metrics(before="2026-01-03T00:00:00+00:00") == 2
    remaining = await store.metric_samples(
        signal="gpu_cache_usage",
        start="2000-01-01T00:00:00+00:00",
        end="2100-01-01T00:00:00+00:00",
        limit=10,
    )
    assert len(remaining) == 1
    assert remaining[0].value == 3.0


@pytest.mark.asyncio
async def test_OUI_002_latest_metric_observed_at_reports_most_recent(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    assert await store.latest_metric_observed_at(signal="gpu_cache_usage") is None
    await store.record_metric_samples(
        [
            _sample("2026-08-15T12:00:00+00:00", value=1.0),
            _sample("2026-08-15T12:03:00+00:00", value=3.0),
        ]
    )
    assert await store.latest_metric_observed_at(signal="gpu_cache_usage") == (
        "2026-08-15T12:03:00+00:00"
    )
    assert await store.latest_metric_observed_at() == "2026-08-15T12:03:00+00:00"


@pytest.mark.asyncio
async def test_OUI_003_events_persist_redacted_messages(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_event(
        source="engine",
        severity="error",
        message="upstream rejected Bearer abc123 secret=xyz789",
        correlation_id="corr-1",
    )
    events = await store.events(limit=10)
    assert len(events) == 1
    assert "abc123" not in events[0].message
    assert "xyz789" not in events[0].message
    assert events[0].correlation_id == "corr-1"


@pytest.mark.asyncio
async def test_OUI_003_events_query_filters_by_source_severity_correlation_and_since(
    tmp_path: Path,
) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_event(
        source="engine",
        severity="error",
        message="oops",
        correlation_id="corr-1",
        recorded_at="2026-08-15T21:00:00+00:00",
    )
    await store.record_event(
        source="api",
        severity="warn",
        message="slow",
        correlation_id="corr-1",
        recorded_at="2026-08-15T22:00:00+00:00",
    )
    await store.record_event(
        source="agent",
        severity="info",
        message="heartbeat",
        correlation_id="corr-2",
        recorded_at="2026-08-15T23:00:00+00:00",
    )

    only_engine = await store.events(source="engine", limit=10)
    assert [event.message for event in only_engine] == ["oops"]

    only_warn = await store.events(severity="warn", limit=10)
    assert [event.message for event in only_warn] == ["slow"]

    correlated = await store.events(correlation_id="corr-1", limit=10)
    assert {event.message for event in correlated} == {"oops", "slow"}

    since_events = await store.events(
        since=(datetime.now(UTC) + timedelta(days=1)).isoformat(), limit=10
    )
    assert since_events == []


@pytest.mark.asyncio
async def test_OUI_003_events_are_most_recent_first_and_limit_is_capped(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    for index in range(3):
        await store.record_event(
            source="api",
            severity="info",
            message=f"event-{index}",
            recorded_at=f"2026-08-15T12:00:0{index}+00:00",
        )
    events = await store.events(limit=2)
    assert [event.message for event in events] == ["event-2", "event-1"]


@pytest.mark.asyncio
async def test_OUI_003_events_retention_prunes_old_records(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    for index in range(3):
        await store.record_event(
            source="api",
            severity="info",
            message=f"event-{index}",
            recorded_at=f"2026-01-0{index + 1}T00:00:00+00:00",
        )
    assert await store.prune_events(before="2026-01-03T00:00:00+00:00") == 2
    assert len(await store.events(limit=10)) == 1


@pytest.mark.asyncio
async def test_OUI_003_store_rejects_unapproved_sources_and_severities(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    with pytest.raises(ValueError):
        await store.record_event(source="bogus", severity="info", message="x")
    with pytest.raises(ValueError):
        await store.record_event(source="api", severity="fatal", message="x")
    with pytest.raises(ValueError):
        await store.events(source="bogus", limit=10)


@pytest.mark.asyncio
async def test_OUI_006_workflow_audit_persists_and_round_trips(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    await store.record_workflow_audit(
        recorded_at="2026-08-15T10:00:00+00:00",
        session_id="session-1",
        workflow_id="benchmark",
        event="started",
    )
    await store.record_workflow_audit(
        recorded_at="2026-08-15T10:00:05+00:00",
        session_id="session-1",
        workflow_id="benchmark",
        event="step_succeeded",
        step_id="preflight",
    )
    await store.record_workflow_audit(
        recorded_at="2026-08-15T10:00:10+00:00",
        session_id="session-2",
        workflow_id="remove",
        event="failed",
        message="not owned",
    )
    events = await store.workflow_audit_events()
    assert len(events) == 3
    assert events[0]["session_id"] == "session-2"
    assert events[0]["event"] == "failed"
    assert events[1]["step_id"] == "preflight"
    assert events[2]["workflow_id"] == "benchmark"


@pytest.mark.asyncio
async def test_OUI_006_workflow_audit_bounds_the_result_size(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3")
    await store.initialize()
    for index in range(5):
        await store.record_workflow_audit(
            recorded_at=f"2026-08-15T10:00:0{index}+00:00",
            session_id=f"session-{index}",
            workflow_id="benchmark",
            event="started",
        )
    assert len(await store.workflow_audit_events(limit=2)) == 2
    assert len(await store.workflow_audit_events(limit=0)) == 1
    assert len(await store.workflow_audit_events(limit=500)) == 5


@pytest.mark.asyncio
async def test_schema_v4_migrates_an_existing_v2_database(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "morpheus.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_meta (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES (2)")
        connection.execute(
            "CREATE TABLE telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "recorded_at TEXT NOT NULL, correlation_id TEXT NOT NULL UNIQUE, "
            "model_requested TEXT NOT NULL, model_reported TEXT, started_at REAL NOT NULL, "
            "first_byte_seconds REAL, completed_seconds REAL, prompt_tokens INTEGER, "
            "completion_tokens INTEGER, finish_reason TEXT, outcome TEXT NOT NULL)"
        )
        # A v3-era audit table without the RUNM-001 identity columns.
        connection.execute(
            "CREATE TABLE workflow_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "recorded_at TEXT NOT NULL, session_id TEXT NOT NULL, workflow_id TEXT NOT NULL, "
            "event TEXT NOT NULL, step_id TEXT, message TEXT)"
        )
    store = SqliteStore(database)
    await store.initialize()
    assert await store.schema_version() == 4
    await store.record_workflow_audit(
        recorded_at="2026-08-15T10:00:00+00:00",
        session_id="session-1",
        workflow_id="plan_promote",
        event="promote",
        plan_id="plan-libri-gguf-q4-0001",
        ownership="managed",
    )
    events = await store.workflow_audit_events()
    assert len(events) == 1
    assert events[0]["plan_id"] == "plan-libri-gguf-q4-0001"
    assert events[0]["ownership"] == "managed"
