"""Unit tests: portable RAG service API and versioned metadata (RAG-003)."""

from __future__ import annotations

import json

import pytest

from morpheus.core.rag_contract import (
    CollectionMetadata,
    documented_ingest_url,
    documented_search_url,
    render_collection_metadata,
    verify_ingest_payload,
    verify_search_payload,
)


def test_collection_metadata_is_versioned_and_typed() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    assert metadata.schema_version == 1


def test_render_collection_metadata_is_versioned_json() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    rendered = json.loads(render_collection_metadata(metadata))
    assert rendered["schema_version"] == 1
    assert rendered["collection_id"] == "docs-v1"
    assert rendered["embedding_model_id"] == "text-embedding-3"
    assert rendered["chunk_size_tokens"] == 512
    assert "documents" not in rendered


def test_render_collection_metadata_rejects_unbounded_ids() -> None:
    with pytest.raises(ValueError, match="collection id"):
        CollectionMetadata(
            collection_id="x" * 200,
            embedding_model_id="m",
            chunk_size_tokens=512,
        )


def test_documented_ingest_url_uses_versioned_collection_path() -> None:
    url = documented_ingest_url(base_url="http://vector:6333", collection_id="docs-v1")
    assert url == "http://vector:6333/collections/docs-v1/points"


def test_documented_search_url_uses_versioned_collection_path() -> None:
    url = documented_search_url(base_url="http://vector:6333", collection_id="docs-v1")
    assert url == "http://vector:6333/collections/docs-v1/points/search"


def test_documented_urls_reject_unsafe_base() -> None:
    with pytest.raises(ValueError, match="http or https"):
        documented_ingest_url(base_url="file:///data", collection_id="docs-v1")


def test_verify_ingest_payload_accepts_versioned_vectors() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    payload = {
        "points": [
            {
                "id": 1,
                "vector": [0.1, 0.2, 0.3],
                "payload": {
                    "collection_schema_version": 1,
                    "embedding_model_id": "text-embedding-3",
                    "document_id": "doc-1",
                },
            }
        ]
    }
    outcome = verify_ingest_payload(payload, metadata)
    assert outcome.accepted is True
    assert outcome.reasons == ()


def test_verify_ingest_payload_rejects_missing_version_tag() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    payload = {
        "points": [
            {
                "id": 1,
                "vector": [0.1, 0.2, 0.3],
                "payload": {"document_id": "doc-1"},
            }
        ]
    }
    outcome = verify_ingest_payload(payload, metadata)
    assert outcome.accepted is False
    assert any("schema_version" in reason for reason in outcome.reasons)


def test_verify_ingest_payload_rejects_foreign_embedding_model() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    payload = {
        "points": [
            {
                "id": 1,
                "vector": [0.1, 0.2, 0.3],
                "payload": {
                    "collection_schema_version": 1,
                    "embedding_model_id": "some-other-model",
                    "document_id": "doc-1",
                },
            }
        ]
    }
    outcome = verify_ingest_payload(payload, metadata)
    assert outcome.accepted is False
    assert any("embedding_model_id" in reason for reason in outcome.reasons)


def test_verify_ingest_payload_rejects_empty_points() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    outcome = verify_ingest_payload({"points": []}, metadata)
    assert outcome.accepted is False
    assert outcome.blockers


def test_verify_search_payload_accepts_vector_and_metadata_filter() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    payload = {
        "vector": [0.1, 0.2, 0.3],
        "limit": 5,
        "filter": {"must": [{"key": "collection_schema_version", "match": {"value": 1}}]},
    }
    outcome = verify_search_payload(payload, metadata)
    assert outcome.accepted is True
    assert outcome.reasons == ()


def test_verify_search_payload_rejects_unknown_metadata_versions() -> None:
    metadata = CollectionMetadata(
        collection_id="docs-v1",
        embedding_model_id="text-embedding-3",
        chunk_size_tokens=512,
    )
    payload = {
        "vector": [0.1, 0.2, 0.3],
        "limit": 5,
        "filter": {"must": [{"key": "collection_schema_version", "match": {"value": 2}}]},
    }
    outcome = verify_search_payload(payload, metadata)
    assert outcome.accepted is False
    assert any("version" in reason for reason in outcome.reasons)
