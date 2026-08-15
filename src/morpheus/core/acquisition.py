"""Verified resumable model/engine acquisition, reservations, quotas, and cache (RUNM-003).

Acquisition follows the durable architecture state machine (planned -> acquiring
-> verified -> staged) for every edge and keeps artifacts in an owned,
content-addressed cache: a sha256 digest names an artifact, verification is
required before any artifact becomes usable, and partial downloads resume from
a journal instead of restarting. All decisions are pure or bounded by the
owned-path resolver.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.core.state_machines import (
    MachineKind,
    MachineRecord,
    StateMachine,
    StateTransitionError,
)

SCHEMA_VERSION = 1
_HEX = frozenset("0123456789abcdef")


class AcquisitionError(ValueError):
    """An acquisition plan, policy, or cache operation violates its contract."""


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    """Trust rules applied to every acquisition plan."""

    permitted_sources: tuple[str, ...] = ()
    required_licenses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CacheQuota:
    """Bounded cache size; eviction never exceeds it."""

    max_bytes: int = 0


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    """Immutable installation plan for one model or engine artifact."""

    entry_id: str
    kind: str
    revision: str
    source_url: str
    expected_sha256: str
    declared_size_bytes: int
    license: str

    def __post_init__(self) -> None:
        if self.kind not in ("model", "engine"):
            raise AcquisitionError("acquisition kind must be model or engine")
        if not self.entry_id:
            raise AcquisitionError("acquisition entry id must not be empty")
        if not self.revision:
            raise AcquisitionError("acquisition revision must not be empty")
        if len(self.expected_sha256) != 64 or any(c not in _HEX for c in self.expected_sha256):
            raise AcquisitionError("expected sha256 must be a 64-char hex digest")
        if self.declared_size_bytes <= 0:
            raise AcquisitionError("declared size must be positive")


def acquisition_violations(plan: AcquisitionPlan, policy: AcquisitionPolicy) -> tuple[str, ...]:
    """Return trust violations for a plan; empty means the plan is admissible."""
    reasons: list[str] = []
    if policy.permitted_sources and not any(
        plan.source_url.startswith(prefix) for prefix in policy.permitted_sources
    ):
        reasons.append("source is not permitted by acquisition policy")
    if policy.required_licenses and plan.license not in policy.required_licenses:
        reasons.append("license is not permitted by acquisition policy")
    return tuple(reasons)


def disk_reservation_violations(
    plan: AcquisitionPlan,
    *,
    free_bytes: int,
    quota: CacheQuota,
) -> tuple[str, ...]:
    """Return declared-disk-impact violations; empty means the plan fits."""
    reasons: list[str] = []
    if free_bytes < plan.declared_size_bytes:
        reasons.append(f"declared size {plan.declared_size_bytes} exceeds free space {free_bytes}")
    if quota.max_bytes and plan.declared_size_bytes > quota.max_bytes:
        reasons.append(
            f"declared size {plan.declared_size_bytes} exceeds cache quota {quota.max_bytes}"
        )
    return tuple(reasons)


def verify_digest(path: Path, expected_sha256: str) -> bool:
    """Stream a file and compare its sha256 against the expected digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256


