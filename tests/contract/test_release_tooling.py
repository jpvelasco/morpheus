from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "validation/tools/images.lock.json"
REQUIRED_TOOLS = {
    "node",
    "playwright",
    "accessibility",
    "secret-scan",
    "vulnerability-scan",
    "sbom",
    "license-scan",
    "load-test",
}


def test_TOOL_001_every_release_tool_is_immutable_licensed_and_amd64() -> None:
    lock = json.loads(LOCK.read_text())
    assert lock["format"] == 1
    assert lock["platform"] == "linux/amd64"
    tools = {item["id"]: item for item in lock["tools"]}
    assert set(tools) == REQUIRED_TOOLS
    for name, tool in tools.items():
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", tool["index_digest"]), name
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", tool["platform_digest"]), name
        assert tool["reference"] == f"{tool['image']}@{tool['platform_digest']}", name
        assert tool["platform"] == "linux/amd64", name
        assert tool["version"] and tool["version"] != "latest", name
        assert tool["license"] and tool["license"] != "unknown", name
        assert tool["source"].startswith("https://github.com/"), name


def test_TOOL_001_accessibility_package_and_playwright_versions_are_locked() -> None:
    lock = json.loads(LOCK.read_text())
    tools = {item["id"]: item for item in lock["tools"]}
    package_lock = json.loads((ROOT / "web/package-lock.json").read_text())
    packages = package_lock["packages"]

    accessibility = tools["accessibility"]
    axe = packages["node_modules/@axe-core/playwright"]
    assert accessibility["package"] == "@axe-core/playwright"
    assert accessibility["version"] == axe["version"]
    assert accessibility["package_integrity"] == axe["integrity"]
    assert accessibility["license"] == axe["license"]
    assert accessibility["reference"] == tools["playwright"]["reference"]
    assert tools["playwright"]["version"] == packages["node_modules/@playwright/test"]["version"]


def test_TOOL_001_node_index_digest_matches_all_frontend_build_inputs() -> None:
    tools = {item["id"]: item for item in json.loads(LOCK.read_text())["tools"]}
    expected = tools["node"]["index_digest"]
    assert expected in (ROOT / "web/Dockerfile").read_text()
    assert expected in (ROOT / ".github/workflows/quality.yml").read_text()
