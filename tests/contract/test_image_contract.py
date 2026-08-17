"""Contract tests: shipped ComfyUI fixture stays Morpheus-owned (IMG-001)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from morpheus.core.image_paths import (
    validate_owned_image_paths,
    verify_workflow_references,
)

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = json.loads(
    (ROOT / "tests/fixtures/comfy-smoke-workflow.json").read_text(encoding="utf-8")
)


def test_IMG_001_shipped_workflow_has_only_safe_references() -> None:
    decision = verify_workflow_references(WORKFLOW)
    assert decision.accepted is True
    assert decision.reasons == ()


def test_IMG_001_default_owned_roots_live_under_data_dir(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    decision = validate_owned_image_paths(
        models_root=data_root / "comfy" / "models",
        inputs_root=data_root / "comfy" / "inputs",
        outputs_root=data_root / "comfy" / "outputs",
        workflows_root=data_root / "comfy" / "workflows",
        morpheus_data_root=data_root,
    )
    assert decision.accepted is True


def test_IMG_001_external_model_root_is_rejected(tmp_path: Path) -> None:
    decision = validate_owned_image_paths(
        models_root=tmp_path / "comfy" / "models",
        inputs_root=tmp_path / "data" / "comfy" / "inputs",
        outputs_root=tmp_path / "data" / "comfy" / "outputs",
        workflows_root=tmp_path / "data" / "comfy" / "workflows",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert any("models" in reason for reason in decision.reasons)
