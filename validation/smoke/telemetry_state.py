from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.config import load_settings
from morpheus.core.telemetry import TelemetryEvent

BACKUP_NAME = "telemetry-validation-backup.sqlite3"
CONTENT_CANARY = b"morpheus-private-prompt-canary-opt-tel-001"
EXPIRED_CORRELATION = "morpheus-retention-expired-canary"
REQUIRED_OUTCOMES = {
    "success",
    "upstream_http_error",
    "upstream_protocol_error",
    "upstream_timeout",
    "canceled",
}
ALLOWED_FIELDS = {
    "id",
    "recorded_at",
    "correlation_id",
    "model_requested",
    "model_reported",
    "started_at",
    "first_byte_seconds",
    "completed_seconds",
    "prompt_tokens",
    "completion_tokens",
    "finish_reason",
    "outcome",
}


def _store(data_dir: Path, name: str = "morpheus.sqlite3") -> SqliteStore:
    return SqliteStore(data_dir / name, owned_root=data_dir)


async def _records(store: SqliteStore) -> list[dict[str, Any]]:
    return sorted(await store.telemetry(limit=1_000), key=lambda record: record["correlation_id"])


def _validate_metadata(records: list[dict[str, Any]]) -> set[str]:
    if not records:
        raise AssertionError("telemetry database must contain validation records")
    if any(set(record) != ALLOWED_FIELDS for record in records):
        raise AssertionError("telemetry database contains an unexpected field")
    outcomes = {str(record["outcome"]) for record in records}
    missing = REQUIRED_OUTCOMES - outcomes
    if missing:
        raise AssertionError(f"telemetry outcomes are incomplete: {sorted(missing)}")
    return outcomes


def _verify_privacy(paths: list[Path]) -> None:
    for path in paths:
        if path.exists() and CONTENT_CANARY in path.read_bytes():
            raise AssertionError(f"content canary persisted in {path.name}")


def _database_paths(data_dir: Path, *, include_backup: bool) -> list[Path]:
    database = data_dir / "morpheus.sqlite3"
    paths = [database, Path(f"{database}-wal"), Path(f"{database}-shm")]
    if include_backup:
        paths.append(data_dir / BACKUP_NAME)
    return paths


async def _inspect_and_backup(data_dir: Path) -> dict[str, object]:
    store = _store(data_dir)
    await store.initialize()
    records = await _records(store)
    outcomes = _validate_metadata(records)

    backup_path = data_dir / BACKUP_NAME
    await store.backup(backup_path)
    backup = _store(data_dir, BACKUP_NAME)
    await backup.initialize()
    backup_records = await _records(backup)
    if backup_records != records:
        raise AssertionError("telemetry backup is not logically equivalent")
    _verify_privacy(_database_paths(data_dir, include_backup=True))
    return {
        "action": "inspect-backup",
        "backup_records": len(backup_records),
        "live_records": len(records),
        "outcomes": sorted(outcomes),
        "privacy": "passed",
        "schema_version": await backup.schema_version(),
    }


async def _seed_expired(data_dir: Path) -> dict[str, object]:
    store = _store(data_dir)
    await store.initialize()
    records = await _records(store)
    if not any(record["correlation_id"] == EXPIRED_CORRELATION for record in records):
        event = TelemetryEvent.new(
            correlation_id=EXPIRED_CORRELATION,
            model_requested="morpheus-fixture-model",
            started_at=0,
        )
        event.complete(1)
        await store.record_telemetry(event, recorded_at="2000-01-01T00:00:00+00:00")
    records = await _records(store)
    if not any(record["correlation_id"] == EXPIRED_CORRELATION for record in records):
        raise AssertionError("expired retention fixture was not seeded")
    return {"action": "seed-expired", "seeded": True}


async def _verify_restart(data_dir: Path) -> dict[str, object]:
    store = _store(data_dir)
    await store.initialize()
    records = await _records(store)
    if any(record["correlation_id"] == EXPIRED_CORRELATION for record in records):
        raise AssertionError("telemetry restart did not enforce retention")
    outcomes = _validate_metadata(records)

    backup = _store(data_dir, BACKUP_NAME)
    await backup.initialize()
    backup_records = await _records(backup)
    if backup_records != records:
        raise AssertionError("restart did not retain the backed-up recent telemetry state")
    _verify_privacy(_database_paths(data_dir, include_backup=True))
    return {
        "action": "verify-restart",
        "backup_records": len(backup_records),
        "live_records": len(records),
        "outcomes": sorted(outcomes),
        "privacy": "passed",
        "retention": "passed",
        "restart": "passed",
    }


async def _run(action: str) -> dict[str, object]:
    data_dir = load_settings().data_dir
    if action == "inspect-backup":
        return await _inspect_and_backup(data_dir)
    if action == "seed-expired":
        return await _seed_expired(data_dir)
    if action == "verify-restart":
        return await _verify_restart(data_dir)
    raise AssertionError("unsupported telemetry state action")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate disposable telemetry state")
    parser.add_argument(
        "action", choices=("inspect-backup", "seed-expired", "verify-restart")
    )
    args = parser.parse_args()
    result = asyncio.run(_run(args.action))
    sys.stdout.write(f"telemetry_state={json.dumps(result, sort_keys=True)}\n")


if __name__ == "__main__":
    main()
