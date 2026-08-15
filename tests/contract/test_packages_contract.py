"""Contract gates: versioned backend package integrity, scanning, and SBOM (PLAT-003)."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

from morpheus.core.packages import (
    PackageError,
    PackageManifest,
    PackageVersion,
    build_package,
    package_digest,
    package_file_name,
    scan_package,
)

pytestmark = pytest.mark.contract
PLATFORM = "linux-x86_64"


def build(tmp_path: Path, *, version: str = "1.0.0", extra: dict[str, bytes] | None = None) -> Path:
    source = tmp_path / "staging"
    source.mkdir(exist_ok=True)
    files = {"app/main.py": b"def main():\n    return 1\n", "conf/default.json": b'{"x": 1}'}
    files.update(extra or {})
    for relative, data in files.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    destination = tmp_path / "artifacts"
    destination.mkdir(exist_ok=True)
    parsed = PackageVersion.parse(version)
    return build_package(
        source,
        destination / package_file_name("backend", parsed, PLATFORM),
        name="backend",
        version=parsed,
        platform=PLATFORM,
    )


def replace_zip_entry(artifact: Path, entry: str, data: bytes) -> None:
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr(entry, data)


def test_manifest_gate_integrity_corpus(tmp_path) -> None:
    """Manifest gate: the scan verdict must be 'verified' exactly for genuine artifacts."""
    for version in ("1.0.0", "1.0.1", "2.3.4"):
        manifest, contents = scan_package(build(tmp_path, version=version))
        assert manifest.version == PackageVersion.parse(version)
        assert set(contents) == {"app/main.py", "conf/default.json"}
    with pytest.raises(PackageError, match="unsafe package path"):
        build(tmp_path, version="1.0.0", extra={"bad name.txt": b"x"})


def test_scan_gate_rejects_each_tamper_class(tmp_path) -> None:
    """Scan gate: every tamper class must be rejected with an actionable error."""
    artifact = build(tmp_path)
    replace_zip_entry(artifact, "files/app/main.py", b"tampered")
    with pytest.raises(PackageError, match="checksum mismatch"):
        scan_package(artifact)

    artifact = build(tmp_path)
    replace_zip_entry(artifact, "files/extra.bin", b"x")
    with pytest.raises(PackageError, match="do not match"):
        scan_package(artifact)

    artifact = build(tmp_path)
    replace_zip_entry(artifact, "files/../escape.bin", b"x")
    with pytest.raises(PackageError, match="unsafe"):
        scan_package(artifact)

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact, "a") as bundle:
        info = zipfile.ZipInfo("files/app/link.txt")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, b"main.py")
    with pytest.raises(PackageError, match="symbolic link"):
        scan_package(artifact)

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
    manifest["version"] = "1.0.1"
    replace_zip_entry(artifact, "manifest.json", json.dumps(manifest).encode())
    with pytest.raises(PackageError, match="disagrees"):
        scan_package(artifact)

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
    manifest["algorithm"] = "md5"
    replace_zip_entry(artifact, "manifest.json", json.dumps(manifest).encode())
    with pytest.raises(PackageError, match="unsupported"):
        scan_package(artifact)

    artifact = build(tmp_path)
    replace_zip_entry(artifact, "manifest.json", b"{}")
    with pytest.raises(PackageError, match="schema version"):
        scan_package(artifact)


def test_sbom_gate_lists_exactly_the_verified_files(tmp_path) -> None:
    """SBOM gate: the SBOM must name every file and agree on every checksum."""
    artifact = build(tmp_path)
    manifest, _ = scan_package(artifact)
    with zipfile.ZipFile(artifact) as bundle:
        sbom = json.loads(bundle.read("sbom.spdx.json"))
    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert sbom["name"] == "backend-1.0.0"
    assert sbom["packages"][0]["versionInfo"] == "1.0.0"
    assert sbom["documentDescribes"] == ["SPDXRef-Package-backend-1.0.0"]
    sbom_files = {
        entry["fileName"]: entry["checksums"][0]["checksumValue"] for entry in sbom["files"]
    }
    assert set(sbom_files) == set(dict(manifest.files))
    assert all(sbom_files[name] == digest for name, digest in manifest.files)
    relationships = {rel["relatedSpdxElement"] for rel in sbom["relationships"]}
    assert relationships == {f"SPDXRef-File-{index}" for index in range(len(sbom["files"]))}
    assert {rel["spdxElementId"] for rel in sbom["relationships"]} == {
        "SPDXRef-Package-backend-1.0.0"
    }
    assert {rel["relationshipType"] for rel in sbom["relationships"]} == {"CONTAINS"}

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        sbom = json.loads(bundle.read("sbom.spdx.json"))
    sbom["files"][0]["checksums"][0]["checksumValue"] = "0" * 64
    replace_zip_entry(artifact, "sbom.spdx.json", json.dumps(sbom).encode())
    with pytest.raises(PackageError, match="checksum mismatch"):
        scan_package(artifact)

    artifact = build(tmp_path)
    with zipfile.ZipFile(artifact) as bundle:
        sbom = json.loads(bundle.read("sbom.spdx.json"))
    sbom["packages"][0]["name"] = "other-package"
    replace_zip_entry(artifact, "sbom.spdx.json", json.dumps(sbom).encode())
    with pytest.raises(PackageError, match="disagrees"):
        scan_package(artifact)


def test_packages_are_independent_and_reproducible(tmp_path) -> None:
    """Independent packaging: two versions are distinct artifacts with stable file digests."""
    one = build(tmp_path, version="1.0.0")
    two = build(tmp_path, version="1.1.0")
    assert one != two
    assert package_digest(one) != package_digest(two)
    manifest_one, _ = scan_package(one)
    manifest_two, _ = scan_package(two)
    assert manifest_one.to_json()["files"] == manifest_two.to_json()["files"]
    rebuilt = build(tmp_path, version="1.0.0")
    assert scan_package(rebuilt)[0].to_json()["files"] == manifest_one.to_json()["files"]


def test_manifest_json_round_trip_is_lossless(tmp_path) -> None:
    """Manifest gate: JSON round trip must preserve every field exactly."""
    manifest, _ = scan_package(build(tmp_path))
    assert PackageManifest.from_json(manifest.to_json()) == manifest
    with pytest.raises(PackageError, match="schema version"):
        PackageManifest.from_json({"schema_version": 2})
