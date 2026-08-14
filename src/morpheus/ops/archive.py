from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from morpheus.core.paths import OwnedPathResolver


class ArchiveValidationError(ValueError):
    """A backup archive is corrupt, incompatible, or unsafe."""


_ARCHIVE_FORMAT_VERSION = 2
_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RestorePreflight:
    file_count: int
    total_bytes: int
    schema_version: int


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ArchiveValidationError(f"unsafe archive path: {name}")
    return path


class BackupManager:
    def __init__(self, *, owned_root: Path) -> None:
        self._paths = OwnedPathResolver(owned_root)
        self._root = self._paths.root

    def create(self, destination: Path) -> Path:
        if not self._root.is_dir():
            raise FileNotFoundError("Morpheus-owned state root does not exist")
        destination = self._paths.workspace_path("backups", destination)
        temporary = self._paths.workspace_path(
            "backups", destination.with_name(f".{destination.name}.tmp")
        )
        files: dict[str, str] = {}
        contents: dict[str, bytes] = {}
        for source in sorted(self._root.rglob("*")):
            if source.is_symlink():
                raise ArchiveValidationError("backup source contains a symbolic link")
            if not source.is_file():
                continue
            if source in (destination, temporary):
                continue
            relative = source.relative_to(self._root).as_posix()
            data = source.read_bytes()
            files[relative] = _digest(data)
            contents[relative] = data
        manifest = json.dumps(
            {
                "version": _ARCHIVE_FORMAT_VERSION,
                "schema_version": _STATE_SCHEMA_VERSION,
                "algorithm": "sha256",
                "files": files,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("manifest.json", manifest)
                for relative, data in contents.items():
                    bundle.writestr(f"files/{relative}", data)
            _fsync_file(temporary)
            os.replace(temporary, destination)
            _fsync_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def restore_preflight(self, archive: Path) -> RestorePreflight:
        archive = self._paths.workspace_path("backups", archive)
        verified, schema_version = self._verified_archive(archive)
        total_bytes = sum(len(data) for data in verified.values())
        available = shutil.disk_usage(self._root.parent).free
        if available < total_bytes:
            raise ArchiveValidationError("insufficient free space for restore staging")
        return RestorePreflight(
            file_count=len(verified), total_bytes=total_bytes, schema_version=schema_version
        )

    def restore(self, archive: Path) -> None:
        archive = self._paths.workspace_path("backups", archive)
        verified, _ = self._verified_archive(archive)
        self.restore_preflight(archive)
        parent = self._root.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = self._paths.create_staging_directory("restore")
        previous = self._paths.staging_path("previous")
        try:
            for relative, data in verified.items():
                target = staging / _safe_name(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_durable(target, data)
            _fsync_directory(staging)
            if previous.exists():
                shutil.rmtree(previous)
            if self._root.exists():
                os.replace(self._root, previous)
                _fsync_directory(parent)
            try:
                os.replace(staging, self._root)
                _fsync_directory(parent)
            except OSError:
                if previous.exists():
                    os.replace(previous, self._root)
                    _fsync_directory(parent)
                raise
            if previous.exists():
                shutil.rmtree(previous)
                _fsync_directory(parent)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _verified_archive(self, archive: Path) -> tuple[dict[str, bytes], int]:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                _safe_name(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ArchiveValidationError("archive contains a symbolic link")
            try:
                manifest_data = json.loads(bundle.read("manifest.json"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ArchiveValidationError("archive manifest is missing or invalid") from error
            files, schema_version = self._validate_manifest(manifest_data)
            expected_entries = {"manifest.json", *(f"files/{name}" for name in files)}
            if set(bundle.namelist()) != expected_entries:
                raise ArchiveValidationError("archive entries do not match the manifest")
            verified: dict[str, bytes] = {}
            for relative, expected_digest in files.items():
                data = bundle.read(f"files/{relative}")
                if not isinstance(expected_digest, str) or _digest(data) != expected_digest:
                    raise ArchiveValidationError(f"checksum mismatch for {relative}")
                verified[relative] = data
        return verified, schema_version

    @staticmethod
    def _validate_manifest(value: Any) -> tuple[dict[str, str], int]:
        if not isinstance(value, dict) or value.get("version") != _ARCHIVE_FORMAT_VERSION:
            raise ArchiveValidationError("archive manifest version is incompatible")
        schema_version = value.get("schema_version")
        if schema_version != _STATE_SCHEMA_VERSION:
            raise ArchiveValidationError("archive schema version is incompatible")
        files = value.get("files")
        if not isinstance(files, dict):
            raise ArchiveValidationError("archive manifest files are invalid")
        result: dict[str, str] = {}
        for name, digest in files.items():
            if not isinstance(name, str) or not isinstance(digest, str):
                raise ArchiveValidationError("archive manifest entry is invalid")
            _safe_name(name)
            result[name] = digest
        return result, schema_version


def _write_durable(destination: Path, data: bytes) -> None:
    with destination.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_file(path: Path) -> None:
    if os.name == "nt":
        # Windows cannot fsync a read-only file handle; its write path already
        # flushes file data, so directory-level durability has no counterpart.
        return
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        # Windows flushes directory metadata through file fsync; the POSIX
        # O_DIRECTORY descriptor protocol does not exist there.
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
