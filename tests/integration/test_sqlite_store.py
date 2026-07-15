from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.core.telemetry import TelemetryEvent

pytestmark = pytest.mark.integration


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
