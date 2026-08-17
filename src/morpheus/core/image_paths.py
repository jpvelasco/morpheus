"""Morpheus-owned ComfyUI paths and safe workflow references (IMG-001).

Morpheus integrates upstream ComfyUI using its documented API, but only
with Morpheus-owned models, input, output, and workflow paths. Every root
must live under the Morpheus data root, and any path referenced inside a
ComfyUI workflow must be a safe relative path (never absolute, never
parent-traversing, never null-byte).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_PATH_KEYS = (
    "ckpt_name",
    "filename",
    "filename_prefix",
    "path",
    "subfolder",
    "input_dir",
    "output_dir",
)


@dataclass(frozen=True, slots=True)
class OwnedImagePaths:
    models_root: Path
    inputs_root: Path
    outputs_root: Path
    workflows_root: Path


@dataclass(frozen=True, slots=True)
class ImagePathsDecision:
    accepted: bool
    reasons: tuple[str, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reasons if not self.accepted else ()


def _resolve_owned(candidate: Path | str, data_root: Path) -> Path:
    path = Path(candidate)
    return path if path.is_absolute() else data_root / path


def _under_root(candidate: Path | str, data_root: Path) -> bool:
    try:
        return _resolve_owned(candidate, data_root).resolve().is_relative_to(data_root.resolve())
    except (OSError, ValueError):
        return False


def validate_owned_image_paths(
    *,
    models_root: Path | str,
    inputs_root: Path | str,
    outputs_root: Path | str,
    workflows_root: Path | str,
    morpheus_data_root: Path | str,
) -> ImagePathsDecision:
    """Validate that every ComfyUI root is owned by Morpheus."""
    data_root = Path(morpheus_data_root)
    roots = {
        "models": models_root,
        "inputs": inputs_root,
        "outputs": outputs_root,
        "workflows": workflows_root,
    }
    reasons = [
        f"ComfyUI {label} root must be a Morpheus-owned path"
        for label, root in roots.items()
        if not _under_root(root, data_root)
    ]
    return ImagePathsDecision(accepted=not reasons, reasons=tuple(reasons))


def safe_workflow_reference(value: str) -> bool:
    """A workflow path reference is safe only as a non-empty relative path."""
    if not value or "\x00" in value or value.startswith(("\\", "/")) or ":" in value:
        return False
    path = PurePosixPath(value.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def verify_workflow_references(workflow: object, *, _depth: int = 0) -> ImagePathsDecision:
    """Walk a bounded workflow graph and reject unsafe path references."""
    if _depth > 8:
        return ImagePathsDecision(
            accepted=False, reasons=("workflow graph exceeds the bounded depth",)
        )
    reasons: list[str] = []
    if isinstance(workflow, dict):
        for key, value in workflow.items():
            if isinstance(key, str) and key.lower() in _PATH_KEYS and isinstance(value, str):
                if not safe_workflow_reference(value):
                    reasons.append(f"workflow {key} references an external path")
            elif isinstance(value, dict | list):
                reasons.extend(verify_workflow_references(value, _depth=_depth + 1).reasons)
    elif isinstance(workflow, list):
        for item in workflow:
            reasons.extend(verify_workflow_references(item, _depth=_depth + 1).reasons)
    return ImagePathsDecision(accepted=not reasons, reasons=tuple(reasons))
