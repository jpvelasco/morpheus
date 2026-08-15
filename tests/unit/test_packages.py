"""Unit tests: versioned backend packages (PLAT-003)."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

from morpheus.core.packages import (
    DIGEST_ALGORITHM,
    PACKAGE_SCHEMA_VERSION,
    PackageError,
    PackageManifest,
    PackageVersion,
    build_package,
    extract_package,
    package_digest,
    package_file_name,
    scan_package,
)

PLATFORM = "linux-x86_64"


def staging(tmp_path: Path, **files) -> Path:
    directory = tmp_path / "staging"
    directory.mkdir(exist_ok=True)
    for relative, data in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return directory


def build(tmp_path: Path, **overrides) -> Path:
    fields = {
        "name": "backend",
        "version": PackageVersion(1, 0, 0),
        "platform": PLATFORM,
    }
    fields.update(overrides)
    source = staging(tmp_path, **{"app/main.py": b"import morpheus", "app/conf.json": b"{}"})
    destination = tmp_path / "artifacts"
    destination.mkdir(exist_ok=True)
    return build_package(
        source,
        destination / package_file_name(fields["name"], fields["version"], fields["platform"]),
        **fields,
    )


def test_package_version_parse_str_and_ordering() -> None:
    assert str(PackageVersion(1, 2, 3)) == "1.2.3"
    assert PackageVersion.parse("1.2.3") == PackageVersion(1, 2, 3)
    assert PackageVersion(1, 2, 3) < PackageVersion(1, 2, 4)
    assert PackageVersion(1, 2, 3) < PackageVersion(1, 3, 0)
    assert PackageVersion(1, 2, 3) < PackageVersion(2, 0, 0)
    for broken in ("1.2", "1.2.3.4", "v1.2.3", "1.2.x", "", "1.2.3\n"):
        with pytest.raises(PackageError, match="X.Y.Z"):
            PackageVersion.parse(broken)


def valid_manifest_json() -> dict:
    return {
        "schema_version": 1,
        "algorithm": "sha256",
        "name": "backend",
        "version": "1.0.0",
        "platform": PLATFORM,
        "files": {"app/main.py": "0" * 64},
    }


def test_package_file_name_and_manifest_validation() -> None:
    assert package_file_name("backend", PackageVersion(1, 0, 0), PLATFORM) == (
        "backend-1.0.0-linux-x86_64.mrpkg"
    )
    with pytest.raises(PackageError, match="bounded"):
        package_file_name("Backend", PackageVersion(1, 0, 0), PLATFORM)
    with pytest.raises(PackageError, match="unsupported"):
        package_file_name("backend", PackageVersion(1, 0, 0), "wasm32")
    with pytest.raises(PackageError, match="manifest files"):
        PackageManifest.from_json({**valid_manifest_json(), "files": []})
    with pytest.raises(PackageError, match="schema version"):
        PackageManifest.from_json({**valid_manifest_json(), "schema_version": 2})


def test_build_and_scan_roundtrip_preserves_contents(tmp_path) -> None:
    artifact = build(tmp_path)
    assert artifact.is_file()
    manifest, contents = scan_package(artifact)
    assert manifest.name == "backend"
    assert manifest.version == PackageVersion(1, 0, 0)
    assert manifest.platform == PLATFORM
    assert set(contents) == {"app/main.py", "app/conf.json"}
    assert contents["app/main.py"] == b"import morpheus"
    assert all(entry[1] == manifest.to_json()["files"][entry[0]] for entry in manifest.files)


def test_package_digest_is_deterministic(tmp_path) -> None:
    first = build(tmp_path)
    assert package_digest(first) == package_digest(first)
    assert len(package_digest(first)) == 64


def test_scan_rejects_tampered_file_bytes(tmp_path) -> None:
    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("files/app/main.py", b"TAMPERED")
    with pytest.raises(PackageError, match="checksum mismatch"):
        scan_package(artifact)


def test_scan_rejects_extra_and_missing_entries(tmp_path) -> None:
    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("files/extra.txt", b"x")
    with pytest.raises(PackageError, match="do not match"):
        scan_package(artifact)

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("manifest.json", b"{}")
    with pytest.raises(PackageError, match="schema version"):
        scan_package(artifact)


def test_scan_rejects_symlink_and_unsafe_entries(tmp_path) -> None:
    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact, "a") as bundle:
        info = zipfile.ZipInfo("files/app/link.txt")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, b"target")
    with pytest.raises(PackageError, match="symbolic link"):
        scan_package(artifact)

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("files/../escape.txt", b"x")
    with pytest.raises(PackageError, match="unsafe"):
        scan_package(artifact)


def test_scan_rejects_manifest_algorithm_and_schema_changes(tmp_path) -> None:
    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
    manifest["algorithm"] = "md5"
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(PackageError, match="unsupported"):
        scan_package(artifact)


def test_scan_rejects_sbom_disagreement(tmp_path) -> None:
    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        sbom = json.loads(bundle.read("sbom.spdx.json"))
    sbom["packages"][0]["versionInfo"] = "9.9.9"
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("sbom.spdx.json", json.dumps(sbom))
    with pytest.raises(PackageError, match="disagrees"):
        scan_package(artifact)


def test_scan_rejects_sbom_file_checksum_tamper(tmp_path) -> None:
    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        sbom = json.loads(bundle.read("sbom.spdx.json"))
    sbom["files"][0]["checksums"][0]["checksumValue"] = "0" * 64
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("sbom.spdx.json", json.dumps(sbom))
    with pytest.raises(PackageError, match="checksum mismatch"):
        scan_package(artifact)


def test_build_rejects_symlinked_staging_source(tmp_path) -> None:
    source = staging(tmp_path, **{"app/main.py": b"x"})
    (source / "app" / "link").symlink_to(source / "app" / "main.py")
    with pytest.raises(PackageError, match="symbolic link"):
        build_package(
            source,
            tmp_path / "bad.mrpkg",
            name="backend",
            version=PackageVersion(1, 0, 0),
            platform=PLATFORM,
        )


def test_extract_package_materializes_verified_contents(tmp_path) -> None:
    artifact = build(tmp_path)
    manifest, contents = scan_package(artifact)
    destination = tmp_path / "installed"
    extract_package(manifest, contents, destination)
    assert (destination / "app" / "main.py").read_bytes() == b"import morpheus"
    assert (destination / "app" / "conf.json").read_bytes() == b"{}"
    with pytest.raises(PackageError, match="already exists"):
        extract_package(manifest, contents, destination)


def test_manifest_schema_and_algorithm_constants() -> None:
    assert PACKAGE_SCHEMA_VERSION == 1
    assert DIGEST_ALGORITHM == "sha256"
