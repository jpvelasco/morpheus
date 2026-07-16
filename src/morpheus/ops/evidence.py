from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Self
from uuid import uuid4

from morpheus.core.paths import OwnedPathResolver
from morpheus.core.redaction import redact

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENVIRONMENTS = frozenset({"DEV", "VM", "HOST-RO", "HOST-MAINT"})
_RESERVED_PATHS = frozenset({"manifest.json"})
_SCAN_CHUNK_SIZE = 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_ARCHIVE_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 512 * 1024 * 1024


class EvidenceStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - evidence outcome, not a password  # nosec B105
    FAIL = "fail"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class CanaryLeakError(ValueError):
    """Raised before evidence containing a raw privacy canary can be persisted."""


@dataclass(frozen=True)
class EvidenceRunSpec:
    task_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    environment: str
    source_commit: str
    reviewer: str | None = None
    authorization_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.task_ids or any(not value.strip() for value in self.task_ids):
            raise ValueError("at least one non-empty task ID is required")
        if any(not value.strip() for value in self.requirement_ids):
            raise ValueError("requirement IDs must be non-empty")
        if self.environment not in _ENVIRONMENTS:
            raise ValueError(f"unsupported evidence environment: {self.environment}")
        if not re.fullmatch(r"[0-9a-f]{7,64}", self.source_commit):
            raise ValueError("source commit must be a lowercase hexadecimal Git object ID")


class CanaryGuard:
    """Redact known canaries and reject opaque artifacts that still contain one."""

    def __init__(self, canaries: Mapping[str, str]) -> None:
        normalized: dict[str, bytes] = {}
        seen_values: set[str] = set()
        for name, value in canaries.items():
            if not name or not value:
                raise ValueError("canary names and values must be non-empty")
            if value in seen_values:
                raise ValueError("canary values must be unique")
            normalized[name] = value.encode()
            seen_values.add(value)
        self._canaries = dict(sorted(normalized.items()))
        self._redaction_values = tuple(
            sorted(self._canaries.values(), key=lambda item: (-len(item), item))
        )

    @property
    def identifiers(self) -> dict[str, str]:
        return {name: self.identifier(name) for name in self._canaries}

    def identifier(self, name: str) -> str:
        try:
            value = self._canaries[name]
        except KeyError as error:
            raise KeyError(f"unknown canary class: {name}") from error
        return f"sha256:{hashlib.sha256(value).hexdigest()}"

    def sanitize_text(self, value: str) -> str:
        safe = value
        for canary in self._canaries.values():
            safe = safe.replace(canary.decode(), "[REDACTED]")
        return safe

    def stream_redactor(self) -> _CanaryStreamRedactor:
        return _CanaryStreamRedactor(self._redaction_values)

    def scan_bytes(self, value: bytes, *, context: str) -> None:
        for name, canary in self._canaries.items():
            if canary in value:
                raise CanaryLeakError(f"raw {name} canary detected in {context}")

    def _scan_stream(self, stream: BinaryIO, *, context: str) -> None:
        overlap = max((len(value) for value in self._canaries.values()), default=1) - 1
        previous = b""
        while chunk := stream.read(_SCAN_CHUNK_SIZE):
            self.scan_bytes(previous + chunk, context=context)
            previous = chunk[-overlap:] if overlap else b""

    def scan_file(self, source: Path, *, context: str | None = None) -> None:
        label = context or source.name
        with source.open("rb") as stream:
            self._scan_stream(stream, context=label)
        if not zipfile.is_zipfile(source):
            return
        with zipfile.ZipFile(source) as archive:
            self._validate_archive(archive, context=label)
            for member in archive.infolist():
                if member.is_dir():
                    continue
                with archive.open(member) as stream:
                    content = stream.read()
                member_context = f"{label}:{member.filename}"
                self.scan_bytes(content, context=member_context)
                self._scan_nested_zip(content, context=member_context, depth=1)

    def _scan_nested_zip(self, content: bytes, *, context: str, depth: int) -> None:
        if depth > 3:
            raise ValueError(f"archive nesting exceeds evidence inspection limit in {context}")
        stream = io.BytesIO(content)
        if not zipfile.is_zipfile(stream):
            return
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            self._validate_archive(archive, context=context)
            for member in archive.infolist():
                if member.is_dir():
                    continue
                nested = archive.read(member)
                member_context = f"{context}:{member.filename}"
                self.scan_bytes(nested, context=member_context)
                self._scan_nested_zip(nested, context=member_context, depth=depth + 1)

    @staticmethod
    def _validate_archive(archive: zipfile.ZipFile, *, context: str) -> None:
        members = archive.infolist()
        if len(members) > _MAX_ARCHIVE_ENTRIES:
            raise ValueError(f"archive has too many entries for evidence inspection: {context}")
        total = 0
        for member in members:
            if member.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
                raise ValueError(f"archive member exceeds evidence inspection limit: {context}")
            total += member.file_size
            if total > _MAX_ARCHIVE_TOTAL_BYTES:
                raise ValueError(f"archive exceeds evidence inspection limit: {context}")


