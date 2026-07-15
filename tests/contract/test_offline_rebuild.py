from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
OFFLINE_GUARD = ROOT / "validation/vm/offline-egress.sh"
POPULATE = ROOT / "validation/candidate/populate-cache.sh"
REBUILD = ROOT / "validation/candidate/rebuild-offline.sh"
BACKEND_DOCKERFILE = ROOT / "validation/candidate/Dockerfile.backend"
DASHBOARD_DOCKERFILE = ROOT / "validation/candidate/Dockerfile.dashboard"


def test_CLEAN_002_scripts_are_executable_and_parse_as_bash() -> None:
    for script in (OFFLINE_GUARD, POPULATE, REBUILD):
        assert script.stat().st_mode & 0o111
        subprocess.run(  # noqa: S603 - fixed parser and checked-in script paths
            ["/usr/bin/bash", "-n", script], check=True
        )


def test_CLEAN_002_guard_proves_and_restores_guest_egress_isolation() -> None:
    script = OFFLINE_GUARD.read_text(encoding="utf-8")
    assert "egress_before=reachable" in script
    assert "egress_during=blocked" in script
    assert "policy drop" in script
    assert "trap cleanup EXIT" in script
    assert 'delete table inet "${table}"' in script
    assert "output ct state established,related accept" in script
    assert "forward ct state established,related accept" in script


def test_CLEAN_002_declares_one_fetch_then_requires_offline_rebuild() -> None:
    populate = POPULATE.read_text(encoding="utf-8")
    rebuild = REBUILD.read_text(encoding="utf-8")
    assert "uv sync --python 3.12 --extra dev --frozen" in populate
    assert 'export SOURCE_DATE_EPOCH="${source_date_epoch}"' in populate
    assert 'rm -f "${output}/python/.gitignore"' in populate
    assert populate.count("docker buildx build") == 0
    assert populate.count("docker pull") == 2
    assert "pip download" in populate
    assert "--require-hashes" in populate
    assert "--only-binary=:all:" in populate
    assert "npm ci --ignore-scripts --cache /npm-cache" in populate
    assert 'cache_scope: "portable-locked-dependencies-and-local-base-images"' in populate
    assert 'list table inet "${offline_table}"' in rebuild
    assert "uv build --offline" in rebuild
    assert 'rm -f "${output}/payload/python/.gitignore"' in rebuild
    assert rebuild.count("docker buildx build") == 2
    assert "rewrite-timestamp=true" in rebuild
    assert "--pull=false" in rebuild
    assert "--network=none" in rebuild
    assert "--no-cache" in rebuild
    assert "Dockerfile.backend" in rebuild
    assert "Dockerfile.dashboard" in rebuild


def test_BUILD_001_candidate_dockerfiles_are_offline_pinned_and_normalized() -> None:
    backend = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    dashboard = DASHBOARD_DOCKERFILE.read_text(encoding="utf-8")
    for dockerfile in (backend, dashboard):
        assert "python:3.12.11-slim@sha256:47ae396f" in dockerfile
        assert "sha256sum --check SHA256SUMS" in dockerfile
        assert "--no-index" in dockerfile
        assert "--find-links=/wheelhouse" in dockerfile
        assert 'touch -h --date="@${SOURCE_DATE_EPOCH}"' in dockerfile
        assert "org.opencontainers.image.revision" in dockerfile
        assert "HEALTHCHECK" in dockerfile
        assert "USER morpheus" in dockerfile
        assert "curl" not in dockerfile
        assert "wget" not in dockerfile
    assert "node:22.17.1-alpine3.22@sha256:99351363" in dashboard
    assert "npm ci --offline --ignore-scripts" in dashboard


def test_ART_001_oci_producers_name_the_fetch_and_offline_steps() -> None:
    definition = json.loads(
        (ROOT / "validation/candidate/artifact-set.json").read_text(encoding="utf-8")
    )
    artifacts = {item["id"]: item for item in definition["artifacts"]}
    expected_fetch = [
        "validation/candidate/populate-cache.sh",
        "{cache-evidence-directory}",
    ]
    for artifact_id in ("backend-oci", "dashboard-oci"):
        producer = artifacts[artifact_id]["producer"]
        assert producer["network"] is False
        assert producer["dependency_fetch"] == expected_fetch
        assert producer["command"][:2] == [
            "validation/vm/offline-egress.sh",
            "validation/candidate/rebuild-offline.sh",
        ]


def test_CLEAN_002_no_script_contains_shell_network_fetch_shortcuts() -> None:
    scripts = "\n".join(
        path.read_text(encoding="utf-8") for path in (OFFLINE_GUARD, POPULATE, REBUILD)
    )
    assert "curl |" not in scripts
    assert "wget" not in scripts
    assert os.path.commonpath([ROOT, OFFLINE_GUARD]) == str(ROOT)
