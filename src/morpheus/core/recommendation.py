"""Immutable, content-addressed recommendation records (SEL-004, SEL-005)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from morpheus.core.benchstore import sha256_hex
from morpheus.core.catalog import CatalogCollection
from morpheus.core.paths import OwnedPathError, OwnedPathResolver
from morpheus.core.ranking import Contribution, MetricEvidence, RankedCandidate, rank_candidates
from morpheus.core.solver import (
    Candidate,
    ConstraintViolation,
    EngineRule,
    HardwareBudget,
    WorkloadRequirements,
    estimate_resource_use,
    filter_viable,
)
from morpheus.core.workload import OperatorConstraints, WorkloadPolicy

SCHEMA_VERSION = 1
_ASCII = frozenset(chr(code) for code in range(32, 127))

Migration = Callable[[dict[str, Any]], dict[str, Any]]
_MIGRATIONS: dict[int, Migration] = {}


class RecommendationError(ValueError):
    """A recommendation record or store violates its contract."""


def _bounded_identifier(value: str, what: str) -> None:
    if not value or len(value) > 128 or any(c not in _ASCII or c.isspace() for c in value):
        raise RecommendationError(f"{what} must be a bounded identifier")


def register_migration(from_version: int) -> Callable[[Migration], Migration]:
    def decorator(function: Migration) -> Migration:
        _MIGRATIONS[from_version] = function
        return function

    return decorator


def migrate(payload: dict[str, Any], from_version: int) -> dict[str, Any]:
    current = from_version
    while current < SCHEMA_VERSION:
        if current not in _MIGRATIONS:
            raise RecommendationError(f"no migration registered from schema version {current}")
        payload = _MIGRATIONS[current](payload)
        current += 1
    return payload


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON with sorted keys, stable across Python versions."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class RecommendationRecord:
    """Immutable recommendation: inputs, ranking, and complete exclusion set."""

    record_id: str
    created_at: datetime
    profile: WorkloadPolicy
    operator: OperatorConstraints | None
    reference_machine_id: str
    budget: dict[str, int | str]
    ranked: tuple[RankedCandidate, ...]
    excluded: tuple[tuple[Candidate, tuple[ConstraintViolation, ...]], ...]
    summary: str

    def __post_init__(self) -> None:
        _bounded_identifier(self.record_id, "record id")
        if self.created_at.tzinfo is None:
            raise RecommendationError("record timestamp must be timezone-aware")
        if not self.ranked:
            raise RecommendationError("recommendation must rank at least one tuple")

    def content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "profile": self.profile.to_dict(),
            "operator": self.operator.to_dict() if self.operator else None,
            "reference_machine_id": self.reference_machine_id,
            "budget": dict(self.budget),
            "ranked": [item.to_dict() for item in self.ranked],
            "excluded": [
                {
                    "candidate": {
                        "model_id": candidate.model_id,
                        "quantization": candidate.quantization,
                        "engine_id": candidate.engine_id,
                        "context_window": candidate.context_window,
                        "concurrency": candidate.concurrency,
                    },
                    "violations": [
                        {"code": violation.code, "detail": violation.detail}
                        for violation in violations
                    ],
                }
                for candidate, violations in self.excluded
            ],
            "summary": self.summary,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self.content_dict()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecommendationRecord:
        created = datetime.fromisoformat(payload["created_at"])
        if created.tzinfo is None:
            raise RecommendationError("record timestamp must be timezone-aware")
        return cls(
            record_id=payload["record_id"],
            created_at=created.astimezone(UTC),
            profile=WorkloadPolicy.from_dict(payload["profile"]),
            operator=_operator_from_dict(payload["operator"]) if payload.get("operator") else None,
            reference_machine_id=payload["reference_machine_id"],
            budget=dict(payload["budget"]),
            ranked=tuple(_ranked_from_dict(item) for item in payload["ranked"]),
            excluded=tuple(_excluded_from_dict(item) for item in payload["excluded"]),
            summary=payload["summary"],
        )


def _operator_from_dict(payload: dict[str, Any]) -> OperatorConstraints:
    return OperatorConstraints(
        max_context=payload.get("max_context"),
        max_concurrency=payload.get("max_concurrency"),
        allowed_engines=tuple(payload.get("allowed_engines", [])),
        allowed_quantizations=tuple(payload.get("allowed_quantizations", [])),
        max_ram_bytes=payload.get("max_ram_bytes"),
        max_vram_bytes=payload.get("max_vram_bytes"),
        max_storage_bytes=payload.get("max_storage_bytes"),
    )


def _ranked_from_dict(payload: dict[str, Any]) -> RankedCandidate:
    candidate = _candidate_from_dict(payload["candidate"])
    contributions = tuple(
        Contribution(
            metric=item["metric"],
            weight=item["weight"],
            calibrated=item["calibrated"],
            effective_confidence=item["effective_confidence"],
            contribution=item["contribution"],
            comparability=item["comparability"],
        )
        for item in payload["contributions"]
    )
    return RankedCandidate(
        candidate=candidate,
        score=payload["score"],
        contributions=contributions,
        summary=payload["summary"],
    )


def _candidate_from_dict(payload: dict[str, Any]) -> Candidate:
    return Candidate(
        model_id=payload["model_id"],
        quantization=payload["quantization"],
        engine_id=payload["engine_id"],
        context_window=payload["context_window"],
        concurrency=payload["concurrency"],
    )


def _excluded_from_dict(
    payload: dict[str, Any],
) -> tuple[Candidate, tuple[ConstraintViolation, ...]]:
    violations = tuple(
        ConstraintViolation(item["code"], item["detail"]) for item in payload["violations"]
    )
    return _candidate_from_dict(payload["candidate"]), violations


@dataclass(slots=True)
class RecommendationStore:
    """Versioned, content-addressed recommendation record store."""

    root: Path
    resolver: OwnedPathResolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = OwnedPathResolver(self.root)

    def _path(self, relative: str) -> Path:
        return self.resolver.resolve_relative(relative)

    def initialize(self) -> None:
        self._path("raw").mkdir(parents=True, exist_ok=True)
        manifest_path = self._path("manifest.json")
        if not manifest_path.exists():
            payload = {
                "schema_version": SCHEMA_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "store_digest": sha256_hex(b""),
                "entries": [],
            }
            self._write_json(manifest_path, payload)

    def store_record(self, record: RecommendationRecord) -> str:
        """Store a record content-addressed by its canonical payload digest."""
        digest = sha256_hex(canonical_json(record.content_dict()).encode("utf-8"))
        if digest != record.record_id:
            raise RecommendationError("record digest does not match its content")
        payload = record.to_dict()
        target = self._path(f"raw/{digest}")
        if target.exists():
            stored = self._read_json(target)
            if stored != payload:
                raise RecommendationError(f"content-addressed collision at {digest}")
        else:
            self._write_json(target, payload)
        entries_path = self._path("manifest.json")
        manifest = self._read_json(entries_path)
        if digest not in manifest["entries"]:
            manifest["entries"] = sorted([*manifest["entries"], digest])
            self._write_json(entries_path, manifest)
        return digest

    def load_record(self, record_id: str) -> RecommendationRecord:
        if len(record_id) != 64 or any(c not in "0123456789abcdef" for c in record_id):
            raise RecommendationError("record id must be sha256 hex")
        payload = self._read_document(f"raw/{record_id}")
        if payload.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            payload = migrate(payload, payload["schema_version"])
        return RecommendationRecord.from_dict(payload)

    def latest(self) -> RecommendationRecord | None:
        manifest_path = self._path("manifest.json")
        if not manifest_path.exists():
            return None
        manifest = self._read_json(manifest_path)
        entries = manifest.get("entries", [])
        if not entries:
            return None
        newest: RecommendationRecord | None = None
        for digest in entries:
            candidate = self.load_record(digest)
            if newest is None or candidate.created_at > newest.created_at:
                newest = candidate
        return newest

    def backup(self, destination: Path) -> None:
        destination = OwnedPathResolver(self.root.parent).resolve(destination)
        if destination.exists():
            raise RecommendationError("backup destination already exists")
        shutil.copytree(self.root, destination, symlinks=False)

    @classmethod
    def restore(cls, backup: Path, destination: Path) -> RecommendationStore:
        backup = OwnedPathResolver(destination.parent).resolve(backup)
        if not (backup / "manifest.json").exists():
            raise RecommendationError("not a recommendation store backup")
        store = cls(destination)
        store.initialize()
        for child in backup.iterdir():
            target = store._path(child.name)
            if target.is_dir():
                shutil.rmtree(target)
                shutil.copytree(child, target, symlinks=False)
            else:
                target.write_bytes(child.read_bytes())
        return store

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(payload), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise OwnedPathError("store documents must not be symbolic links")
        if not path.exists():
            raise RecommendationError(f"store document missing: {path.name}")
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return payload

    def _read_document(self, relative: str) -> dict[str, Any]:
        raw = Path(self.root, relative)
        if raw.is_symlink():
            raise OwnedPathError("store documents must not be symbolic links")
        return self._read_json(self._path(relative))


def build_recommendation(
    *,
    profile: WorkloadPolicy,
    operator: OperatorConstraints | None,
    reference_machine_id: str,
    budget: dict[str, int | str],
    ranked: tuple[RankedCandidate, ...],
    excluded: tuple[tuple[Candidate, tuple[ConstraintViolation, ...]], ...],
    created_at: datetime | None = None,
) -> RecommendationRecord:
    """Build an immutable record whose id is the digest of its content."""
    if not ranked:
        raise RecommendationError("recommendation must rank at least one tuple")
    summary = _record_summary(ranked, excluded)
    created = created_at or datetime.now(UTC)
    record = RecommendationRecord(
        record_id=sha256_hex(b""),
        created_at=created,
        profile=profile,
        operator=operator,
        reference_machine_id=reference_machine_id,
        budget=dict(budget),
        ranked=ranked,
        excluded=excluded,
        summary=summary,
    )
    digest = sha256_hex(canonical_json(record.content_dict()).encode("utf-8"))
    return RecommendationRecord(
        record_id=digest,
        created_at=created,
        profile=profile,
        operator=operator,
        reference_machine_id=reference_machine_id,
        budget=dict(budget),
        ranked=ranked,
        excluded=excluded,
        summary=summary,
    )


def _record_summary(
    ranked: tuple[RankedCandidate, ...],
    excluded: tuple[tuple[Candidate, tuple[ConstraintViolation, ...]], ...],
) -> str:
    top = ranked[0]
    bottom = ranked[-1]
    exclusion_codes = {
        code for _, violations in excluded for code in (violation.code for violation in violations)
    }
    parts = [
        f"top: {top.candidate.model_id}/{top.candidate.quantization} "
        f"{top.candidate.engine_id} (score {top.score:.3f})",
        f"bottom: {bottom.candidate.model_id}/{bottom.candidate.quantization} "
        f"{bottom.candidate.engine_id} (score {bottom.score:.3f})",
        f"excluded: {len(excluded)} tuples",
    ]
    if exclusion_codes:
        parts.append(f"exclusion reasons: {', '.join(sorted(exclusion_codes))}")
    return "; ".join(parts)


def default_engine_rules(catalog: CatalogCollection) -> dict[str, EngineRule]:
    """Deterministic engine rules derived from catalog engine features."""
    rules: dict[str, EngineRule] = {}
    for engine in catalog.engines:
        accelerator = "cuda" if "cuda" in engine.features else "cpu"
        quantizations = sorted(
            {
                quantization
                for model in catalog.models
                if engine.id in model.engine_support
                for quantization in model.quantizations
            }
        )
        rules[engine.id] = EngineRule(
            engine_id=engine.id,
            accelerator=accelerator,
            max_context=131072,
            quantizations=tuple(quantizations),
        )
    return rules


def candidates_for_catalog(catalog: CatalogCollection) -> tuple[Candidate, ...]:
    """Deterministic candidate tuples from catalog models and engines."""
    candidates: list[Candidate] = []
    for model in catalog.models:
        for engine_id in model.engine_support:
            if not any(engine.id == engine_id for engine in catalog.engines):
                continue
            for quantization in model.quantizations:
                ceiling = min(65536, model.context_window or 65536)
                contexts = sorted({8192, ceiling})
                for context_window in contexts:
                    for concurrency in (1, 4):
                        candidates.append(
                            Candidate(
                                model_id=model.id,
                                quantization=quantization,
                                engine_id=engine_id,
                                context_window=context_window,
                                concurrency=concurrency,
                            )
                        )
    return tuple(candidates)


def budget_from_host(host: dict[str, Any]) -> HardwareBudget | None:
    """Build a hardware budget from agent host evidence; None when unavailable."""
    memory = host.get("memory") or {}
    disk = host.get("disk") or {}
    total_ram = memory.get("total_bytes")
    storage = disk.get("total_bytes")
    if not total_ram or not storage:
        return None
    gpu = host.get("gpu") or {}
    vram_mib = gpu.get("memory_total_mib")
    accelerator = "cuda" if vram_mib else "cpu"
    vram_bytes = int(vram_mib) * 1024 * 1024 if vram_mib else 0
    return HardwareBudget(
        ram_bytes=int(total_ram),
        vram_bytes=vram_bytes,
        storage_bytes=int(storage),
        accelerator=accelerator,
    )


def recommend_for_host(
    *,
    profile: WorkloadPolicy,
    budget: HardwareBudget,
    catalog: CatalogCollection,
    operator: OperatorConstraints | None = None,
    reference_machine_id: str = "local",
) -> tuple[
    tuple[RankedCandidate, ...],
    tuple[tuple[Candidate, tuple[ConstraintViolation, ...]], ...],
]:
    """Partition catalog candidates and rank the viable subset for a host.

    Evidence is derived honestly from resource estimates (memory headroom and
    resource cost, provenance ``estimated``); no invented benchmark values.
    """
    rules = default_engine_rules(catalog)
    models = {model.id: model for model in catalog.models}
    engines = {engine.id: engine for engine in catalog.engines}
    requirements = WorkloadRequirements(
        features=profile.features,
        context_tokens=profile.context_tokens,
        concurrency=profile.concurrency,
    )
    viable, rejected = filter_viable(
        candidates_for_catalog(catalog),
        models=models,
        engines=engines,
        engine_rules=rules,
        budget=budget,
        requirements=requirements,
        operator=operator,
    )
    evidence: dict[Candidate, tuple[MetricEvidence, ...]] = {}
    for candidate in viable:
        model = models[candidate.model_id]
        estimate = estimate_resource_use(model, candidate, budget)
        headroom = max(0.0, 1.0 - estimate.ram_with_margin() / budget.ram_bytes)
        cost = min(1.0, estimate.ram_with_margin() / budget.ram_bytes)
        evidence[candidate] = (
            MetricEvidence(
                metric="memory_headroom",
                value=headroom,
                provenance="estimated",
                source="resource-estimate",
                machine_id=None,
            ),
            MetricEvidence(
                metric="resource_cost",
                value=cost,
                provenance="estimated",
                source="resource-estimate",
                machine_id=None,
            ),
        )
    ranked = rank_candidates(
        viable,
        profile=profile,
        evidence_by_candidate=evidence,
        reference_machine_id=reference_machine_id,
    )
    return ranked, rejected
