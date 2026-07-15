from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from morpheus.core.telemetry import TelemetryEvent

T = TypeVar("T")
SCHEMA_VERSION = 1


class SqliteStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    async def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        def execute() -> T:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                return operation(connection)

        return await asyncio.to_thread(execute)

    async def initialize(self) -> None:
        def migrate(connection: sqlite3.Connection) -> None:
            connection.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
            if connection.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0] == 0:
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    correlation_id TEXT NOT NULL UNIQUE,
                    model_requested TEXT NOT NULL,
                    model_reported TEXT,
                    started_at REAL NOT NULL,
                    first_byte_seconds REAL,
                    completed_seconds REAL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    finish_reason TEXT,
                    outcome TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_telemetry_recorded_at ON telemetry(recorded_at)"
            )

        await self._run(migrate)

    async def schema_version(self) -> int:
        return await self._run(
            lambda connection: int(
                connection.execute("SELECT version FROM schema_meta").fetchone()[0]
            )
        )

    async def record_telemetry(
        self, event: TelemetryEvent, *, recorded_at: str | None = None
    ) -> None:
        timestamp = recorded_at or datetime.now(UTC).isoformat()
        record = event.as_record()
        values = tuple(record.values())

        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO telemetry (
                    recorded_at,
                    correlation_id,
                    model_requested,
                    model_reported,
                    started_at,
                    first_byte_seconds,
                    completed_seconds,
                    prompt_tokens,
                    completion_tokens,
                    finish_reason,
                    outcome
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, *values),
            )

        await self._run(insert)

    async def telemetry(self, *, limit: int) -> list[dict[str, Any]]:
        bounded_limit = min(max(limit, 1), 1_000)

        def select(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                "SELECT * FROM telemetry ORDER BY recorded_at DESC LIMIT ?", (bounded_limit,)
            ).fetchall()
            return [dict(row) for row in rows]

        return await self._run(select)

    async def prune_telemetry(self, *, before: str) -> int:
        def prune(connection: sqlite3.Connection) -> int:
            cursor = connection.execute("DELETE FROM telemetry WHERE recorded_at < ?", (before,))
            return cursor.rowcount

        return await self._run(prune)

    async def backup(self, destination: Path) -> Path:
        def create_backup(connection: sqlite3.Connection) -> Path:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(destination) as target:
                connection.backup(target)
            return destination

        return await self._run(create_backup)
