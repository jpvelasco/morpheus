"""Durable versioned benchmark store with content-addressed raw data (BENCH-003)."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from morpheus.core.benchmark import (
    BenchmarkError,
    BenchmarkSample,
    BenchmarkSummary,
    CampaignDeclaration,
    RunIdentity,
    bounded_identifier,
)
from morpheus.core.paths import OwnedPathError, OwnedPathResolver

SCHEMA_VERSION = 1
_HEX = frozenset("0123456789abcdef")
Migration = Callable[[dict[str, Any]], dict[str, Any]]
_MIGRATIONS: dict[int, Migration] = {}


@dataclass(frozen=True, slots=True)
class StoreManifest:
    schema_version: int
    created_at: datetime
    store_digest: str
    entries: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "store_digest": self.store_digest,
            "entries": list(self.entries),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StoreManifest:
        created = datetime.fromisoformat(payload["created_at"])
        if created.tzinfo is None:
            raise BenchmarkError("manifest timestamp must be timezone-aware")
        return cls(
            schema_version=payload["schema_version"],
            created_at=created.astimezone(UTC),
            store_digest=payload["store_digest"],
            entries=tuple(payload.get("entries", [])),
        )


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def register_migration(from_version: int) -> Callable[[Migration], Migration]:
    """Register a payload migration for a future schema version (test hook)."""

    def decorator(function: Migration) -> Migration:
        _MIGRATIONS[from_version] = function
        return function

    return decorator


def migrate(payload: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate a stored payload from one schema version to the next."""
    current = from_version
    while current < SCHEMA_VERSION:
        if current not in _MIGRATIONS:
            raise BenchmarkError(f"no migration registered from schema version {current}")
        payload = _MIGRATIONS[current](payload)
        current += 1
    return payload


