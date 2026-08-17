"""Unit tests: RAG isolated data ownership (RAG-002)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from morpheus.core.rag_ownership import (
    RagStorageDeclaration,
    validate_rag_storage,
)

OPEN_WEBUI_DB = "Open WebUI database"


def test_validate_rag_storage_accepts_morpheus_owned_root(tmp_path: Path) -> None:
    owned = tmp_path / "data" / "rag" / "vectors"
    decision = validate_rag_storage(
        vector_root=owned,
        embedding_root=tmp_path / "data" / "rag" / "embeddings",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is True
    assert decision.reasons == ()


def test_validate_rag_storage_rejects_open_webui_database_read(tmp_path: Path) -> None:
    vector_root = tmp_path / "open-webui" / "data" / "webui.db"
    decision = validate_rag_storage(
        vector_root=vector_root,
        embedding_root=tmp_path / "data" / "embeddings",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert any(OPEN_WEBUI_DB in reason for reason in decision.reasons)


def test_validate_rag_storage_rejects_open_webui_database_mutation(tmp_path: Path) -> None:
    decision = validate_rag_storage(
        vector_root=tmp_path / "data" / "vectors",
        embedding_root=tmp_path / "open-webui" / "webui.db",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert any(OPEN_WEBUI_DB in reason for reason in decision.reasons)


def test_validate_rag_storage_rejects_embeddings_shared_with_webui(tmp_path: Path) -> None:
    shared = tmp_path / "open-webui" / "data"
    decision = validate_rag_storage(
        vector_root=tmp_path / "data" / "vectors",
        embedding_root=shared,
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert any("embedding" in reason for reason in decision.reasons)


def test_validate_rag_storage_rejects_outside_morpheus_roots(tmp_path: Path) -> None:
    decision = validate_rag_storage(
        vector_root=tmp_path / "outside" / "vectors",
        embedding_root=tmp_path / "data" / "embeddings",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
    assert any("Morpheus-owned" in reason for reason in decision.reasons)
    assert decision.blockers == decision.reasons


def test_validate_rag_storage_canonicalizes_paths(tmp_path: Path) -> None:
    decision = validate_rag_storage(
        vector_root=tmp_path / "data" / "rag" / ".." / "vectors",
        embedding_root=tmp_path / "data" / "embeddings",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is True


def test_rag_storage_declaration_is_frozen_and_typed(tmp_path: Path) -> None:
    declaration = RagStorageDeclaration(
        vector_root=tmp_path / "data" / "vectors",
        embedding_root=tmp_path / "data" / "embeddings",
    )
    with pytest.raises(AttributeError):
        declaration.vector_root = tmp_path  # type: ignore[misc]


def test_validate_rag_storage_accepts_relative_owned_paths(tmp_path: Path) -> None:
    decision = validate_rag_storage(
        vector_root="rag/vectors",
        embedding_root="rag/embeddings",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is True


def test_validate_rag_storage_is_case_and_separator_aware(tmp_path: Path) -> None:
    decision = validate_rag_storage(
        vector_root=os.path.join(str(tmp_path), "OPEN-WEBUI", "data", "webui.db"),
        embedding_root=tmp_path / "data" / "embeddings",
        morpheus_data_root=tmp_path / "data",
    )
    assert decision.accepted is False
