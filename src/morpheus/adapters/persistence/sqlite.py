from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from morpheus.core.events import (
    EventRecord,
    bounded_limit,
    normalize_event,
    validate_event_filter,
)
from morpheus.core.metrics_history import MetricSample
from morpheus.core.paths import OwnedPathResolver
from morpheus.core.telemetry import TelemetryEvent

T = TypeVar("T")
SCHEMA_VERSION = 4
MAX_METRIC_SAMPLES = 10_000


class SqliteStore:
    def __init__(self, path: Path, *, owned_root: Path | None = None) -> None:
        self._paths = OwnedPathResolver(owned_root or path.parent)
        self._path = self._paths.resolve(path)

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
        await self._run(self._migrate)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        row = connection.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
        elif int(row[0]) != SCHEMA_VERSION:
            connection.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                source TEXT NOT NULL,
                signal TEXT NOT NULL,
                value REAL NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_metric_samples_signal_recorded "
            "ON metric_samples(signal, recorded_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                source TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                correlation_id TEXT,
                deployment_id TEXT,
                campaign_id TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_recorded_at ON events(recorded_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                session_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                event TEXT NOT NULL,
                step_id TEXT,
                message TEXT,
                plan_id TEXT,
                ownership TEXT
            )
            """
        )
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(workflow_audit)").fetchall()
        }
        if "plan_id" not in existing_columns:
            connection.execute("ALTER TABLE workflow_audit ADD COLUMN plan_id TEXT")
        if "ownership" not in existing_columns:
            connection.execute("ALTER TABLE workflow_audit ADD COLUMN ownership TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_audit_recorded ON workflow_audit(recorded_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_audit_session ON workflow_audit(session_id)"
        )

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

    async def record_metric_samples(self, samples: Sequence[MetricSample]) -> None:
        values = [
            (sample.observed_at, sample.source, sample.signal, float(sample.value))
            for sample in samples
        ]

        def insert(connection: sqlite3.Connection) -> None:
            connection.executemany(
                """
                INSERT INTO metric_samples (recorded_at, source, signal, value)
                VALUES (?, ?, ?, ?)
                """,
                values,
            )

        await self._run(insert)

    async def metric_samples(
        self,
        *,
        signal: str,
        start: str,
        end: str,
        limit: int,
    ) -> list[MetricSample]:
        bounded_limit = min(max(limit, 1), MAX_METRIC_SAMPLES)

        def select(connection: sqlite3.Connection) -> list[MetricSample]:
            rows = connection.execute(
                """
                SELECT recorded_at, source, signal, value
                FROM metric_samples
                WHERE signal = ? AND recorded_at >= ? AND recorded_at < ?
                ORDER BY recorded_at ASC
                LIMIT ?
                """,
                (signal, start, end, bounded_limit),
            ).fetchall()
            return [
                MetricSample(
                    observed_at=row["recorded_at"],
                    source=row["source"],
                    signal=row["signal"],
                    value=row["value"],
                )
                for row in rows
            ]

        return await self._run(select)

    async def prune_metrics(self, *, before: str) -> int:
        def prune(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                "DELETE FROM metric_samples WHERE recorded_at < ?", (before,)
            )
            return cursor.rowcount

        return await self._run(prune)

    async def record_event(
        self,
        *,
        source: str,
        severity: str,
        message: str,
        correlation_id: str | None = None,
        deployment_id: str | None = None,
        campaign_id: str | None = None,
        recorded_at: str | None = None,
    ) -> None:
        event = normalize_event(
            source=source,
            severity=severity,
            message=message,
            correlation_id=correlation_id,
            deployment_id=deployment_id,
            campaign_id=campaign_id,
            recorded_at=recorded_at,
        )
        values = (
            event.recorded_at,
            event.source,
            event.severity,
            event.message,
            event.correlation_id,
            event.deployment_id,
            event.campaign_id,
        )

        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO events (
                    recorded_at, source, severity, message,
                    correlation_id, deployment_id, campaign_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

        await self._run(insert)

    async def events(
        self,
        *,
        source: str | None = None,
        severity: str | None = None,
        correlation_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[EventRecord]:
        validate_event_filter(
            source=source, severity=severity, correlation_id=correlation_id, since=since
        )
        bounded = bounded_limit(limit)

        def select(connection: sqlite3.Connection) -> list[EventRecord]:
            rows = connection.execute(
                """
                SELECT recorded_at, source, severity, message,
                       correlation_id, deployment_id, campaign_id
                FROM events
                WHERE (? IS NULL OR source = ?)
                  AND (? IS NULL OR severity = ?)
                  AND (? IS NULL OR correlation_id = ?)
                  AND (? IS NULL OR recorded_at >= ?)
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (
                    source,
                    source,
                    severity,
                    severity,
                    correlation_id,
                    correlation_id,
                    since,
                    since,
                    bounded,
                ),
            ).fetchall()
            return [
                EventRecord(
                    recorded_at=row["recorded_at"],
                    source=row["source"],
                    severity=row["severity"],
                    message=row["message"],
                    correlation_id=row["correlation_id"],
                    deployment_id=row["deployment_id"],
                    campaign_id=row["campaign_id"],
                )
                for row in rows
            ]

        return await self._run(select)

    async def prune_events(self, *, before: str) -> int:
        def prune(connection: sqlite3.Connection) -> int:
            cursor = connection.execute("DELETE FROM events WHERE recorded_at < ?", (before,))
            return cursor.rowcount

        return await self._run(prune)

    async def latest_metric_observed_at(self, *, signal: str | None = None) -> str | None:
        def select(connection: sqlite3.Connection) -> str | None:
            if signal is None:
                row = connection.execute(
                    "SELECT recorded_at FROM metric_samples ORDER BY recorded_at DESC LIMIT 1"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT recorded_at FROM metric_samples WHERE signal = ? "
                    "ORDER BY recorded_at DESC LIMIT 1",
                    (signal,),
                ).fetchone()
            return row["recorded_at"] if row else None

        return await self._run(select)

    async def record_workflow_audit(
        self,
        *,
        recorded_at: str,
        session_id: str,
        workflow_id: str,
        event: str,
        step_id: str | None = None,
        message: str | None = None,
        plan_id: str | None = None,
        ownership: str | None = None,
    ) -> None:
        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO workflow_audit (
                    recorded_at, session_id, workflow_id, event, step_id, message,
                    plan_id, ownership
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (recorded_at, session_id, workflow_id, event, step_id, message, plan_id, ownership),
            )

        await self._run(insert)

    async def workflow_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = min(max(limit, 1), 200)

        def select(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                """
                SELECT recorded_at, session_id, workflow_id, event, step_id, message,
                       plan_id, ownership
                FROM workflow_audit
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            return [
                {
                    "recorded_at": row["recorded_at"],
                    "session_id": row["session_id"],
                    "workflow_id": row["workflow_id"],
                    "event": row["event"],
                    "step_id": row["step_id"],
                    "message": row["message"],
                    "plan_id": row["plan_id"],
                    "ownership": row["ownership"],
                }
                for row in rows
            ]

        return await self._run(select)

    def record_workflow_audit_sync(
        self,
        *,
        recorded_at: str,
        session_id: str,
        workflow_id: str,
        event: str,
        step_id: str | None = None,
        message: str | None = None,
        plan_id: str | None = None,
        ownership: str | None = None,
    ) -> None:
        """Composition-time audit write; only restart recovery may use this.

        Recovery runs synchronously while the application is being built,
        before any request task or lazy async initialization exists.
        """

        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO workflow_audit (
                    recorded_at, session_id, workflow_id, event, step_id, message,
                    plan_id, ownership
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (recorded_at, session_id, workflow_id, event, step_id, message, plan_id, ownership),
            )

        def migrate_and_insert(connection: sqlite3.Connection) -> None:
            self._migrate(connection)
            insert(connection)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            migrate_and_insert(connection)

    async def backup(self, destination: Path) -> Path:
        destination = self._paths.resolve(destination)

        def create_backup(connection: sqlite3.Connection) -> Path:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(destination) as target:
                connection.backup(target)
            return destination

        return await self._run(create_backup)
