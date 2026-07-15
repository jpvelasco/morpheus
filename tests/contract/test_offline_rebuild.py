from __future__ import annotations

import hashlib
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
COMPARE = ROOT / "validation/candidate/compare-rebuilds.sh"
BACKEND_DOCKERFILE = ROOT / "validation/candidate/Dockerfile.backend"
DASHBOARD_DOCKERFILE = ROOT / "validation/candidate/Dockerfile.dashboard"
CANDIDATE_COMPOSE = ROOT / "validation/candidate/compose.yaml"
AGENT_INSTALLER = ROOT / "deploy/agent/install.sh"


def test_CLEAN_002_scripts_are_executable_and_parse_as_bash() -> None:
    for script in (OFFLINE_GUARD, POPULATE, REBUILD, COMPARE, AGENT_INSTALLER):
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
    assert ".venv/bin/python -m pip download" in populate
    assert "agent-wheelhouse" in populate
    assert '"${python_reference}"' in populate
    assert "uv run --offline python -m pip download" not in populate
    assert "--no-cache-dir" in populate
    assert "--require-hashes" in populate
    assert "--only-binary=:all:" in populate
    assert "--no-header" in populate
    assert "npm ci --ignore-scripts --cache /npm-cache" in populate
    assert 'cache_scope: "portable-locked-dependencies-and-local-base-images"' in populate
    assert 'list table inet "${offline_table}"' in rebuild
    assert "uv build --offline" in rebuild
    assert "runtime_requirements_sha256" in populate
    assert "runtime_requirements_sha256" in rebuild
    assert "agent_wheelhouse_sha256" in populate
    assert "agent_wheelhouse_sha256" in rebuild
    assert 'rm -f "${output}/payload/python/.gitignore"' in rebuild
    assert rebuild.count("docker buildx build") == 2
    assert "rewrite-timestamp=true" in rebuild
    assert "--pull=false" in rebuild
    assert "--network=none" in rebuild
    assert "--no-cache" in rebuild
    assert "Dockerfile.backend" in rebuild
    assert "Dockerfile.dashboard" in rebuild
    assert '--tag "${backend_tag}"' in rebuild
    assert '--tag "${dashboard_tag}"' in rebuild
    assert "morpheus-agent-" in rebuild
    assert "gzip -n" in rebuild


def test_BUILD_001_comparator_requires_exact_artifact_identity() -> None:
    compare = COMPARE.read_text(encoding="utf-8")
    assert "sha256sum --check SHA256SUMS" in compare
    assert 'cmp "${first}/SHA256SUMS" "${second}/SHA256SUMS"' in compare
    assert 'cmp "${first}/${path}" "${second}/${path}"' in compare
    assert 'comparison: "byte-for-byte"' in compare


def test_ART_001_agent_bundle_installer_is_offline_verified_and_atomic() -> None:
    installer = AGENT_INSTALLER.read_text(encoding="utf-8")
    for required in (
        "sha256sum --check SHA256SUMS",
        "--no-index",
        "--require-hashes",
        "--no-deps",
        "pip check",
        "mktemp -d",
        "MORPHEUS_AGENT_PYTHON",
        "Runtime agent requires CPython 3.12",
        "content.replace(staging, destination)",
        'mv --no-clobber --no-target-directory -- "${temporary}" "${destination}"',
    ):
        assert required in installer
    assert "curl" not in installer
    assert "wget" not in installer


def test_BUILD_001_comparator_proves_equal_rebuilds(tmp_path: Path) -> None:
    rebuilds = [tmp_path / "first", tmp_path / "second"]
    paths = [
        "payload/agent/morpheus-agent.tar.gz",
        "payload/images/backend.oci.tar",
        "payload/images/dashboard.oci.tar",
        "payload/python/morpheus.whl",
        "payload/python/morpheus.tar.gz",
    ]
    for rebuild in rebuilds:
        checksums: list[str] = []
        for index, relative in enumerate(paths):
            artifact = rebuild / relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            content = f"artifact-{index}".encode()
            artifact.write_bytes(content)
            checksums.append(f"{hashlib.sha256(content).hexdigest()}  {relative}\n")
        (rebuild / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
        (rebuild / "offline-rebuild.json").write_text(
            json.dumps(
                {
                    "format": 1,
                    "source_commit": "a" * 40,
                    "source_date_epoch": 1_784_147_805,
                    "version": "0.1.0",
                }
            ),
            encoding="utf-8",
        )

    result = tmp_path / "comparison.json"
    subprocess.run(  # noqa: S603 - fixed checked-in script path
        [COMPARE, rebuilds[0], rebuilds[1], result], check=True
    )
    comparison = json.loads(result.read_text(encoding="utf-8"))
    assert comparison["status"] == "pass"
    assert comparison["artifact_count"] == 5
    assert [artifact["path"] for artifact in comparison["artifacts"]] == paths


def test_BUILD_001_candidate_dockerfiles_are_offline_pinned_and_normalized() -> None:
    backend = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    dashboard = DASHBOARD_DOCKERFILE.read_text(encoding="utf-8")
    for dockerfile in (backend, dashboard):
        assert "python:3.12-alpine3.23@sha256:601d3d37" in dockerfile
        assert "sha256sum -c SHA256SUMS" in dockerfile
        assert "--no-index" in dockerfile
        assert "--find-links=/wheelhouse" in dockerfile
        assert 'touch -h -d "@${SOURCE_DATE_EPOCH}"' in dockerfile
        assert "addgroup -S morpheus" in dockerfile
        assert "adduser -S -D -H -G morpheus morpheus" in dockerfile
        assert "org.opencontainers.image.revision" in dockerfile
        assert "HEALTHCHECK" in dockerfile
        assert "USER morpheus" in dockerfile
        assert "curl" not in dockerfile
        assert "wget" not in dockerfile
    assert "node:22.17.1-alpine3.22@sha256:99351363" in dashboard
    assert "npm ci --offline --ignore-scripts" in dashboard
    assert "install -d -o morpheus -g morpheus -m 0750 /var/lib/morpheus" in backend


def test_CONT_002_compose_overlay_uses_exported_candidate_images() -> None:
    compose = CANDIDATE_COMPOSE.read_text(encoding="utf-8")
    assert compose.count("${MORPHEUS_BACKEND_IMAGE:") == 2
    assert compose.count("${MORPHEUS_DASHBOARD_IMAGE:") == 1
    assert "build:" not in compose


def test_ART_001_oci_producers_name_the_fetch_and_offline_steps() -> None:
    definition = json.loads(
        (ROOT / "validation/candidate/artifact-set.json").read_text(encoding="utf-8")
    )
    artifacts = {item["id"]: item for item in definition["artifacts"]}
    expected_fetch = [
        "validation/candidate/populate-cache.sh",
        "{cache-evidence-directory}",
    ]
    for artifact_id in ("backend-oci", "dashboard-oci", "runtime-agent-bundle"):
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
