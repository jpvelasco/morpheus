"""Versioned model and engine catalogs (SEL-001) with trust evaluation.

Catalog documents are immutable: parsing reproduces the same entries and no
catalog operation mutates installed plans. Trust evaluation is pure and
explainable, returning violations instead of raising.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_BOUNDED_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SAFE_SOURCE = ("https://", "hf://")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CatalogError(ValueError):
    """A catalog document or entry violates its schema."""


def _bounded(value: str, what: str) -> str:
    if not _BOUNDED_ID.fullmatch(value):
        raise CatalogError(f"{what} must be a bounded identifier")
    return value


def _safe_source(value: str | None) -> str | None:
    if value is None:
        return None
    if not any(value.startswith(prefix) for prefix in _SAFE_SOURCE):
        raise CatalogError("catalog source must be https:// or hf://")
    if "@" in value.split("/", 2)[2]:
        raise CatalogError("catalog source must not embed credentials")
    return value


def _digest(value: str | None) -> str | None:
    if value is None:
        return None
    if not _DIGEST_PATTERN.fullmatch(value):
        raise CatalogError("catalog digest must be a sha256 hex digest")
    return value


def _day(value: str | None, what: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CatalogError(f"{what} must be an ISO-8601 date") from None


def _optional_int(value: Any, what: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise CatalogError(f"{what} must be a non-negative integer")
    return value


def _strings(value: Any, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogError(f"{what} must be a list of strings")
    return tuple(value)


@dataclass(frozen=True)
class ModelCatalogEntry:
    id: str
    name: str
    license: str
    architecture: str
    modalities: tuple[str, ...]
    formats: tuple[str, ...]
    quantizations: tuple[str, ...]
    context_window: int | None = None
    artifact_size_bytes: int | None = None
    validation_freshness: date | None = None
    source_url: str | None = None
    source_digest: str | None = None
    revision: str | None = None
    engine_support: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    compatibility: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "license": self.license,
            "architecture": self.architecture,
            "modalities": list(self.modalities),
            "formats": list(self.formats),
            "quantizations": list(self.quantizations),
            "context_window": self.context_window,
            "artifact_size_bytes": self.artifact_size_bytes,
            "validation_freshness": self.validation_freshness.isoformat()
            if self.validation_freshness
            else None,
            "source_url": self.source_url,
            "source_digest": self.source_digest,
            "revision": self.revision,
            "engine_support": list(self.engine_support),
            "features": list(self.features),
            "compatibility": list(self.compatibility),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ModelCatalogEntry:
        unknown = set(payload) - set(cls.__dataclass_fields__)
        if unknown:
            raise CatalogError(f"unknown model catalog field: {sorted(unknown)[0]}")
        return cls(
            id=_bounded(payload["id"], "model id"),
            name=str(payload["name"]),
            license=str(payload["license"]),
            architecture=str(payload["architecture"]),
            modalities=_strings(payload["modalities"], "modalities"),
            formats=_strings(payload["formats"], "formats"),
            quantizations=_strings(payload["quantizations"], "quantizations"),
            context_window=_optional_int(payload.get("context_window"), "context window"),
            artifact_size_bytes=_optional_int(payload.get("artifact_size_bytes"), "artifact size"),
            validation_freshness=_day(payload.get("validation_freshness"), "validation freshness"),
            source_url=_safe_source(payload.get("source_url")),
            source_digest=_digest(payload.get("source_digest")),
            revision=payload.get("revision"),
            engine_support=_strings(payload.get("engine_support", []), "engine support"),
            features=_strings(payload.get("features", []), "features"),
            compatibility=_strings(payload.get("compatibility", []), "compatibility"),
        )


@dataclass(frozen=True)
class EngineCatalogEntry:
    id: str
    name: str
    license: str
    version: str
    platforms: tuple[str, ...]
    features: tuple[str, ...] = ()
    released: date | None = None
    source_url: str | None = None
    source_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "license": self.license,
            "version": self.version,
            "platforms": list(self.platforms),
            "features": list(self.features),
            "released": self.released.isoformat() if self.released else None,
            "source_url": self.source_url,
            "source_digest": self.source_digest,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EngineCatalogEntry:
        unknown = set(payload) - set(cls.__dataclass_fields__)
        if unknown:
            raise CatalogError(f"unknown engine catalog field: {sorted(unknown)[0]}")
        return cls(
            id=_bounded(payload["id"], "engine id"),
            name=str(payload["name"]),
            license=str(payload["license"]),
            version=str(payload["version"]),
            platforms=_strings(payload["platforms"], "platforms"),
            features=_strings(payload.get("features", []), "features"),
            released=_day(payload.get("released"), "release date"),
            source_url=_safe_source(payload.get("source_url")),
            source_digest=_digest(payload.get("source_digest")),
        )


@dataclass(frozen=True)
class CatalogCollection:
    version: str
    models: tuple[ModelCatalogEntry, ...]
    engines: tuple[EngineCatalogEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "models": [entry.to_dict() for entry in self.models],
            "engines": [entry.to_dict() for entry in self.engines],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CatalogCollection:
        unknown = set(payload) - {"version", "models", "engines"}
        if unknown:
            raise CatalogError(f"unknown catalog field: {sorted(unknown)[0]}")
        models = [ModelCatalogEntry.from_dict(item) for item in payload["models"]]
        engines = [EngineCatalogEntry.from_dict(item) for item in payload["engines"]]
        return cls(
            version=str(payload["version"]),
            models=tuple(models),
            engines=tuple(engines),
        )


def validate_references(collection: CatalogCollection) -> tuple[str, ...]:
    """Return dangling model engine-support references as violation strings."""
    engine_ids = {engine.id for engine in collection.engines}
    return tuple(
        f"model {model.id} requires unknown engine {engine_id}"
        for model in collection.models
        for engine_id in model.engine_support
        if engine_id not in engine_ids
    )


@dataclass(frozen=True)
class TrustPolicy:
    permitted_sources: tuple[str, ...] = ()
    required_licenses: tuple[str, ...] = ()
    require_digest: bool = True
    max_freshness_days: int | None = 90


@dataclass(frozen=True)
class TrustViolation:
    entry_id: str
    reason: str


def evaluate_trust(
    collection: CatalogCollection,
    policy: TrustPolicy,
    today: date,
) -> tuple[
    tuple[ModelCatalogEntry, ...], tuple[EngineCatalogEntry, ...], tuple[TrustViolation, ...]
]:
    """Filter a collection against a trust policy, reporting every violation."""
    trusted_models: list[ModelCatalogEntry] = []
    trusted_engines: list[EngineCatalogEntry] = []
    violations: list[TrustViolation] = []

    for model in collection.models:
        reasons = _trust_reasons(
            source=model.source_url,
            license=model.license,
            digest=model.source_digest,
            freshness=model.validation_freshness,
            policy=policy,
            today=today,
        )
        if reasons:
            violations.extend(TrustViolation(model.id, reason) for reason in reasons)
        else:
            trusted_models.append(model)
    for engine in collection.engines:
        reasons = _trust_reasons(
            source=engine.source_url,
            license=engine.license,
            digest=engine.source_digest,
            freshness=engine.released,
            policy=policy,
            today=today,
        )
        if reasons:
            violations.extend(TrustViolation(engine.id, reason) for reason in reasons)
        else:
            trusted_engines.append(engine)
    return tuple(trusted_models), tuple(trusted_engines), tuple(violations)


def _trust_reasons(
    *,
    source: str | None,
    license: str,
    digest: str | None,
    freshness: date | None,
    policy: TrustPolicy,
    today: date,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if source is None:
        reasons.append("missing immutable source")
    elif policy.permitted_sources and not any(
        source.startswith(prefix) for prefix in policy.permitted_sources
    ):
        reasons.append("source is not permitted by trust policy")
    if policy.required_licenses and license not in policy.required_licenses:
        reasons.append("license is not permitted by trust policy")
    if policy.require_digest and digest is None:
        reasons.append("missing sha256 digest")
    if policy.max_freshness_days is not None:
        if freshness is None:
            reasons.append("never validated")
        elif (today - freshness).days > policy.max_freshness_days:
            reasons.append("validation evidence is stale")
    return tuple(reasons)


def catalog_digest(collection: CatalogCollection) -> str:
    """Content digest over the canonical catalog document."""
    return hashlib.sha256(
        json.dumps(collection.to_dict(), sort_keys=True).encode("utf-8")
    ).hexdigest()


SEED_MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        id="llama-3.1-8b-instruct",
        name="Llama 3.1 8B Instruct",
        license="llama-3.1",
        architecture="llama",
        modalities=("text",),
        formats=("gguf",),
        quantizations=("q4_k_m", "q5_k_m"),
        context_window=131072,
        artifact_size_bytes=4_910_000_000,
        validation_freshness=date(2026, 7, 1),
        source_url="hf://huggingface.co/meta-llama/Llama-3.1-8B-Instruct-GGUF",
        revision="main",
        engine_support=("llama.cpp",),
        features=("tool_calling", "structured_output", "reasoning"),
    ),
    ModelCatalogEntry(
        id="qwen2.5-7b-instruct",
        name="Qwen2.5 7B Instruct",
        license="apache-2.0",
        architecture="qwen2",
        modalities=("text",),
        formats=("safetensors",),
        quantizations=("awq", "gptq"),
        context_window=32768,
        artifact_size_bytes=15_000_000_000,
        validation_freshness=date(2026, 7, 15),
        source_url="hf://huggingface.co/Qwen/Qwen2.5-7B-Instruct",
        revision="main",
        engine_support=("vllm",),
        features=("tool_calling", "structured_output"),
    ),
    ModelCatalogEntry(
        id="mistral-7b-instruct",
        name="Mistral 7B Instruct v0.3",
        license="apache-2.0",
        architecture="mistral",
        modalities=("text",),
        formats=("gguf",),
        quantizations=("q4_k_m",),
        context_window=32768,
        artifact_size_bytes=4_370_000_000,
        validation_freshness=date(2026, 7, 20),
        source_url="hf://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3",
        revision="main",
        engine_support=("llama.cpp",),
        features=("tool_calling",),
    ),
)

SEED_ENGINES: tuple[EngineCatalogEntry, ...] = (
    EngineCatalogEntry(
        id="llama.cpp",
        name="llama.cpp",
        license="mit",
        version="b6000",
        platforms=("linux", "windows", "macos"),
        features=("gguf", "cpu", "metal", "tool_calling"),
        released=date(2026, 7, 1),
        source_url="https://github.com/ggml-org/llama.cpp",
    ),
    EngineCatalogEntry(
        id="vllm",
        name="vLLM",
        license="apache-2.0",
        version="0.8.4",
        platforms=("linux",),
        features=("safetensors", "cuda", "paged-attention", "tool_calling"),
        released=date(2026, 7, 10),
        source_url="https://github.com/vllm-project/vllm",
    ),
)

SEED_CATALOG: CatalogCollection = CatalogCollection(
    version="2026.2",
    models=SEED_MODELS,
    engines=SEED_ENGINES,
)

SEED_TRUST_POLICY = TrustPolicy(
    permitted_sources=("hf://huggingface.co/", "https://github.com/"),
    required_licenses=("apache-2.0", "mit", "llama-3.1"),
    require_digest=False,
    max_freshness_days=90,
)

DEFAULT_TRUST_POLICY = TrustPolicy(
    permitted_sources=("hf://huggingface.co/", "https://github.com/"),
    required_licenses=("apache-2.0", "mit", "llama-3.1"),
    require_digest=True,
    max_freshness_days=90,
)
