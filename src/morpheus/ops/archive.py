from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from morpheus.core.paths import OwnedPathResolver


class ArchiveValidationError(ValueError):
    """A backup archive is corrupt, incompatible, or unsafe."""


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
            {"version": 1, "algorithm": "sha256", "files": files},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", manifest)
            for relative, data in contents.items():
                bundle.writestr(f"files/{relative}", data)
        os.replace(temporary, destination)
        return destination

    def restore(self, archive: Path) -> None:
        archive = self._paths.workspace_path("backups", archive)
        parent = self._root.parent
        parent.mkdir(parents=True, exist_ok=True)
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
            files = self._validate_manifest(manifest_data)
            expected_entries = {"manifest.json", *(f"files/{name}" for name in files)}
            if set(bundle.namelist()) != expected_entries:
                raise ArchiveValidationError("archive entries do not match the manifest")
            verified: dict[str, bytes] = {}
            for relative, expected_digest in files.items():
                data = bundle.read(f"files/{relative}")
                if not isinstance(expected_digest, str) or _digest(data) != expected_digest:
                    raise ArchiveValidationError(f"checksum mismatch for {relative}")
                verified[relative] = data

        staging = self._paths.create_staging_directory("restore")
        previous = self._paths.staging_path("previous")
        try:
            for relative, data in verified.items():
                target = staging / _safe_name(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if previous.exists():
                shutil.rmtree(previous)
            if self._root.exists():
                os.replace(self._root, previous)
            try:
                os.replace(staging, self._root)
            except OSError:
                if previous.exists():
                    os.replace(previous, self._root)
                raise
            if previous.exists():
                shutil.rmtree(previous)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    @staticmethod
    def _validate_manifest(value: Any) -> dict[str, str]:
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ArchiveValidationError("archive manifest version is incompatible")
        files = value.get("files")
        if not isinstance(files, dict):
            raise ArchiveValidationError("archive manifest files are invalid")
        result: dict[str, str] = {}
        for name, digest in files.items():
            if not isinstance(name, str) or not isinstance(digest, str):
                raise ArchiveValidationError("archive manifest entry is invalid")
            _safe_name(name)
            result[name] = digest
        return result