@dataclass(frozen=True, slots=True)
class CampaignRun:
    run_id: str
    declaration: CampaignDeclaration
    identity: RunIdentity
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "started"
    errors: tuple[str, ...] = ()
    checkpoint: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        bounded_identifier(self.run_id, "run id")
        if self.status not in ("started", "completed", "cancelled", "failed"):
            raise BenchmarkError(f"unknown run status: {self.status}")
        if self.started_at.tzinfo is None:
            raise BenchmarkError("run timestamp must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "declaration": self.declaration.to_dict(),
            "identity": self.identity.to_dict(),
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "ended_at": self.ended_at.astimezone(UTC).isoformat() if self.ended_at else None,
            "status": self.status,
            "errors": list(self.errors),
            "checkpoint": [list(pair) for pair in self.checkpoint],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CampaignRun:
        started = datetime.fromisoformat(payload["started_at"])
        ended = datetime.fromisoformat(payload["ended_at"]) if payload.get("ended_at") else None
        if started.tzinfo is None or (ended is not None and ended.tzinfo is None):
            raise BenchmarkError("run timestamps must be timezone-aware")
        return cls(
            run_id=payload["run_id"],
            declaration=CampaignDeclaration.from_dict(payload["declaration"]),
            identity=RunIdentity.from_dict(payload["identity"]),
            started_at=started.astimezone(UTC),
            ended_at=ended.astimezone(UTC) if ended else None,
            status=payload["status"],
            errors=tuple(payload.get("errors", [])),
            checkpoint=tuple((k, int(v)) for k, v in payload.get("checkpoint", [])),
        )


@dataclass(slots=True)
class BenchmarkStore:
    """Versioned, content-addressed benchmark result store."""

    root: Path
    resolver: OwnedPathResolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = OwnedPathResolver(self.root)

    def _path(self, relative: str) -> Path:
        return self.resolver.resolve_relative(relative)

    def initialize(self) -> None:
        self._path("raw").mkdir(parents=True, exist_ok=True)
        self._path("samples").mkdir(parents=True, exist_ok=True)
        self._path("summaries").mkdir(parents=True, exist_ok=True)
        self._path("runs").mkdir(parents=True, exist_ok=True)
        manifest_path = self._path("manifest.json")
        if not manifest_path.exists():
            manifest = StoreManifest(
                schema_version=SCHEMA_VERSION,
                created_at=datetime.now(UTC),
                store_digest=sha256_hex(b""),
            )
            self._write_json(manifest_path, manifest.to_dict())

    def store_raw_lines(self, lines: tuple[str, ...]) -> tuple[str, ...]:
        """Store raw observation lines content-addressed; existing digests are
        verified, never rewritten."""
        raw_dir = self._path("raw")
        digests: list[str] = []
        for line in lines:
            digest = sha256_hex(line.encode("utf-8"))
            target = raw_dir / digest
            if target.exists():
                stored = target.read_bytes()
                if sha256_hex(stored) != digest:
                    raise BenchmarkError(f"content-addressed collision at {digest}")
            else:
                target.write_text(line, encoding="utf-8")
            digests.append(digest)
        return tuple(digests)

    def read_raw(self, digest: str) -> str:
        if len(digest) != 64 or any(c not in _HEX for c in digest):
            raise BenchmarkError("raw digest must be sha256 hex")
        path = self._path(f"raw/{digest}")
        if not path.exists():
            raise BenchmarkError(f"raw digest not stored: {digest}")
        return path.read_text(encoding="utf-8")

    def store_samples(self, samples: tuple[BenchmarkSample, ...]) -> None:
        if not samples:
            raise BenchmarkError("cannot store an empty sample set")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": samples[0].run_id,
            "samples": [sample.to_dict() for sample in samples],
        }
        self._write_json(self._path(f"samples/{samples[0].run_id}.json"), payload)

    def load_samples(self, run_id: str) -> tuple[BenchmarkSample, ...]:
        payload = self._read_document(f"samples/{run_id}.json")
        if "schema_version" in payload and payload["schema_version"] != SCHEMA_VERSION:
            payload = migrate(payload, payload["schema_version"])
        return tuple(BenchmarkSample.from_dict(item) for item in payload["samples"])

    def store_summary(self, summary: BenchmarkSummary) -> None:
        payload = {"schema_version": SCHEMA_VERSION, "summary": summary.to_dict()}
        self._write_json(
            self._path(f"summaries/{summary.run_id}-{summary.statistic}.json"), payload
        )

    def load_summary(self, run_id: str, statistic: str = "p50") -> BenchmarkSummary:
        payload = self._read_document(f"summaries/{run_id}-{statistic}.json")
        if "schema_version" in payload and payload["schema_version"] != SCHEMA_VERSION:
            payload = migrate(payload, payload["schema_version"])
        return BenchmarkSummary.from_dict(payload["summary"])

    def store_run(self, run: CampaignRun) -> None:
        payload = {"schema_version": SCHEMA_VERSION, "run": run.to_dict()}
        self._write_json(self._path(f"runs/{run.run_id}.json"), payload)

    def load_run(self, run_id: str) -> CampaignRun:
        payload = self._read_document(f"runs/{run_id}.json")
        if "schema_version" in payload and payload["schema_version"] != SCHEMA_VERSION:
            payload = migrate(payload, payload["schema_version"])
        return CampaignRun.from_dict(payload["run"])

    def backup(self, destination: Path) -> None:
        """Copy the whole store to a destination inside an owned sibling workspace."""
        destination = OwnedPathResolver(self.root.parent).resolve(destination)
        if destination.exists():
            raise BenchmarkError("backup destination already exists")
        shutil.copytree(self.root, destination, symlinks=False)
        manifest = StoreManifest.from_dict(self._read_document("manifest.json"))
        self._write_json(
            destination / "manifest.json",
            manifest.to_dict(),
        )

    @classmethod
    def restore(cls, backup: Path, destination: Path) -> BenchmarkStore:
        """Restore a store from a backup produced by :meth:`backup`."""
        backup = OwnedPathResolver(destination.parent).resolve(backup)
        if not (backup / "manifest.json").exists():
            raise BenchmarkError("not a benchmark store backup")
        store = cls(destination)
        store.initialize()
        for child in backup.iterdir():
            target = store._path(child.name)
            if target.is_dir():
                shutil.rmtree(target)
                shutil.copytree(child, target, symlinks=False)
            else:
                target.write_bytes(child.read_bytes())
        return store

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_document(self, relative: str) -> dict[str, Any]:
        raw = Path(self.root, relative)
        if raw.is_symlink():
            raise OwnedPathError("store documents must not be symbolic links")
        return self._read_json(self._path(relative))

    def _read_json(self, path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise OwnedPathError("store documents must not be symbolic links")
        if not path.exists():
            raise BenchmarkError(f"store document missing: {path.name}")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return payload
