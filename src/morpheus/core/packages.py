"""Versioned, checksummed, target-native backend packages (PLAT-003).

A package is an immutable artifact: a zip with a strict manifest, per-file
SHA-256 digests, and a bounded SPDX document listing exactly the same
files. Building, scanning, and digest verification are pure and testable;
scanning rejects corrupt, tampered, symlinked, or path-escaping archives.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from morpheus.core.durable import fsync_directory, fsync_file

PACKAGE_SCHEMA_VERSION = 1
DIGEST_ALGORITHM = "sha256"
PACKAGE_SUFFIX = ".mrpkg"
PLATFORM_PATTERN = re.compile(r"^(win32|linux|darwin)-(x86_64|arm64)$")
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ENTRY_PART_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class PackageError(ValueError):
    """A package is malformed, tampered, or violates the package contract."""


@dataclass(frozen=True, slots=True, order=True)
class PackageVersion:
    """Strict ``X.Y.Z`` semantic version; services version independently."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, value: str) -> PackageVersion:
        if not _VERSION_PATTERN.fullmatch(value):
            raise PackageError(f"version must match X.Y.Z: {value!r}")
        major, minor, patch = (int(part) for part in value.split("."))
        return cls(major=major, minor=minor, patch=patch)


@dataclass(frozen=True, slots=True)
class PackageManifest:
    """Strict, canonical package identity and content digest list."""

    name: str
    version: PackageVersion
    platform: str
    files: tuple[tuple[str, str], ...]

    @classmethod
    def from_json(cls, value: Any) -> PackageManifest:
        if not isinstance(value, dict):
            raise PackageError("package manifest is invalid")
        if value.get("schema_version") != PACKAGE_SCHEMA_VERSION:
            raise PackageError("package manifest schema version is incompatible")
        if value.get("algorithm") != DIGEST_ALGORITHM:
            raise PackageError("package manifest algorithm is unsupported")
        name = value.get("name")
        if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
            raise PackageError("package name is not a bounded identifier")
        version = value.get("version")
        if not isinstance(version, str):
            raise PackageError("package version is invalid")
        platform = value.get("platform")
        if not isinstance(platform, str) or not PLATFORM_PATTERN.fullmatch(platform):
            raise PackageError("package platform is unsupported")
        files = value.get("files")
        if not isinstance(files, dict):
            raise PackageError("package manifest files are invalid")
        entries: list[tuple[str, str]] = []
        for relative, digest in files.items():
            if not isinstance(relative, str) or not isinstance(digest, str):
                raise PackageError("package manifest entry is invalid")
            _safe_package_name(relative)
            entries.append((relative, digest))
        return cls(
            name=name,
            version=PackageVersion.parse(version),
            platform=platform,
            files=tuple(sorted(entries)),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "algorithm": DIGEST_ALGORITHM,
            "name": self.name,
            "version": str(self.version),
            "platform": self.platform,
            "files": dict(self.files),
        }


def _safe_package_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PackageError(f"unsafe package path: {name}")
    for part in path.parts:
        if not _ENTRY_PART_PATTERN.fullmatch(part):
            raise PackageError(f"unsafe package path: {name}")
    return path


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_file_name(name: str, version: PackageVersion, platform: str) -> str:
    if not _NAME_PATTERN.fullmatch(name):
        raise PackageError("package name is not a bounded identifier")
    if not PLATFORM_PATTERN.fullmatch(platform):
        raise PackageError("package platform is unsupported")
    return f"{name}-{version}-{platform}{PACKAGE_SUFFIX}"


def package_digest(artifact: Path) -> str:
    """Whole-artifact digest used for transfer integrity verification."""
    return _digest(artifact.read_bytes())


