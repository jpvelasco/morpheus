from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from morpheus.ops.support import SupportBundleBuilder

pytestmark = pytest.mark.integration


def test_OPS_003_support_bundle_contains_safe_evidence_without_canaries(tmp_path: Path) -> None:
    destination = tmp_path / "support.zip"
    SupportBundleBuilder().build(
        destination,
        version="0.1.0",
        configuration={
            "llm_base_url": "http://llm:8000/v1",
            "api_key": "secret-key-canary",
            "nested": {"sessionSecret": "session-secret-canary"},
        },
        health={"state": "degraded", "reason_code": "search_unreachable"},
        errors=[
            {
                "code": "dependency_unavailable",
                "safe_summary": "Search is unavailable",
                "raw_detail": "private-prompt-content-canary",
            }
        ],
    )
    with zipfile.ZipFile(destination) as bundle:
        assert set(bundle.namelist()) == {
            "configuration.json",
            "errors.json",
            "health.json",
            "manifest.json",
        }
        combined = b"".join(bundle.read(name) for name in bundle.namelist()).decode()
        assert "secret-key-canary" not in combined
        assert "session-secret-canary" not in combined
        assert "private-prompt-content-canary" not in combined
        assert "Search is unavailable" in combined
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["version"] == "0.1.0"


def test_OPS_003_bundle_write_is_atomic(tmp_path: Path) -> None:
    destination = tmp_path / "support.zip"
    SupportBundleBuilder().build(
        destination,
        version="0.1.0",
        configuration={},
        health={},
        errors=[],
    )
    assert destination.is_file()
    assert not (tmp_path / ".support.zip.tmp").exists()
