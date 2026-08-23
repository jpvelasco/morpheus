"""Architectural contract: exactly one canonical identity family (RUNM-001, AUD-001).

These checks encode the R1 exit criteria as executable rules so a competing
identity family cannot return quietly:

- exactly one semantic ``DeploymentPlan``, ``ModelIdentity``, and
  ``WorkloadProfile`` class exists under ``src/morpheus``;
- the retired lean-plan family (``ManagedCandidate``, derived ``plan_id``
  properties) stays retired;
- content-derived IDs never read the wall clock or observation timestamps.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "morpheus"


def _python_sources() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _classes_named(name: str) -> list[str]:
    found: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                found.append(path.relative_to(SRC).as_posix())
    return found


def test_exactly_one_deployment_plan_class_exists() -> None:
    definitions = _classes_named("DeploymentPlan")
    assert definitions == ["core/records.py"], definitions


def test_exactly_one_model_identity_and_workload_profile_exist() -> None:
    assert _classes_named("ModelIdentity") == ["core/records.py"]
    assert _classes_named("WorkloadProfile") == ["core/records.py"]


def test_retired_lean_plan_family_stays_retired() -> None:
    assert _classes_named("ManagedCandidate") == []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "plan_id":
                raise AssertionError(
                    f"{path.relative_to(SRC)}:{node.lineno} defines a derived plan_id; "
                    "plan identity is an explicit field of records.DeploymentPlan"
                )


def test_campaign_identity_never_reads_the_wall_clock() -> None:
    source = (SRC / "core" / "campaign.py").read_text(encoding="utf-8")
    assert "time.time()" not in source
    assert 'run_id or f"campaign-' not in source
    signature = re.search(r"def run_campaign\(.*?\)\s*->", source, re.DOTALL)
    assert signature is not None
    assert "run_id: str,\n" in signature.group(0)


def test_recommendation_identity_excludes_observation_timestamps() -> None:
    source = (SRC / "core" / "recommendation.py").read_text(encoding="utf-8")
    assert "def identity_dict" in source, (
        "recommendation records must derive their id from timestamp-free content"
    )
    # The v1 -> v2 migration recomputes the id without created_at/record_id.
    migration = re.search(r"def _migrate_v1_to_v2.*?(?=\ndef |\nclass )", source, re.DOTALL)
    assert migration is not None
    body = migration.group(0)
    assert '"created_at"' in body and '"record_id"' in body


def test_planning_service_is_the_only_selection_owner() -> None:
    harness = (ROOT / "validation" / "vslice" / "harness.py").read_text(encoding="utf-8")
    assert "PlanningService(" in harness, "the VSLICE fixture must use the production service"
    assert 'recommendation_id="recommendation-' not in harness