def build_package(
    staging_dir: Path,
    destination: Path,
    *,
    name: str,
    version: PackageVersion,
    platform: str,
) -> Path:
    """Bundle ``staging_dir`` into a checksummed package with an SBOM."""
    if not staging_dir.is_dir() or staging_dir.is_symlink():
        raise PackageError("package staging directory is invalid")
    contents: dict[str, bytes] = {}
    for source in sorted(staging_dir.rglob("*")):
        if source.is_symlink():
            raise PackageError("package source contains a symbolic link")
        if not source.is_file():
            continue
        relative = source.relative_to(staging_dir).as_posix()
        _safe_package_name(relative)
        contents[relative] = source.read_bytes()
    manifest = PackageManifest(
        name=name,
        version=version,
        platform=platform,
        files=tuple((relative, _digest(data)) for relative, data in sorted(contents.items())),
    )
    sbom = _build_sbom(manifest, contents)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=PACKAGE_SUFFIX, dir=destination.parent
    ) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest.to_json(), sort_keys=True))
            bundle.writestr("sbom.spdx.json", json.dumps(sbom, sort_keys=True))
            for relative, data in sorted(contents.items()):
                bundle.writestr(f"files/{relative}", data)
        fsync_file(temporary)
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def scan_package(artifact: Path) -> tuple[PackageManifest, dict[str, bytes]]:
    """Verify a package completely and return its manifest and contents.

    Rejects: missing or invalid manifests, entry/symlink mismatches, unsafe
    paths, per-file checksum mismatches, and SBOMs that disagree with the
    manifest.
    """
    artifact = artifact.resolve()
    if not artifact.is_file() or artifact.is_symlink():
        raise PackageError("package artifact is invalid")
    with zipfile.ZipFile(artifact) as bundle:
        for info in bundle.infolist():
            _safe_package_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise PackageError("package contains a symbolic link")
        try:
            manifest_data = json.loads(bundle.read("manifest.json"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PackageError("package manifest is missing or invalid") from error
        manifest = PackageManifest.from_json(manifest_data)
        expected_entries = {
            "manifest.json",
            "sbom.spdx.json",
            *(f"files/{relative}" for relative, _ in manifest.files),
        }
        if set(bundle.namelist()) != expected_entries:
            raise PackageError("package entries do not match the manifest")
        verified: dict[str, bytes] = {}
        for relative, expected_digest in manifest.files:
            data = bundle.read(f"files/{relative}")
            if _digest(data) != expected_digest:
                raise PackageError(f"package checksum mismatch for {relative}")
            verified[relative] = data
        try:
            sbom_data = json.loads(bundle.read("sbom.spdx.json"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PackageError("package SBOM is missing or invalid") from error
        _validate_sbom(sbom_data, manifest, verified)
    return manifest, verified


def _build_sbom(manifest: PackageManifest, contents: dict[str, bytes]) -> dict[str, Any]:
    package_id = f"SPDXRef-Package-{manifest.name}-{manifest.version}"
    document_hash = _digest(json.dumps(manifest.to_json(), sort_keys=True).encode())
    files = [
        {
            "fileName": relative,
            "SPDXID": f"SPDXRef-File-{index}",
            "checksums": [{"algorithm": "SHA256", "checksumValue": _digest(data)}],
        }
        for index, (relative, data) in enumerate(sorted(contents.items()))
    ]
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{manifest.name}-{manifest.version}",
        "documentNamespace": (
            f"https://morpheus.local/spdx/{manifest.name}-{manifest.version}-{document_hash}"
        ),
        "documentDescribes": [package_id],
        "creationInfo": {
            "created": datetime.now(UTC).isoformat(),
            "creators": ["Tool: morpheus-control-plane"],
        },
        "packages": [
            {
                "name": manifest.name,
                "SPDXID": package_id,
                "versionInfo": str(manifest.version),
                "downloadLocation": "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
                "filesAnalyzed": True,
                "packageFileName": package_file_name(
                    manifest.name, manifest.version, manifest.platform
                ),
            }
        ],
        "files": files,
        "relationships": [
            {
                "spdxElementId": package_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": f"SPDXRef-File-{index}",
            }
            for index in range(len(files))
        ],
    }


def _validate_sbom(value: Any, manifest: PackageManifest, contents: dict[str, bytes]) -> None:
    if not isinstance(value, dict):
        raise PackageError("package SBOM is invalid")
    if value.get("spdxVersion") != "SPDX-2.3":
        raise PackageError("package SBOM version is unsupported")
    packages = value.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise PackageError("package SBOM package entry is invalid")
    package = packages[0]
    if (
        not isinstance(package, dict)
        or package.get("name") != manifest.name
        or package.get("versionInfo") != str(manifest.version)
    ):
        raise PackageError("package SBOM identity disagrees with the manifest")
    package_id = f"SPDXRef-Package-{manifest.name}-{manifest.version}"
    if value.get("documentDescribes") != [package_id]:
        raise PackageError("package SBOM identity disagrees with the manifest")
    files = value.get("files")
    if not isinstance(files, list):
        raise PackageError("package SBOM file list is invalid")
    expected = set(contents)
    listed: dict[str, str] = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("fileName"), str):
            raise PackageError("package SBOM file entry is invalid")
        checksums = entry.get("checksums")
        if not isinstance(checksums, list) or len(checksums) != 1:
            raise PackageError("package SBOM file checksum is invalid")
        checksum = checksums[0]
        if (
            not isinstance(checksum, dict)
            or checksum.get("algorithm") != "SHA256"
            or not isinstance(checksum.get("checksumValue"), str)
        ):
            raise PackageError("package SBOM file checksum is invalid")
        listed[entry["fileName"]] = checksum["checksumValue"]
    if set(listed) != expected:
        raise PackageError("package SBOM file list disagrees with the manifest")
    for relative, data in contents.items():
        if listed[relative] != _digest(data):
            raise PackageError(f"package SBOM checksum mismatch for {relative}")


def extract_package(
    manifest: PackageManifest,
    contents: dict[str, bytes],
    destination: Path,
) -> None:
    """Extract a verified package into a fresh destination directory."""
    destination = destination.resolve()
    if destination.exists():
        raise PackageError("package extraction destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for relative, data in contents.items():
            target = staging / _safe_package_name(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        os.replace(staging, destination)
        fsync_directory(destination.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