class _CanaryStreamRedactor:
    def __init__(self, canaries: tuple[bytes, ...]) -> None:
        self._canaries = canaries
        self._overlap = max((len(value) for value in canaries), default=1) - 1
        self._pending = b""

    def feed(self, value: bytes) -> bytes:
        self._pending += value
        boundary = max(0, len(self._pending) - self._overlap)
        return self._consume(boundary)

    def finish(self) -> bytes:
        return self._consume(len(self._pending))

    def _consume(self, boundary: int) -> bytes:
        output = bytearray()
        position = 0
        while position < boundary:
            match = next(
                (canary for canary in self._canaries if self._pending.startswith(canary, position)),
                None,
            )
            if match is None:
                output.append(self._pending[position])
                position += 1
            else:
                output.extend(b"[REDACTED]")
                position += len(match)
        self._pending = self._pending[position:]
        return bytes(output)


class RedactedEvidenceStream:
    def __init__(self, destination: Path, temporary: Path, guard: CanaryGuard) -> None:
        self._destination = destination
        self._temporary = temporary
        self._stream = temporary.open("xb")
        self._redactor = guard.stream_redactor()
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del error, traceback
        if error_type is None:
            self.close()
        else:
            self.abort()

    def write(self, value: bytes) -> None:
        if self._closed:
            raise RuntimeError("evidence stream is closed")
        self._stream.write(self._redactor.feed(value))

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._stream.write(self._redactor.finish())
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            self._temporary.chmod(0o640)
            os.replace(self._temporary, self._destination)
        finally:
            self._closed = True
            if not self._stream.closed:
                self._stream.close()
            self._temporary.unlink(missing_ok=True)

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stream.close()
        self._temporary.unlink(missing_ok=True)


