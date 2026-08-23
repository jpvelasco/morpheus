from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^]]+]\(([^)]+)\)")

CURRENT_STATE_DOCS = (
    "README.md",
    "AGENTS.md",
    "docs/RELEASE_STATE.md",
    "docs/IMPLEMENTATION_GAP_REVIEW.md",
)

# Historical inputs classified by docs/RECTIFICATION_PLAN.md section 6 (R0):
# their stale claims are preserved as history and are exempt from current-state checks.
HISTORICAL_DOCS = (
    "docs/IMPLEMENTATION_AUDIT_2026-08-15.md",
    "docs/VERTICAL_SLICE_ASSESSMENT.md",
    "docs/OPENCODE_IMPLEMENTATION_BOOTSTRAP.md",
)

BANNED_CURRENT_CLAIMS = (
    "97 implemented",
    "97 complete",
    "all 97 requirements",
    "0 planned, 0 deferred",
    "Phase 11.5 next",
    "Phase 18 next",
)


def test_local_documentation_links_resolve() -> None:
    missing: list[str] = []
    for document in sorted(ROOT.rglob("*.md")):
        relative_document = document.relative_to(ROOT)
        if {".git", ".venv", "node_modules"}.intersection(relative_document.parts):
            continue
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (document.parent / relative).resolve().exists():
                missing.append(f"{relative_document} -> {target}")
    assert missing == []


def _requirement_counts() -> dict[str, int]:
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    counts = {"implemented": 0, "planned": 0, "deferred": 0, "validated": 0}
    for item in manifest["requirements"]:
        counts[item["status"]] += 1
    return counts


def test_current_state_documents_agree_with_requirement_counts() -> None:
    """Count claims in current-state documents must be derived, never hand-written drift."""
    counts = _requirement_counts()
    stale: list[str] = []
    pattern = re.compile(r"\b(\d+) (implemented|planned|deferred|validated)\b")
    for name in CURRENT_STATE_DOCS:
        for number, status in pattern.findall((ROOT / name).read_text(encoding="utf-8")):
            if int(number) != counts[status]:
                stale.append(f"{name}: claims {number} {status}")
    assert stale == [], f"count drift vs requirements.json ({counts}): {stale}"


def test_current_state_documents_have_single_active_plan_and_no_stale_claims() -> None:
    missing_pointer = [
        name
        for name in CURRENT_STATE_DOCS
        if "RECTIFICATION_PLAN.md" not in (ROOT / name).read_text(encoding="utf-8")
    ]
    assert missing_pointer == [], f"no active-plan pointer: {missing_pointer}"

    banned: list[str] = []
    for name in CURRENT_STATE_DOCS:
        text = (ROOT / name).read_text(encoding="utf-8")
        for phrase in BANNED_CURRENT_CLAIMS:
            if phrase in text:
                banned.append(f"{name}: {phrase!r}")
    assert banned == [], f"stale completion claims: {banned}"
