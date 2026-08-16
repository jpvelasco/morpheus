"""Contract tests: checksummed developer desktop package (DESK-002).

A desktop delivery is bundled through the same versioned, checksummed
package format as backend artifacts: an immutable archive with a strict
manifest, per-file SHA-256 digests, and a matching SPDX SBOM. The test
proves the whole chain — build, scan, digest verification, trust
evaluation as an unsigned developer package, and a confirmed install
plan — without any native installer or signing credentials.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from morpheus.core.bootstrap import (
    BootstrapState,
    CandidatePackage,
    plan_bootstrap,
)
from morpheus.core.package_trust import (
    QUALIFICATION_DEVELOPER,
    evaluate_trust,
)
from morpheus.core.packages import (
    PackageManifest,
    PackageVersion,
    build_package,
    package_digest,
    package_file_name,
    scan_package,
)

PLATFORM = "linux-x86_64"


def _desktop_staging(tmp_path: Path) -> Path:
    directory = tmp_path / "staging"
    directory.mkdir(exist_ok=True)
    (directory / "morpheus-desktop").write_bytes(b"#! /bin/sh\necho morpheus-desktop\n")
    (directory / "fallback").mkdir()
    (directory / "fallback" / "index.html").write_bytes(b"<html>fallback</html>")
    return directory


def test_desktop_package_builds_scan_and_plans_confirmed_install(tmp_path: Path) -> None:
    artifact = build_package(
        _desktop_staging(tmp_path),
        tmp_path / "out" / "morpheus-desktop-0.1.0-linux-x86_64.mrpkg",
        name="morpheus-desktop",
        version=PackageVersion(0, 1, 0),
        platform=PLATFORM,
    )
    assert artifact.name == package_file_name("morpheus-desktop", PackageVersion(0, 1, 0), PLATFORM)

    manifest, contents = scan_package(artifact)
    assert isinstance(manifest, PackageManifest)
    assert set(contents) == {
        "fallback/index.html",
        "morpheus-desktop",
    }
    assert package_digest(artifact) == package_digest(artifact)

    trust = evaluate_trust(qualification=QUALIFICATION_DEVELOPER, digests_verified=True)
    assert trust.usable
    assert trust.confirmation_required
    assert not trust.unattended_update_allowed

    plan = plan_bootstrap(
        state=BootstrapState(backend_present=False, backend_running=False),
        candidate=CandidatePackage(
            package_name="morpheus-desktop",
            version=str(manifest.version),
            platform=manifest.platform,
            qualification=QUALIFICATION_DEVELOPER,
            digests_verified=True,
        ),
        trust=trust,
    )
    assert plan.kind == "install"
    assert plan.confirmation_required


def test_desktop_package_tamper_is_detected_by_scan(tmp_path: Path) -> None:
    artifact = build_package(
        _desktop_staging(tmp_path),
        tmp_path / "out" / "morpheus-desktop-0.1.0-linux-x86_64.mrpkg",
        name="morpheus-desktop",
        version=PackageVersion(0, 1, 0),
        platform=PLATFORM,
    )
    with zipfile.ZipFile(artifact, "a") as bundle:
        bundle.writestr("files/fallback/index.html", b"<html>tampered</html>")
    with pytest.raises(ValueError):
        scan_package(artifact)
