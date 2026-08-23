from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from _posix_tools import NEEDS_USABLE_BASH, USABLE_BASH

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"SEC-005"})
pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "validation" / "security" / "run.sh"
FINALIZER = ROOT / "validation" / "security" / "finalize.py"
CACHE_BUILDER = ROOT / "validation" / "security" / "populate-cache.sh"
POLICY = ROOT / "validation" / "security" / "policy.json"
MANIFEST_SCHEMA = ROOT / "validation" / "security" / "manifest.schema.json"
LICENSE_SCHEMA = ROOT / "validation" / "security" / "license-review.schema.json"


def test_SEC_005_policy_blocks_required_findings_and_covers_every_scan_scope() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["format"] == 1
    assert policy["blocked_severities"] == ["HIGH", "CRITICAL"]
    assert policy["sbom_formats"] == ["cyclonedx-json", "spdx-json"]
    assert set(policy["required_scans"]) == {
        "gitleaks-history",
        "gitleaks-worktree",
        "gitleaks-candidate-artifacts",
        "repository-filesystem-security",
        "repository-filesystem-license",
        "candidate-artifacts-security",
        "candidate-artifacts-license",
        "backend-oci-security",
        "backend-oci-license",
        "dashboard-oci-security",
        "dashboard-oci-license",
    }
    assert policy["forbidden_licenses"]


@NEEDS_USABLE_BASH
def test_SEC_005_runner_is_offline_hardened_pinned_and_release_blocking() -> None:
    bash = USABLE_BASH
    assert bash is not None
    subprocess.run([bash, "-n", RUNNER], check=True)  # noqa: S603 - fixed checked-in script
    source = RUNNER.read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    for tool_id in ("secret-scan", "vulnerability-scan", "sbom", "license-scan"):
        assert tool_id in source
    for hardening in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "no-new-privileges:true",
        "--user",
    ):
        assert hardening in source
    for blocker in (
        "--severity=HIGH,CRITICAL",
        "--exit-code=1",
        "--offline-scan",
        "--skip-db-update",
        "--skip-java-db-update",
        "--skip-check-update",
        "--skip-vex-repo-update",
    ):
        assert blocker in source
    assert "--ignore-unfixed" not in source
    assert "--redact=100" in source
    assert "--max-archive-depth=3" in source
    assert "cyclonedx-json=" in source
    assert "spdx-json=" in source
    assert "artifacts/" in source
    # OCI layout archives must be extracted before Trivy --input (not Docker-save).
    assert "oci_extract_root" in source
    assert "oci-layout" in source
    assert "index.json" in source
    assert "security-candidate-scan:" in makefile
    assert "security-release:" in makefile
    assert "release-gate: gate browser-gate security-release" in makefile


def test_SEC_005_finalizer_is_structured_and_never_emits_secret_values() -> None:
    source = FINALIZER.read_text(encoding="utf-8")
    compile(source, str(FINALIZER), "exec")

    assert "verify_supply_chain" in source
    assert "license-review.template.json" in source
    assert "supply-chain-manifest.json" in source
    assert "os.replace" in source
    assert "get_secret_value" not in source
    assert "security_manifest=passed" in source


@NEEDS_USABLE_BASH
def test_SEC_005_vulnerability_database_cache_is_inventoried_and_separate() -> None:
    bash = USABLE_BASH
    assert bash is not None
    subprocess.run(  # noqa: S603 - fixed checked-in script
        [bash, "-n", CACHE_BUILDER], check=True
    )
    source = CACHE_BUILDER.read_text(encoding="utf-8")

    assert "vulnerability-scan" in source
    assert "--download-db-only" in source
    assert "SHA256SUMS" in source
    assert "cache-manifest.json" in source
    assert "artifacts/" in source
    assert "--read-only" in source
    assert "--cap-drop=ALL" in source
    assert "no-new-privileges:true" in source
    assert "--network=none" not in source


def test_SEC_005_generated_manifest_and_human_review_have_closed_schemas() -> None:
    manifest = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    review = json.loads(LICENSE_SCHEMA.read_text(encoding="utf-8"))

    assert manifest["additionalProperties"] is False
    assert set(manifest["required"]) == {
        "format",
        "source_commit",
        "candidate_manifest_sha256",
        "tool_lock_sha256",
        "policy_sha256",
        "vulnerability_database",
        "tools",
        "scans",
        "sboms",
        "license_review",
        "result",
    }
    assert review["additionalProperties"] is False
    assert set(review["required"]) == {
        "format",
        "source_commit",
        "decision",
        "reviewer",
        "reviewed_at",
        "report_sha256s",
        "exceptions",
    }


def test_SEC_005_operator_workflow_separates_download_scan_review_and_finalize() -> None:
    readme = (ROOT / "validation" / "README.md").read_text(encoding="utf-8")

    for command in (
        "validation/security/populate-cache.sh",
        "validation/security/run.sh scan",
        "license-review.template.json",
        "validation/security/run.sh finalize",
        "make release-gate",
    ):
        assert command in readme
    assert "does not constitute candidate evidence" in " ".join(readme.split())
