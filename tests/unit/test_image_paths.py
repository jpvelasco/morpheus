"""Unit tests: Morpheus-owned ComfyUI paths and safe workflow references (IMG-001)."""

from __future__ import annotations

from pathlib import Path

import pytest

from morpheus.core.image_paths import (
    OwnedImagePaths,
    safe_workflow_reference,
    validate_owned_image_paths,
    verify_workflow_references,
)

OWNED = {
    "models_root": "images/models",
    "inputs_root": "images/inputs",
    "outputs_root": "images/outputs",
    "workflows_root": "images/workflows",
}


def test_validate_owned_image_paths_accepts_owned_roots(tmp_path: Path) -> None:
    decision = validate_owned_image_paths(
        models_root=tmp_path / "data" / "images" / "models",
        inputs_root=tmp_path / "data" / "images" / "inputs",
        outputs_root=tmp_path / "data" / "images" / "outputs",
        workflows_root=tmp_path / "data" / "images" / "workflows",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is True
    assert decision.reasons == ()


def test_validate_owned_image_paths_rejects_external_roots(tmp_path: Path) -> None:
    decision = validate_owned_image_paths(
        models_root=tmp_path / "comfy" / "models",
        inputs_root=tmp_path / "data" / "images" / "inputs",
        outputs_root=tmp_path / "data" / "images" / "outputs",
        workflows_root=tmp_path / "data" / "images" / "workflows",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert any("models" in reason for reason in decision.reasons)
    assert decision.blockers == decision.reasons


def test_validate_owned_image_paths_rejects_all_external_roots(tmp_path: Path) -> None:
    decision = validate_owned_image_paths(
        models_root=tmp_path / "outside" / "models",
        inputs_root=tmp_path / "outside" / "inputs",
        outputs_root=tmp_path / "outside" / "outputs",
        workflows_root=tmp_path / "outside" / "workflows",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert len([r for r in decision.reasons if "must be" in r]) == 4


def test_validate_owned_image_paths_resolves_relative_roots(tmp_path: Path) -> None:
    decision = validate_owned_image_paths(
        models_root="images/models",
        inputs_root="images/inputs",
        outputs_root="images/outputs",
        workflows_root="images/workflows",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is True


def test_owned_image_paths_declaration_is_frozen(tmp_path: Path) -> None:
    declaration = OwnedImagePaths(
        models_root=tmp_path / "models",
        inputs_root=tmp_path / "inputs",
        outputs_root=tmp_path / "outputs",
        workflows_root=tmp_path / "workflows",
    )
    with pytest.raises(AttributeError):
        declaration.models_root = tmp_path  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        "smoke.png",
        "sub/dir/image.png",
        "workflows/smoke.json",
        "checkpoints/model.safetensors",
    ],
)
def test_safe_workflow_reference_accepts_relative_paths(value: str) -> None:
    assert safe_workflow_reference(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "/absolute/path.png",
        "../escape.png",
        "a/../../escape.png",
        "",
        "bad\x00name.png",
        "C:\\windows\\path.png",
    ],
)
def test_safe_workflow_reference_rejects_unsafe_paths(value: str) -> None:
    assert safe_workflow_reference(value) is False


def test_verify_workflow_references_accepts_owned_workflow() -> None:
    workflow = {
        "5": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "checkpoints/owned-model.safetensors"},
        },
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "owned/output"}},
    }
    decision = verify_workflow_references(workflow)
    assert decision.accepted is True
    assert decision.reasons == ()


def test_verify_workflow_references_rejects_absolute_escape() -> None:
    workflow = {"5": {"inputs": {"ckpt_name": "/external/model.safetensors"}}}
    decision = verify_workflow_references(workflow)
    assert decision.accepted is False
    assert any("external" in reason for reason in decision.reasons)


def test_verify_workflow_references_rejects_parent_escape() -> None:
    workflow = {"9": {"inputs": {"filename_prefix": "../../owned"}}}
    decision = verify_workflow_references(workflow)
    assert decision.accepted is False


def test_verify_workflow_references_is_bounded_and_typed() -> None:
    workflow = {"1": {"inputs": {"nested": {"deep": {"path": "/etc/passwd"}}}}}
    decision = verify_workflow_references(workflow)
    assert isinstance(decision.accepted, bool)
    assert isinstance(decision.reasons, tuple)
    assert decision.accepted is False
