"""RAG isolated data ownership (RAG-002).

When RAG is enabled, vector and embedding data is owned by Morpheus and
never reads or mutates Open WebUI's database. This module validates any
declared RAG storage against the Morpheus-owned data root, rejecting
Open WebUI database paths, shared embedding roots, and any path outside
the Morpheus data root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OPEN_WEBUI_MARKERS = ("open-webui", "openwebui", "webui.db")

RAG_STORAGE_GUARD_NOTE = (
    "RAG storage must live under the Morpheus-owned data root and must not "
    "read or mutate Open WebUI's database"
)


@dataclass(frozen=True, slots=True)
class RagStorageDeclaration:
    vector_root: Path
    embedding_root: Path


@dataclass(frozen=True, slots=True)
class RagStorageDecision:
    accepted: bool
    reasons: tuple[str, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reasons if not self.accepted else ()


def _owns_path(candidate: Path, data_root: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(data_root.resolve())
    except (OSError, ValueError):
        return False


def _touches_open_webui(candidate: Path) -> bool:
    parts = {part.lower() for part in candidate.parts}
    return any(marker in parts or candidate.name.lower() == marker for marker in OPEN_WEBUI_MARKERS)


def validate_rag_storage(
    *,
    vector_root: Path | str,
    embedding_root: Path | str,
    morpheus_data_root: Path | str,
) -> RagStorageDecision:
    """Validate that declared RAG storage is isolated under Morpheus roots."""
    data_root = Path(morpheus_data_root)
    vector = Path(vector_root) if Path(vector_root).is_absolute() else data_root / vector_root
    embedding = (
        Path(embedding_root) if Path(embedding_root).is_absolute() else data_root / embedding_root
    )
    reasons: list[str] = []
    for label, candidate in (("vector", vector), ("embedding", embedding)):
        if _touches_open_webui(candidate):
            reasons.append(f"RAG {label} root must not read or mutate the Open WebUI database")
        elif not _owns_path(candidate, data_root):
            reasons.append(f"RAG {label} root must be a Morpheus-owned path")
    if reasons:
        reasons.insert(0, RAG_STORAGE_GUARD_NOTE)
    return RagStorageDecision(accepted=not reasons, reasons=tuple(reasons))
