"""Evidence-backed recommendation service over retained repositories (R2).

The service composes the retained catalog snapshot repository, the persisted
machine profile repository, benchmark evidence, ranking policy, and the
canonical plan family. It never reads ``SEED_CATALOG`` from a request path and
never derives identity from observation timestamps: one immutable set of
record inputs replays to one byte-equivalent recommendation and one canonical
plan per viable candidate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from morpheus.core.benchmark import BenchmarkError, BenchmarkSummary
from morpheus.core.benchstore import BenchmarkStore, CampaignRun, sha256_hex
from morpheus.core.catalog import CatalogCollection, EngineCatalogEntry, ModelCatalogEntry
from morpheus.core.ranking import (
    ESTIMATED_CONFIDENCE_CAP,
    STALE_AFTER_DAYS,
    MetricEvidence,
    rank_candidates,
)
from morpheus.core.recommendation import (
    RecommendationError,
    RecommendationRecord,
    build_recommendation,
    candidates_for_catalog,
    canonical_json,
    default_engine_rules,
)
from morpheus.core.records import (
    DeploymentPlan,
    EngineIdentity,
    MachineProfile,
    ModelIdentity,
    Recommendation,
    WorkloadProfile,
)
from morpheus.core.solver import (
    Candidate,
    HardwareBudget,
    WorkloadRequirements,
    estimate_resource_use,
    filter_viable,
)
from morpheus.core.workload import OperatorConstraints, WorkloadPolicy
from morpheus.ports.protocols import Clock

PLAN_CACHE_POLICY = "owned-cache"
PLAN_OWNED_PATHS = ("/opt/morpheus/plans",)
PLAN_PORTS = (8080,)
PLAN_HEALTH_CONTRACT = "health-openai-compatible-0001"
PLAN_BENCHMARK_GATE = "gate-recommendation-0001"


def catalog_snapshot_digest(collection: CatalogCollection) -> str:
    """Content digest naming exactly one retained catalog snapshot."""
    return sha256_hex(canonical_json(collection.to_dict()).encode("utf-8"))


class RecommendationRepositories(Protocol):
    """Retained repositories the recommendation service composes over."""

    def machine_profile(self, machine_id: str) -> MachineProfile | None: ...

    def catalog_snapshot(self, digest: str) -> dict[str, Any] | None: ...

    def save_plan(self, plan: DeploymentPlan) -> None: ...

    def save_recommendation(self, recommendation: Recommendation) -> None: ...

    def recommendation(self, recommendation_id: str) -> Recommendation | None: ...

    def plan(self, plan_id: str) -> DeploymentPlan | None: ...


class BenchmarkEvidencePort(Protocol):
    """Completed campaign runs paired with their normalized summaries."""

    def completed_runs(self) -> tuple[tuple[CampaignRun, BenchmarkSummary], ...]: ...


class StoreBenchmarkEvidence:
    """Adapter reading completed runs and p50 summaries from the bench store."""

    def __init__(self, store: BenchmarkStore) -> None:
        self._store = store

    def completed_runs(self) -> tuple[tuple[CampaignRun, BenchmarkSummary], ...]:
        pairs: list[tuple[CampaignRun, BenchmarkSummary]] = []
        for run in self._store.list_runs(limit=100):
            if run.status != "completed":
                continue
            try:
                summary = self._store.load_summary(run.run_id, "p50")
            except BenchmarkError:
                continue
            pairs.append((run, summary))
        return tuple(pairs)


@dataclass(frozen=True, slots=True)
class RecommendationOutcome:
    """One replayable recommendation over retained evidence."""

    record: RecommendationRecord
    selection: Recommendation
    plans: tuple[DeploymentPlan, ...]


class RecommendationService:
    """Owns evidence-backed preview and operator choice over canonical plans."""

    def __init__(
        self,
        *,
        records: RecommendationRepositories,
        evidence: BenchmarkEvidencePort,
        clock: Clock | None = None,
    ) -> None:
        self._records = records
        self._evidence = evidence
        self._clock = clock

    # -- preview -------------------------------------------------------------

    def preview(
        self,
        *,
        machine_id: str,
        catalog_digest: str,
        policy: WorkloadPolicy,
        budget: HardwareBudget,
        operator: OperatorConstraints | None = None,
    ) -> RecommendationOutcome:
        profile = self._records.machine_profile(machine_id)
        if profile is None:
            raise RecommendationError(
                f"machine profile {machine_id!r} is not retained; "
                "persist the observed profile before requesting recommendations"
            )
        snapshot = self._records.catalog_snapshot(catalog_digest)
        if snapshot is None:
            raise RecommendationError(
                f"catalog snapshot {catalog_digest!r} is not retained; "
                "seed the catalog repository explicitly instead of bypassing it"
            )
        collection = CatalogCollection.from_dict(snapshot)

        requirements = WorkloadRequirements(
            features=policy.features,
            context_tokens=policy.context_tokens,
            concurrency=policy.concurrency,
        )
        models = {model.id: model for model in collection.models}
        engines = {engine.id: engine for engine in collection.engines}
        viable, rejected = filter_viable(
            candidates_for_catalog(collection),
            models=models,
            engines=engines,
            engine_rules=default_engine_rules(collection),
            budget=budget,
            requirements=requirements,
            operator=operator,
        )
        ranked = rank_candidates(
            viable,
            profile=policy,
            evidence_by_candidate={
                candidate: self._evidence_for(candidate, models[candidate.model_id], budget)
                for candidate in viable
            },
            reference_machine_id=machine_id,
        )
        plans = tuple(
            self._materialize_plan(
                item.candidate,
                models[item.candidate.model_id],
                engines[item.candidate.engine_id],
                policy=policy,
                budget=budget,
                catalog_digest=catalog_digest,
            )
            for item in ranked
        )
        # Each ranked tuple names the canonical plan it deterministically
        # materializes; rank order and stored selection order agree.
        ranked = tuple(
            replace(item, plan_id=plan.plan_id) for item, plan in zip(ranked, plans, strict=False)
        )
        for plan in plans:
            self._records.save_plan(plan)
        selection = Recommendation(
            recommendation_id=_selection_id(machine_id, catalog_digest, plans),
            machine_id=machine_id,
            plan_ids=tuple(plan.plan_id for plan in plans),
            evidence_ranked=True,
            weights=policy.weights,
        )
        self._records.save_recommendation(selection)
        record = build_recommendation(
            profile=policy,
            operator=operator,
            reference_machine_id=machine_id,
            budget={
                "ram_bytes": budget.ram_bytes,
                "vram_bytes": budget.vram_bytes,
                "storage_bytes": budget.storage_bytes,
                "accelerator": budget.accelerator,
            },
            ranked=ranked,
            excluded=rejected,
            created_at=self._now(),
            catalog_digest=catalog_digest,
        )
        return RecommendationOutcome(record=record, selection=selection, plans=plans)

    # -- operator choice -----------------------------------------------------

    def choose(self, *, recommendation_id: str, plan_id: str) -> DeploymentPlan:
        selection = self._records.recommendation(recommendation_id)
        if selection is None:
            raise RecommendationError(f"unknown recommendation identity: {recommendation_id!r}")
        plan = self._records.plan(plan_id)
        if plan is None:
            raise RecommendationError(
                f"unknown canonical plan identity: {plan_id!r}; "
                "only plans produced by this recommendation can be chosen"
            )
        if plan_id not in selection.plan_ids:
            raise RecommendationError(
                f"plan {plan_id!r} was not ranked by recommendation "
                f"{recommendation_id!r}; choose one of its ranked plans"
            )
        return plan

    # -- internals -----------------------------------------------------------

    def _evidence_for(
        self,
        candidate: Candidate,
        model: ModelCatalogEntry,
        budget: HardwareBudget,
    ) -> tuple[MetricEvidence, ...]:
        items: list[MetricEvidence] = []
        measured = self._latest_run(candidate)
        now = self._now()
        if measured is not None:
            run, summary = measured
            confidence = 1.0
            freshness = run.ended_at.isoformat() if run.ended_at else None
            if freshness is not None and _age_days(freshness, now) > STALE_AFTER_DAYS:
                confidence = ESTIMATED_CONFIDENCE_CAP
            measured_evidence = _measured_metric(
                confidence=confidence,
                source=run.run_id,
                machine_id=run.identity.machine_id,
                freshness=freshness,
            )
            if summary.ttft_seconds is not None:
                items.append(
                    measured_evidence("time_to_first_token", summary.ttft_seconds * 1000.0)
                )
            if summary.tokens_per_second is not None:
                items.append(measured_evidence("decode_throughput", summary.tokens_per_second))
        items.extend(_estimated_evidence(candidate, model, budget))
        return tuple(items)

    def _latest_run(self, candidate: Candidate) -> tuple[CampaignRun, BenchmarkSummary] | None:
        best: tuple[CampaignRun, BenchmarkSummary] | None = None
        for run, summary in self._evidence.completed_runs():
            identity = run.identity
            if (identity.model_id, identity.quantization, identity.engine_id) != (
                candidate.model_id,
                candidate.quantization,
                candidate.engine_id,
            ):
                continue
            if (
                identity.context_window is not None
                and identity.context_window != candidate.context_window
            ):
                continue
            if best is None or _run_order(run) > _run_order(best[0]):
                best = (run, summary)
        return best

    def _materialize_plan(
        self,
        candidate: Candidate,
        model: ModelCatalogEntry,
        engine: EngineCatalogEntry,
        *,
        policy: WorkloadPolicy,
        budget: HardwareBudget,
        catalog_digest: str,
    ) -> DeploymentPlan:
        estimate = estimate_resource_use(model, candidate, budget)
        workload = WorkloadProfile(
            workload_id=f"workload-{policy.id}",
            developer_profile=policy.id,
            context_tokens=policy.context_tokens,
            max_concurrency=policy.concurrency,
            required_features=policy.features,
        )
        model_identity = ModelIdentity(
            model_id=model.id,
            revision=model.revision or "retained",
            artifact_digest=model.source_digest
            or sha256_hex(f"morpheus:model:{model.id}".encode()),
            model_format=model.formats[0],
            quantization=candidate.quantization,
            license_id=model.license,
            source="retained-catalog",
        )
        engine_identity = EngineIdentity(
            engine_id=engine.id,
            kind=engine.id,
            artifact_digest=engine.source_digest
            or sha256_hex(f"morpheus:engine:{engine.id}".encode()),
            platforms=engine.platforms,
        )
        settings = (
            ("context_length", candidate.context_window),
            ("concurrency", candidate.concurrency),
        )
        plan_id = _plan_id(
            model_identity=model_identity,
            engine_identity=engine_identity,
            workload=workload,
            settings=settings,
            context_tokens=candidate.context_window,
            max_concurrency=candidate.concurrency,
            memory_estimate_bytes=estimate.ram_with_margin(),
            disk_estimate_bytes=estimate.storage_bytes,
        )
        return DeploymentPlan(
            plan_id=plan_id,
            model=model_identity,
            engine=engine_identity,
            workload=workload,
            settings=settings,
            served_aliases=(candidate.model_id,),
            context_tokens=candidate.context_window,
            max_concurrency=candidate.concurrency,
            cache_policy=PLAN_CACHE_POLICY,
            memory_estimate_bytes=estimate.ram_with_margin(),
            disk_estimate_bytes=estimate.storage_bytes,
            owned_paths=PLAN_OWNED_PATHS,
            ports=PLAN_PORTS,
            health_contract_id=PLAN_HEALTH_CONTRACT,
            benchmark_gate_id=PLAN_BENCHMARK_GATE,
            rollback_target_plan_id=None,
            source_evidence_digest=catalog_digest,
        )

    def _now(self) -> datetime:
        if self._clock is None:
            return datetime.now(UTC)
        return self._clock.utc_now()


def _measured_metric(
    *, confidence: float, source: str, machine_id: str, freshness: str | None
) -> Callable[[str, float], MetricEvidence]:
    """Builder for one run's measured evidence; ranking calibrates TTFT in ms."""

    def build(metric: str, value: float) -> MetricEvidence:
        return MetricEvidence(
            metric=metric,
            value=value,
            confidence=confidence,
            provenance="measured",
            source=source,
            machine_id=machine_id,
            freshness=freshness,
        )

    return build


