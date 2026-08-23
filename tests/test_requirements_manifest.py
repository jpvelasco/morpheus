from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT = re.compile(r"\*\*([A-Z]+-[0-9]{3}) [^*]+\.\*\*")
REQUIRED_FIELDS = {
    "id",
    "boundaries",
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
BOUNDARY_KINDS = {"api", "cli", "agent", "browser", "desktop", "end_to_end"}
PUBLIC_LANES = (
    "tests/contract/",
    "tests/integration/",
    "tests/acceptance/",
    "tests/e2e/",
    "web/tests/",
    "web/e2e/",
)
OWNERSHIP_METADATA = "MORPHEUS_OWNED_REQUIREMENTS"


def _owns_requirement(test_path: str, requirement_id: str) -> bool:
    source = (ROOT / test_path).read_text(encoding="utf-8")
    if OWNERSHIP_METADATA in source and re.search(
        rf"{OWNERSHIP_METADATA}\s*[:=][^\n]*\b{re.escape(requirement_id)}\b", source
    ):
        return True
    underscored = requirement_id.replace("-", "_")
    return re.search(rf"def\s+test_\w*{underscored}(?!\d)", source) is not None


def _is_public_boundary(item: dict) -> bool:
    return bool(set(item["boundaries"]) & BOUNDARY_KINDS)


def test_manifest_covers_every_product_requirement_once() -> None:
    specification = (ROOT / "docs/PRODUCT_SPECIFICATION.md").read_text(encoding="utf-8")
    expected = set(REQUIREMENT.findall(specification))
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    ids = [item["id"] for item in manifest["requirements"]]

    assert len(ids) == len(set(ids))
    assert set(ids) == expected


def test_manifest_references_known_delivery_phases() -> None:
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    assert all(0 <= item["phase"] <= 18 for item in manifest["requirements"])
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
            assert test_path.startswith(("tests/", "web/tests/", "web/e2e/")), item["id"]
            assert (ROOT / test_path).is_file(), f"{item['id']}: {test_path}"
        assert set(item["boundaries"]) <= BOUNDARY_KINDS, item["id"]


def test_TRACE_001_implemented_rows_have_semantic_ownership() -> None:
    """An owning test must name the requirement in a test function or explicit metadata.

    File existence alone proves nothing about behavior (AUD-007): a row counts as
    implemented only when at least one owning test embeds the exact requirement ID
    in a ``def test_*`` name or declares it through ``MORPHEUS_OWNED_REQUIREMENTS``.
    """
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    shallow = []
    for item in manifest["requirements"]:
        if item["status"] not in {"implemented", "validated"}:
            continue
        if not any(_owns_requirement(path, item["id"]) for path in item["owning_tests"]):
            shallow.append(item["id"])
    assert shallow == [], (
        "implemented rows without semantic test ownership "
        f"(add MORPHEUS_OWNED_REQUIREMENTS metadata or rename the owning test): {shallow}"
    )


def test_TRACE_001_public_boundary_rows_have_public_lane_owner() -> None:
    """API/CLI/browser/desktop/agent behavior needs an owner outside tests/unit."""
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    violations = []
    for item in manifest["requirements"]:
        if item["status"] not in {"implemented", "validated"}:
            continue
        if not _is_public_boundary(item):
            continue
        public_owners = [path for path in item["owning_tests"] if path.startswith(PUBLIC_LANES)]
        if not public_owners:
            violations.append(f"{item['id']}: boundaries={item['boundaries']}")
    assert violations == [], (
        "public-boundary rows without any contract/integration/acceptance/e2e/web owner: "
        f"{violations}"
    )


def test_TRACE_001_status_claims_require_implementation_and_green_evidence() -> None:
    manifest = json.loads((ROOT / "requirements.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    for item in manifest["requirements"]:
        if item["status"] == "planned":
            assert item["implementation_tasks"], item["id"]
            assert item["first_satisfying_version"] is None, item["id"]
        elif item["status"] == "deferred":
            assert item["first_satisfying_version"] is None, item["id"]
            assert item["implementation_tasks"] == [], item["id"]
        else:
            assert item["owning_tests"], item["id"]
            assert item["implementation_tasks"] == [], item["id"]
            first_version = item["first_satisfying_version"]
            assert isinstance(first_version, str), item["id"]
            assert tuple(map(int, first_version.split("."))) <= tuple(
                map(int, version.split("."))
            ), item["id"]

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