class EvidenceRun:
    def __init__(
        self,
        path: Path,
        spec: EvidenceRunSpec,
        guard: CanaryGuard,
        started_at: datetime,
    ) -> None:
        self._paths = OwnedPathResolver(path)
        self.path = self._paths.root
        self._spec = spec
        self._guard = guard
        self._started_at = _utc_text(started_at)
        self._finalized = False

    @classmethod
    def create(
        cls,
        root: Path,
        run_id: str,
        spec: EvidenceRunSpec,
        *,
        guard: CanaryGuard,
        started_at: datetime,
    ) -> EvidenceRun:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid evidence run ID")
        _utc_text(started_at)
        paths = OwnedPathResolver(root)
        paths.root.mkdir(parents=True, exist_ok=True)
        path = paths.resolve_relative(run_id)
        path.mkdir(mode=0o750)
        return cls(path, spec, guard, started_at)

    def write_json(self, relative_path: str, value: Any) -> Path:
        safe_value = redact(value)
        content = json.dumps(safe_value, indent=2, sort_keys=True).encode() + b"\n"
        return self._write_bytes(relative_path, self._sanitize(content))

    def write_text(self, relative_path: str, value: str) -> Path:
        return self._write_bytes(relative_path, self._guard.sanitize_text(value).encode())

    def open_redacted_stream(self, relative_path: str) -> RedactedEvidenceStream:
        self._ensure_open()
        destination = self._destination(relative_path)
        self._prepare_destination(destination)
        return RedactedEvidenceStream(destination, _temporary_path(destination), self._guard)

    def import_artifact(self, source: Path, relative_path: str) -> Path:
        self._ensure_open()
        destination = self._destination(relative_path)
        if source.is_symlink() or not source.is_file():
            raise ValueError("evidence source must be a regular file")
        self._guard.scan_file(source, context=relative_path)
        self._prepare_destination(destination)
        temporary = _temporary_path(destination)
        try:
            with source.open("rb") as source_stream, temporary.open("xb") as destination_stream:
                shutil.copyfileobj(source_stream, destination_stream)
                destination_stream.flush()
                os.fsync(destination_stream.fileno())
            temporary.chmod(0o640)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def finalize(
        self,
        status: EvidenceStatus,
        *,
        ended_at: datetime,
        safe_summary: str,
        tool_versions: Mapping[str, str],
        candidate_checksums: Mapping[str, str] | None = None,
        pre_state_digest: str | None = None,
        post_state_digest: str | None = None,
    ) -> Path:
        self._ensure_open()
        ended_text = _utc_text(ended_at)
        if ended_at.astimezone(UTC) < _parse_utc(self._started_at):
            raise ValueError("evidence end time precedes start time")
        for digest in (pre_state_digest, post_state_digest):
            if digest is not None and not _SHA256.fullmatch(digest):
                raise ValueError("state digests must use sha256:<lowercase-hex>")
        candidates = dict(sorted((candidate_checksums or {}).items()))
        if any(not _SHA256.fullmatch(value) for value in candidates.values()):
            raise ValueError("candidate checksums must use sha256:<lowercase-hex>")

        files = self._inventory_files()
        manifest = {
            "format": 1,
            "run_id": self.path.name,
            "task_ids": list(self._spec.task_ids),
            "requirement_ids": list(self._spec.requirement_ids),
            "environment": self._spec.environment,
            "source_commit": self._spec.source_commit,
            "candidate_checksums": candidates,
            "started_at": self._started_at,
            "ended_at": ended_text,
            "status": status.value,
            "safe_summary": self._guard.sanitize_text(safe_summary),
            "tools": dict(sorted(tool_versions.items())),
            "pre_state_digest": pre_state_digest,
            "post_state_digest": post_state_digest,
            "reviewer": self._spec.reviewer,
            "authorization_ref": self._spec.authorization_ref,
            "canary_identifiers": self._guard.identifiers,
            "files": files,
        }
        content = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
        destination = self._write_bytes("manifest.json", self._sanitize(content), reserved=True)
        self._guard.scan_file(destination)
        self._finalized = True
        return destination

    def _sanitize(self, content: bytes) -> bytes:
        return self._guard.sanitize_text(content.decode()).encode()

    def _inventory_files(self) -> dict[str, dict[str, int | str]]:
        inventory: dict[str, dict[str, int | str]] = {}
        for path in sorted(self.path.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"symlinks are not allowed in evidence: {path.name}")
            if not path.is_file():
                continue
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                raise ValueError(f"temporary file found in evidence: {path.name}")
            relative = path.relative_to(self.path).as_posix()
            self._guard.scan_file(path, context=relative)
            size, digest = _file_identity(path)
            inventory[relative] = {
                "sha256": digest,
                "size": size,
            }
        return inventory

    def _write_bytes(self, relative_path: str, content: bytes, *, reserved: bool = False) -> Path:
        self._ensure_open()
        destination = self._destination(relative_path, reserved=reserved)
        self._guard.scan_bytes(content, context=relative_path)
        self._prepare_destination(destination)
        temporary = _temporary_path(destination)
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o640)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _destination(self, relative_path: str, *, reserved: bool = False) -> Path:
        path = Path(relative_path)
        if (
            not relative_path
            or "\\" in relative_path
            or path.is_absolute()
            or path == Path(".")
            or ".." in path.parts
            or (relative_path in _RESERVED_PATHS and not reserved)
        ):
            raise ValueError(f"invalid evidence path: {relative_path}")
        return self._paths.resolve_relative(path)

    def _prepare_destination(self, destination: Path) -> None:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        current = parent
        while current != self.path:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError(f"symlinks are not allowed in evidence paths: {current.name}")
            current = current.parent

    def _ensure_open(self) -> None:
        if self._finalized:
            raise RuntimeError("evidence run is already finalized")


def _temporary_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_SCAN_CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()
