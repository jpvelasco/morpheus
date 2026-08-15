from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def test_BROW_001_browser_gate_is_version_matched_pinned_and_internal_only() -> None:
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "validation/tools/images.lock.json").read_text(encoding="utf-8"))
    playwright = next(tool for tool in lock["tools"] if tool["id"] == "playwright")
    runner = (ROOT / "validation/browser/run.sh").read_text(encoding="utf-8")

    assert package["devDependencies"]["@playwright/test"] == playwright["version"]
    assert package["devDependencies"]["@axe-core/playwright"] == "4.12.1"
    assert playwright["reference"] in runner or 'select(.id == "playwright")' in runner
    for hardening in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "no-new-privileges:true",
        "--user",
    ):
        assert hardening in runner


def test_BROW_001_playwright_policy_retains_failure_artifacts_under_ignored_output() -> None:
    config = (ROOT / "web/playwright.config.ts").read_text(encoding="utf-8")
    browser_test = (ROOT / "web/e2e/dashboard.spec.ts").read_text(encoding="utf-8")

    assert "retain-on-failure" in config
    assert "only-on-failure" in config
    assert "BROWSER_ARTIFACT_ROOT" in config
    assert "reuseExistingServer: false" in config
    assert "critical' || violation.impact === 'serious'" in browser_test
    assert "scrollWidth" in browser_test
    assert "reducedMotion: 'reduce'" in browser_test


def test_BROW_004_refreshes_are_cancelable_and_stale_responses_are_covered() -> None:
    app = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
    browser_test = (ROOT / "web/e2e/dashboard.spec.ts").read_text(encoding="utf-8")

    assert "new AbortController()" in app
    assert "overviewRequest.current?.abort()" in app
    assert "stale-response" in browser_test
    assert "latest-response" in browser_test


def test_BROW_006_runner_scans_plain_and_compressed_evidence_for_the_canary() -> None:
    runner = (ROOT / "validation/browser/run.sh").read_text(encoding="utf-8")
    scanner = (ROOT / "validation/browser/scan_evidence.py").read_text(encoding="utf-8")

    assert "scan_evidence.py" in runner
    assert "python3 /scan-evidence.py /artifacts" in runner
    assert "browser-test-key" in scanner
    assert "zipfile.ZipFile" in scanner
