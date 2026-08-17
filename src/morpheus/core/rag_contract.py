"""Portable RAG service API and versioned collection metadata (RAG-003).

Ingestion and retrieval use documented service APIs (the Qdrant REST
shape: collection-scoped points endpoints) and every collection carries
versioned metadata. Payload verification is strict: vectors must carry a
matching collection schema version and embedding model id, and searches
must pin the versioned metadata filter.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from morpheus.core.benchmark import bounded_identifier

COLLECTION_METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CollectionMetadata:
    collection_id: str
    embedding_model_id: str
    chunk_size_tokens: int
    schema_version: int = COLLECTION_METADATA_SCHEMA_VERSION

    def __post_init__(self) -> None:
        bounded_identifier(self.collection_id, "collection id")
        bounded_identifier(self.embedding_model_id, "embedding model id")
        if self.chunk_size_tokens < 1:
            raise ValueError("chunk_size_tokens must be positive")


@dataclass(frozen=True, slots=True)
class RagPayloadDecision:
    accepted: bool
    reasons: tuple[str, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reasons if not self.accepted else ()


def _documented_url(base_url: str, *, collection_id: str, suffix: str) -> str:
    bounded_identifier(collection_id, "collection id")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("RAG service base URL must use http or https and have a host")
    if parsed.username or parsed.password:
        raise ValueError("RAG service base URL must not contain embedded credentials")
    return f"{base_url.rstrip('/')}/collections/{collection_id}{suffix}"


def documented_ingest_url(*, base_url: str, collection_id: str) -> str:
    """Documented ingestion endpoint for a versioned collection."""
    return _documented_url(base_url, collection_id=collection_id, suffix="/points")


def documented_search_url(*, base_url: str, collection_id: str) -> str:
    """Documented retrieval endpoint for a versioned collection."""
    return _documented_url(base_url, collection_id=collection_id, suffix="/points/search")


def render_collection_metadata(metadata: CollectionMetadata) -> str:
    """Render the versioned collection metadata document."""
    import json

    return json.dumps(
        {
            "schema_version": metadata.schema_version,
            "collection_id": metadata.collection_id,
            "embedding_model_id": metadata.embedding_model_id,
            "chunk_size_tokens": metadata.chunk_size_tokens,
        },
        sort_keys=True,
    )


def verify_ingest_payload(payload: object, metadata: CollectionMetadata) -> RagPayloadDecision:
    """Verify an ingestion payload carries the versioned metadata contract."""
    points = payload.get("points") if isinstance(payload, dict) else None
    if not isinstance(points, list) or not points:
        return RagPayloadDecision(
            accepted=False, reasons=("ingestion payload must include points",)
        )
    reasons: list[str] = []
    for point in points:
        point_payload = point.get("payload") if isinstance(point, dict) else None
        if not isinstance(point_payload, dict):
            reasons.append("every point must carry collection metadata")
            continue
        if point_payload.get("collection_schema_version") != metadata.schema_version:
            reasons.append("point collection_schema_version does not match the collection metadata")
        if point_payload.get("embedding_model_id") != metadata.embedding_model_id:
            reasons.append("point embedding_model_id does not match the collection metadata")
    return RagPayloadDecision(accepted=not reasons, reasons=tuple(reasons))


def verify_search_payload(payload: object, metadata: CollectionMetadata) -> RagPayloadDecision:
    """Verify a retrieval payload pins the versioned collection metadata."""
    if not isinstance(payload, dict) or "vector" not in payload:
        return RagPayloadDecision(
            accepted=False, reasons=("retrieval payload must include a vector",)
        )
    filter_must = (
        payload.get("filter", {}).get("must") if isinstance(payload.get("filter"), dict) else None
    )
    if not isinstance(filter_must, list):
        return RagPayloadDecision(
            accepted=False,
            reasons=("retrieval must filter on collection_schema_version",),
        )
    matching = any(
        isinstance(clause, dict)
        and clause.get("key") == "collection_schema_version"
        and isinstance(clause.get("match"), dict)
        and clause["match"].get("value") == metadata.schema_version
        for clause in filter_must
    )
    if not matching:
        return RagPayloadDecision(
            accepted=False,
            reasons=(f"retrieval must pin collection schema version {metadata.schema_version}",),
        )
    return RagPayloadDecision(accepted=True, reasons=())
