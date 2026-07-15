from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT = re.compile(r"\*\*([A-Z]+-[0-9]{3}) [^*]+\.\*\*")


def test_manifest_covers_every_product_requirement_once() -> None:
    specification = (ROOT / "docs/PRODUCT_SPECIFICATION.md").read_text(encoding="utf-8")
    expected = set(REQUIREMENT.findall(specification))
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in manifest["requirements"]]

    assert len(ids) == len(set(ids))
    assert set(ids) == expected


def test_manifest_references_known_delivery_phases() -> None:
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    assert all(0 <= item["phase"] <= 10 for item in manifest["requirements"])
    assert all(
        item["status"] in {"planned", "implemented", "validated", "deferred"}
        for item in manifest["requirements"]
    )