def _estimated_evidence(
    candidate: Candidate, model: ModelCatalogEntry, budget: HardwareBudget
) -> tuple[MetricEvidence, ...]:
    """Honest resource-estimate evidence; never invents benchmark values."""
    estimate = estimate_resource_use(model, candidate, budget)
    headroom = max(0.0, 1.0 - estimate.ram_with_margin() / budget.ram_bytes)
    cost = min(1.0, estimate.ram_with_margin() / budget.ram_bytes)
    return (
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


def _plan_id(
    *,
    model_identity: ModelIdentity,
    engine_identity: EngineIdentity,
    workload: WorkloadProfile,
    settings: tuple[tuple[str, int], ...],
    context_tokens: int,
    max_concurrency: int,
    memory_estimate_bytes: int,
    disk_estimate_bytes: int,
) -> str:
    payload = json.dumps(
        {
            "model": model_identity.public_dict(),
            "engine": engine_identity.public_dict(),
            "workload": workload.public_dict(),
            "settings": [list(pair) for pair in settings],
            "context_tokens": context_tokens,
            "max_concurrency": max_concurrency,
            "cache_policy": PLAN_CACHE_POLICY,
            "memory_estimate_bytes": memory_estimate_bytes,
            "disk_estimate_bytes": disk_estimate_bytes,
            "ports": list(PLAN_PORTS),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"plan-{hashlib.sha256(payload).hexdigest()[:32]}"


def _selection_id(machine_id: str, catalog_digest: str, plans: tuple[DeploymentPlan, ...]) -> str:
    payload = json.dumps(
        {
            "machine_id": machine_id,
            "catalog_digest": catalog_digest,
            "plan_ids": [plan.plan_id for plan in plans],
            "evidence_ranked": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"recommendation-{hashlib.sha256(payload).hexdigest()[:32]}"


def _run_order(run: CampaignRun) -> tuple[datetime, str]:
    ended = run.ended_at or run.started_at
    return (ended, run.run_id)


def _age_days(freshness: str, now: datetime) -> int:
    return (now - datetime.fromisoformat(freshness)).days


__all__ = [
    "BenchmarkEvidencePort",
    "RecommendationOutcome",
    "RecommendationRepositories",
    "RecommendationService",
    "StoreBenchmarkEvidence",
    "catalog_snapshot_digest",
]
