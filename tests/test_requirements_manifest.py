from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT = re.compile(r"\*\*([A-Z]+-[0-9]{3}) [^*]+\.\*\*")
REQUIRED_FIELDS = {
    "id",
    "phase",
    "status",
    "owning_tests",
    "risk",
    "required_environments",
    "requires_live_evidence",
    "requires_hardware_evidence",
    "first_satisfying_version",
    "evidence_manifests",
    "implementation_tasks",
}


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


def test_TRACE_001_every_requirement_has_actionable_validation_metadata() -> None:
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    for item in manifest["requirements"]:
        assert set(item) == REQUIRED_FIELDS, item["id"]
        assert item["risk"] in {"low", "medium", "high", "critical"}, item["id"]
        assert item["required_environments"], item["id"]
        assert set(item["required_environments"]) <= {
            "DEV",
            "VM",
            "HOST-RO",
            "HOST-MAINT",
        }, item["id"]
        assert isinstance(item["requires_live_evidence"], bool), item["id"]
        assert isinstance(item["requires_hardware_evidence"], bool), item["id"]
        assert isinstance(item["owning_tests"], list), item["id"]
        assert isinstance(item["evidence_manifests"], list), item["id"]
        assert isinstance(item["implementation_tasks"], list), item["id"]
        for test_path in item["owning_tests"]:
            assert test_path.startswith(("tests/", "web/tests/")), item["id"]
            assert (ROOT / test_path).is_file(), f"{item['id']}: {test_path}"


def test_TRACE_001_status_claims_require_implementation_and_green_evidence() -> None:
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    for item in manifest["requirements"]:
        if item["status"] == "planned":
            assert item["implementation_tasks"], item["id"]
            assert item["first_satisfying_version"] is None, item["id"]
        elif item["status"] == "deferred":
            assert item["first_satisfying_version"] is None, item["id"]
        else:
            assert item["owning_tests"], item["id"]
            assert item["implementation_tasks"] == [], item["id"]
            assert item["first_satisfying_version"] == version, item["id"]

        if item["status"] != "validated":
            assert item["evidence_manifests"] == [], item["id"]
            continue
        assert item["evidence_manifests"], item["id"]
        for relative in item["evidence_manifests"]:
            evidence_path = (ROOT / relative).resolve()
            evidence_root = (ROOT / "artifacts/release-validation").resolve()
            assert evidence_path.is_relative_to(evidence_root), item["id"]
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            assert evidence["status"] == "pass", item["id"]
            assert item["id"] in evidence["requirement_ids"], item["id"]