def cache_record_digest(plan: AcquisitionPlan) -> str:
    """Deterministic artifact identity: sha256 over the canonical plan content."""
    canonical = json.dumps(
        {
            "kind": plan.kind,
            "entry_id": plan.entry_id,
            "revision": plan.revision,
            "source_url": plan.source_url,
            "license": plan.license,
            "declared_size_bytes": plan.declared_size_bytes,
            "expected_sha256": plan.expected_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class CacheRecord:
    """Durable provenance for one cached artifact."""

    record_id: str
    plan: AcquisitionPlan
    machine: MachineRecord
    actual_size_bytes: int | None = None
    acquired_at: datetime | None = None
    verified_at: datetime | None = None
    evicted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.machine.machine != MachineKind.ACQUISITION:
            raise AcquisitionError("cache records use the acquisition machine")
        for stamp in (self.acquired_at, self.verified_at, self.evicted_at):
            if stamp is not None and stamp.tzinfo is None:
                raise AcquisitionError("cache timestamps must be timezone-aware")

    @property
    def state(self) -> str:
        return self.machine.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "plan": {
                "entry_id": self.plan.entry_id,
                "kind": self.plan.kind,
                "revision": self.plan.revision,
                "source_url": self.plan.source_url,
                "expected_sha256": self.plan.expected_sha256,
                "declared_size_bytes": self.plan.declared_size_bytes,
                "license": self.plan.license,
            },
            "machine": self.machine.public_dict(),
            "actual_size_bytes": self.actual_size_bytes,
            "acquired_at": self.acquired_at.astimezone(UTC).isoformat()
            if self.acquired_at
            else None,
            "verified_at": self.verified_at.astimezone(UTC).isoformat()
            if self.verified_at
            else None,
            "evicted_at": self.evicted_at.astimezone(UTC).isoformat() if self.evicted_at else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CacheRecord:
        unknown = set(payload) - {
            "record_id",
            "plan",
            "machine",
            "actual_size_bytes",
            "acquired_at",
            "verified_at",
            "evicted_at",
        }
        if unknown:
            raise AcquisitionError(f"unknown cache record field: {sorted(unknown)[0]}")
        plan = payload["plan"]

        def stamp(key: str) -> datetime | None:
            value = payload.get(key)
            if value is None:
                return None
            return datetime.fromisoformat(value).astimezone(UTC)

        return cls(
            record_id=payload["record_id"],
            plan=AcquisitionPlan(
                entry_id=plan["entry_id"],
                kind=plan["kind"],
                revision=plan["revision"],
                source_url=plan["source_url"],
                expected_sha256=plan["expected_sha256"],
                declared_size_bytes=plan["declared_size_bytes"],
                license=plan["license"],
            ),
            machine=MachineRecord(
                machine=MachineKind(payload["machine"]["machine"]),
                record_id=payload["machine"]["record_id"],
                state=payload["machine"]["state"],
                schema_version=payload["machine"]["schema_version"],
                checkpoint=payload["machine"]["checkpoint"],
            ),
            actual_size_bytes=payload.get("actual_size_bytes"),
            acquired_at=stamp("acquired_at"),
            verified_at=stamp("verified_at"),
            evicted_at=stamp("evicted_at"),
        )


@dataclass(slots=True)
class AcquisitionCache:
    """Owned, content-addressed, resumable artifact cache."""

    root: Path
    resolver: OwnedPathResolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = OwnedPathResolver(self.root)

    def _path(self, relative: str) -> Path:
        return self.resolver.resolve_relative(relative)

    def initialize(self) -> None:
        self._path("cache").mkdir(parents=True, exist_ok=True)
        self._path("records").mkdir(parents=True, exist_ok=True)
        self._path("partial").mkdir(parents=True, exist_ok=True)
        manifest = self._path("manifest.json")
        if not manifest.exists():
            self._write_json(
                manifest,
                {
                    "schema_version": SCHEMA_VERSION,
                    "created_at": datetime.now(UTC).astimezone(UTC).isoformat(),
                },
            )

    def begin(
        self,
        plan: AcquisitionPlan,
        *,
        policy: AcquisitionPolicy,
        free_bytes: int,
        quota: CacheQuota,
    ) -> int:
        """Validate and start (or resume) staging for a plan.

        Returns the number of bytes already received when a partial download
        is resumed; a fresh staging starts at zero.
        """
        violations = acquisition_violations(plan, policy) + disk_reservation_violations(
            plan, free_bytes=free_bytes, quota=quota
        )
        if violations:
            raise AcquisitionError("; ".join(violations))
        self.initialize()
        record_id = cache_record_digest(plan)
        record = self._load_or_create_record(record_id, plan)
        if record.state in ("verified", "staged"):
            raise AcquisitionError("artifact is already verified or staged")
        if record.state == "failed":
            raise AcquisitionError(
                "artifact previously failed verification; acquire again after cleanup"
            )
        partial = self._partial_path(record_id)
        if record.state == "acquiring" and partial.exists():
            return partial.stat().st_size
        if record.state != "acquiring":
            self._persist(self._advance(record, "acquiring"))
        partial.write_bytes(b"")
        return 0

    def append_chunk(self, plan: AcquisitionPlan, chunk: bytes) -> int:
        """Append bytes to the staged artifact; returns the new received size."""
        record_id = cache_record_digest(plan)
        record = self._load_record(record_id)
        if record.state != "acquiring":
            raise AcquisitionError("append requires an acquiring record")
        partial = self._partial_path(record_id)
        received = partial.stat().st_size
        if received + len(chunk) > plan.declared_size_bytes:
            raise AcquisitionError("received bytes exceed the declared size")
        with partial.open("ab") as stream:
            stream.write(chunk)
        return received + len(chunk)

    def verify(self, plan: AcquisitionPlan) -> CacheRecord:
        """Finalize a staged artifact: size and digest must both match."""
        record_id = cache_record_digest(plan)
        record = self._load_record(record_id)
        if record.state != "acquiring":
            raise AcquisitionError("verify requires an acquiring record")
        partial = self._partial_path(record_id)
        actual = partial.stat().st_size
        if actual != plan.declared_size_bytes:
            self._fail(record, "declared size mismatch", partial)
            raise AcquisitionError(
                f"declared size {plan.declared_size_bytes} does not match received {actual}"
            )
        if not verify_digest(partial, plan.expected_sha256):
            self._fail(record, "sha256 mismatch", partial)
            raise AcquisitionError("artifact failed its sha256 verification")
        target = self._cache_path(plan.kind, plan.expected_sha256)
        if target.exists() and not verify_digest(target, plan.expected_sha256):
            raise AcquisitionError(f"content-addressed collision at {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.move(str(partial), str(target))
        else:
            partial.unlink()
        now = datetime.now(UTC)
        verified = self._advance(record, "verified")
        self._persist(
            CacheRecord(
                record_id=record_id,
                plan=plan,
                machine=verified.machine,
                actual_size_bytes=actual,
                acquired_at=record.acquired_at or now,
                verified_at=now,
            )
        )
        return self._load_record(record_id)

    def lookup(self, digest: str) -> CacheRecord | None:
        """Return the verified record for a digest, if any."""
        if len(digest) != 64 or any(c not in _HEX for c in digest):
            raise AcquisitionError("digest must be sha256 hex")
        for path in self._path("records").glob("*.json"):
            record = CacheRecord.from_dict(self._read_document(f"records/{path.name}"))
            if (
                record.plan.expected_sha256 == digest
                and record.state == "verified"
                and record.evicted_at is None
            ):
                return record
        return None

    def artifact_path(self, digest: str, kind: str) -> Path:
        """Return the owned artifact path for a verified digest."""
        if len(digest) != 64 or any(c not in _HEX for c in digest):
            raise AcquisitionError("digest must be sha256 hex")
        raw = Path(self.root, f"cache/{kind}/{digest}")
        if raw.is_symlink():
            raise OwnedPathError("cached artifacts must not be symbolic links")
        path = self._cache_path(kind, digest)
        if not path.exists():
            raise AcquisitionError(f"artifact is not cached: {digest}")
        return path

    def verify_existing(self, digest: str, kind: str) -> bool:
        """Re-hash a cached artifact to prove integrity without mutating it."""
        return verify_digest(self.artifact_path(digest, kind), digest)

    def enforce_quota(self, quota: CacheQuota) -> tuple[str, ...]:
        """Evict the least-recently-verified artifacts until the quota holds.

        Returns the digests evicted; records keep their provenance and are
        marked evicted rather than deleted.
        """
        records = [
            record
            for record in self._all_records()
            if record.state == "verified" and record.evicted_at is None
        ]
        records.sort(key=lambda record: record.verified_at or datetime.min.replace(tzinfo=UTC))
        evicted: list[str] = []
        while records and self.disk_usage() > quota.max_bytes:
            record = records.pop(0)
            self.evict(record.plan)
            evicted.append(record.plan.expected_sha256)
        return tuple(evicted)

    def evict(self, plan: AcquisitionPlan) -> None:
        """Remove an artifact from the cache and mark its record evicted."""
        record = self._load_record(cache_record_digest(plan))
        if record.state != "verified":
            raise AcquisitionError("only verified artifacts can be evicted")
        path = self._cache_path(plan.kind, plan.expected_sha256)
        if path.exists():
            path.unlink()
        self._persist(
            CacheRecord(
                record_id=record.record_id,
                plan=record.plan,
                machine=record.machine,
                actual_size_bytes=record.actual_size_bytes,
                acquired_at=record.acquired_at,
                verified_at=record.verified_at,
                evicted_at=datetime.now(UTC),
            )
        )

    def cleanup_failed(self, plan: AcquisitionPlan) -> None:
        """Remove a failed staging partial and its journal."""
        record_id = cache_record_digest(plan)
        partial = self._partial_path(record_id)
        if partial.exists():
            partial.unlink()
        record = self._load_or_create_record(record_id, plan)
        if record.state == "failed":
            self._write_document(f"records/{record_id}.json", record.to_dict())

    def records(self) -> tuple[CacheRecord, ...]:
        return self._all_records()

    def disk_usage(self, records: tuple[CacheRecord, ...] | None = None) -> int:
        """Sum of artifact bytes currently present in the cache on disk."""
        total = 0
        for path in self._path("cache").rglob("*"):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        return total

    def _cache_path(self, kind: str, digest: str) -> Path:
        return self._path(f"cache/{kind}/{digest}")

    def _partial_path(self, record_id: str) -> Path:
        return self._path(f"partial/{record_id}.part")

    def _all_records(self) -> tuple[CacheRecord, ...]:
        paths = sorted(self._path("records").glob("*.json"))
        return tuple(
            CacheRecord.from_dict(self._read_document(f"records/{path.name}")) for path in paths
        )

    def _load_or_create_record(self, record_id: str, plan: AcquisitionPlan) -> CacheRecord:
        relative = f"records/{record_id}.json"
        if self._path(relative).exists():
            return CacheRecord.from_dict(self._read_document(relative))
        record = CacheRecord(
            record_id=record_id,
            plan=plan,
            machine=MachineRecord(
                machine=MachineKind.ACQUISITION,
                record_id=record_id,
                state="planned",
            ),
        )
        self._write_document(f"records/{record_id}.json", record.to_dict())
        return record

    def _load_record(self, record_id: str) -> CacheRecord:
        return CacheRecord.from_dict(self._read_document(f"records/{record_id}.json"))

    def _advance(self, record: CacheRecord, target: str) -> CacheRecord:
        result = StateMachine.transition(record.machine, target)
        if not result.accepted or result.record is None:
            raise StateTransitionError(result.audit)
        return CacheRecord(
            record_id=record.record_id,
            plan=record.plan,
            machine=result.record,
            actual_size_bytes=record.actual_size_bytes,
            acquired_at=record.acquired_at,
            verified_at=record.verified_at,
            evicted_at=record.evicted_at,
        )

    def _fail(self, record: CacheRecord, reason: str, partial: Path) -> None:
        if partial.exists():
            partial.unlink()
        failed = self._advance(record, "failed")
        self._persist(
            CacheRecord(
                record_id=record.record_id,
                plan=record.plan,
                machine=failed.machine,
                actual_size_bytes=record.actual_size_bytes,
                acquired_at=record.acquired_at,
                verified_at=record.verified_at,
            )
        )
        journal = self._partial_path(record.record_id)
        journal.unlink(missing_ok=True)

    def _persist(self, record: CacheRecord) -> None:
        self._write_document(f"records/{record.record_id}.json", record.to_dict())

    def _write_document(self, relative: str, payload: dict[str, Any]) -> None:
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_document(self, relative: str) -> dict[str, Any]:
        raw = Path(self.root, relative)
        if raw.is_symlink():
            raise OwnedPathError("cache documents must not be symbolic links")
        path = self._path(relative)
        if not path.exists():
            raise AcquisitionError(f"cache document missing: {path.name}")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return payload
