"""Unit tests for the R2 evidence-backed recommendation service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from morpheus.adapters.persistence.records_store import RecordsStore
from morpheus.core.benchmark import BenchmarkSummary, CampaignDeclaration, RunIdentity
from morpheus.core.benchstore import BenchmarkStore, CampaignRun, sha256_hex
from morpheus.core.catalog import CatalogCollection, EngineCatalogEntry, ModelCatalogEntry
from morpheus.core.recommendation import RecommendationError
from morpheus.core.solver import HardwareBudget
from morpheus.core.workload import OperatorConstraints, WorkloadPolicy
from morpheus.ops.planning import machine_profile_from_budget
from morpheus.ops.recommendation import (
    RecommendationService,
    StoreBenchmarkEvidence,
    catalog_snapshot_digest,
)

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
BUDGET = HardwareBudget(
    ram_bytes=4 * 1024**3, vram_bytes=0, storage_bytes=16 * 1024**3, accelerator="cpu"
)
OPERATOR = OperatorConstraints(max_concurrency=1)


def _policy() -> WorkloadPolicy:
    return WorkloadPolicy(
        id="unit-default",
        version="1",
        name="Unit default",
        weights=(("time_to_first_token", 0.6), ("decode_throughput", 0.4)),
        features=("tool_calling",),
        context_tokens=4096,
        concurrency=1,
    )


def _catalog() -> CatalogCollection:
    model = ModelCatalogEntry(
        id="model-unit-a",
        name="Unit model A",
        license="mit",
        architecture="transformer",
        modalities=("text",),
        formats=("gguf",),
        quantizations=("q4_k_m",),
        context_window=4096,
        artifact_size_bytes=64 * 1024**2,
        revision="u1",
        engine_support=("engine-unit",),
        features=("tool_calling",),
    )
    engine = EngineCatalogEntry(
        id="engine-unit",
        name="Unit engine",
        license="mit",
        version="1.0.0",
        platforms=("linux-x86_64",),
        features=("tool_calling",),
    )
    return CatalogCollection(version="unit-0001", models=(model,), engines=(engine,))


def _records_with_catalog(tmp_path: Any) -> tuple[RecordsStore, str]:
    records = RecordsStore(tmp_path / "records")
    records.initialize()
    collection = _catalog()
    digest = catalog_snapshot_digest(collection)
    records.save_catalog_snapshot(digest, collection.to_dict())
    machine = machine_profile_from_budget(BUDGET)
    records.save_machine_profile(machine)
    return records, digest


def _run(run_id: str, *, context_window: int | None) -> CampaignRun:
    identity = RunIdentity(
        machine_id=machine_profile_from_budget(BUDGET).machine_id,
        model_id="model-unit-a",
        model_revision="u1",
        quantization="q4_k_m",
        engine_id="engine-unit",
        engine_version="1.0.0",
        benchmark_revision="bench-u",
        context_window=context_window,
    )
    started = datetime(2026, 8, 20, tzinfo=UTC)
    return CampaignRun(
        run_id=run_id,
        declaration=CampaignDeclaration(
            name=run_id,
            campaign_type="speed",
            benchmark_revision="bench-u",
            duration_seconds=30,
            concurrency=1,
            ownership_target="managed",
        ),
        identity=identity,
        started_at=started,
        ended_at=started.replace(hour=1),
        status="completed",
    )


class StaticEvidence:
    def __init__(self, pairs: tuple[tuple[CampaignRun, BenchmarkSummary], ...]) -> None:
        self._pairs = pairs

    def completed_runs(self) -> tuple[tuple[CampaignRun, BenchmarkSummary], ...]:
        return self._pairs


def _service(
    records: RecordsStore, pairs: tuple[tuple[CampaignRun, BenchmarkSummary], ...] = ()
) -> RecommendationService:
    from morpheus.adapters.fakes import FakeClock

    return RecommendationService(
        records=records, evidence=StaticEvidence(pairs), clock=FakeClock(now=NOW)
    )


def test_preview_rejects_missing_machine_profile(tmp_path: Any) -> None:
    records, digest = _records_with_catalog(tmp_path)
    service = _service(records)
    with pytest.raises(RecommendationError, match="not retained"):
        service.preview(
            machine_id="machine-absent",
            catalog_digest=digest,
            policy=_policy(),
            budget=BUDGET,
            operator=OPERATOR,
        )


def test_preview_rejects_unretained_catalog_instead_of_seeding(tmp_path: Any) -> None:
    records, _ = _records_with_catalog(tmp_path)
    service = _service(records)
    absent = sha256_hex(b"absent-catalog")
    with pytest.raises(RecommendationError, match="seed the catalog"):
        service.preview(
            machine_id=machine_profile_from_budget(BUDGET).machine_id,
            catalog_digest=absent,
            policy=_policy(),
            budget=BUDGET,
            operator=OPERATOR,
        )


def test_latest_run_ignores_context_window_mismatch(tmp_path: Any) -> None:
    records, digest = _records_with_catalog(tmp_path)
    mismatched = (
        _run("run-context-mismatch", context_window=16384),
        BenchmarkSummary(
            run_id="run-context-mismatch",
            sample_count=4,
            statistic="p50",
            ttft_seconds=0.01,
        ),
    )
    service = _service(records, (mismatched,))
    outcome = service.preview(
        machine_id=machine_profile_from_budget(BUDGET).machine_id,
        catalog_digest=digest,
        policy=_policy(),
        budget=BUDGET,
        operator=OPERATOR,
    )
    contributions = outcome.record.ranked[0].contributions
    ttft = next(item for item in contributions if item.metric == "time_to_first_token")
    # The run exists but measured a different context: no measured evidence.
    assert ttft.comparability == "missing"
    assert ttft.source == ""


def test_choose_rejects_unknown_recommendation_unknown_plan_and_non_ranked_plan(
    tmp_path: Any,
) -> None:
    records, digest = _records_with_catalog(tmp_path)
    service = _service(records)
    machine_id = machine_profile_from_budget(BUDGET).machine_id
    outcome = service.preview(
        machine_id=machine_id,
        catalog_digest=digest,
        policy=_policy(),
        budget=BUDGET,
        operator=OPERATOR,
    )

    with pytest.raises(RecommendationError, match="unknown recommendation identity"):
        service.choose(recommendation_id="recommendation-nope", plan_id=outcome.plans[0].plan_id)

    foreign_plan_id = "plan-" + "f" * 32
    with pytest.raises(RecommendationError, match="unknown canonical plan"):
        service.choose(
            recommendation_id=outcome.selection.recommendation_id, plan_id=foreign_plan_id
        )

    # A stored-but-never-ranked plan is rejected by membership, not identity.
    other = _materializable_plan("plan-" + "e" * 32)
    records.save_plan(other)
    with pytest.raises(RecommendationError, match="was not ranked"):
        service.choose(
            recommendation_id=outcome.selection.recommendation_id,
            plan_id=other.plan_id,
        )


def _materializable_plan(plan_id: str) -> Any:
    from morpheus.core.records import (
        DeploymentPlan,
        EngineIdentity,
        ModelIdentity,
        WorkloadProfile,
    )

    return DeploymentPlan(
        plan_id=plan_id,
        model=ModelIdentity(
            model_id="model-unit-a",
            revision="u1",
            artifact_digest=sha256_hex(b"model"),
            model_format="gguf",
            quantization="q4_k_m",
            license_id="mit",
            source="retained-catalog",
        ),
        engine=EngineIdentity(
            engine_id="engine-unit",
            kind="engine-unit",
            artifact_digest=sha256_hex(b"engine"),
            platforms=("linux-x86_64",),
        ),
        workload=WorkloadProfile(
            workload_id="workload-unit-default",
            developer_profile="unit-default",
            context_tokens=4096,
            max_concurrency=1,
            required_features=("tool_calling",),
        ),
        settings=(("context_length", 4096),),
        served_aliases=("model-unit-a",),
        context_tokens=4096,
        max_concurrency=1,
        cache_policy="owned-cache",
        memory_estimate_bytes=1024**3,
        disk_estimate_bytes=64 * 1024**2,
        owned_paths=("/opt/morpheus/plans",),
        ports=(8080,),
        health_contract_id="health-openai-compatible-0001",
        benchmark_gate_id="gate-recommendation-0001",
        rollback_target_plan_id=None,
        source_evidence_digest=sha256_hex(b"catalog"),
    )


def test_store_evidence_adapter_skips_incomplete_runs(tmp_path: Any) -> None:
    store = BenchmarkStore(tmp_path / "benchmarks")
    store.initialize()
    started = _run("run-adapter-started", context_window=None)
    incomplete = CampaignRun(
        run_id=started.run_id,
        declaration=started.declaration,
        identity=started.identity,
        started_at=started.started_at,
        ended_at=None,
        status="started",
    )
    store.store_run(incomplete)
    # A summary without its run stays invisible as well.
    store.store_summary(
        BenchmarkSummary(
            run_id="run-orphan-summary",
            sample_count=1,
            statistic="p50",
            ttft_seconds=0.02,
        )
    )
    adapter = StoreBenchmarkEvidence(store)
    assert adapter.completed_runs() == ()

    # A completed run whose summary was never stored is skipped, not fatal.
    completed = _run("run-no-summary", context_window=None)
    completed_store = BenchmarkStore(tmp_path / "benchmarks-empty")
    completed_store.initialize()
    completed_store.store_run(completed)
    assert StoreBenchmarkEvidence(completed_store).completed_runs() == ()


def test_latest_run_prefers_the_most_recent_completed_run(tmp_path: Any) -> None:
    records, digest = _records_with_catalog(tmp_path)
    older = (
        _run("run-older", context_window=4096),
        BenchmarkSummary(run_id="run-older", sample_count=4, statistic="p50", ttft_seconds=9.9),
    )
    newer = (
        CampaignRun(
            run_id="run-newer",
            declaration=older[0].declaration,
            identity=older[0].identity,
            started_at=older[0].started_at,
            ended_at=older[0].ended_at.replace(hour=2),
            status="completed",
        ),
        BenchmarkSummary(run_id="run-newer", sample_count=4, statistic="p50", ttft_seconds=0.02),
    )
    service = _service(records, (older, newer))
    outcome = service.preview(
        machine_id=machine_profile_from_budget(BUDGET).machine_id,
        catalog_digest=digest,
        policy=_policy(),
        budget=BUDGET,
        operator=OPERATOR,
    )
    ttft = next(
        item
        for item in outcome.record.ranked[0].contributions
        if item.metric == "time_to_first_token"
    )
    assert ttft.source == "run-newer"


def test_service_without_clock_uses_wall_clock_provenance(tmp_path: Any) -> None:
    records, digest = _records_with_catalog(tmp_path)
    service = RecommendationService(records=records, evidence=StaticEvidence(()))
    outcome = service.preview(
        machine_id=machine_profile_from_budget(BUDGET).machine_id,
        catalog_digest=digest,
        policy=_policy(),
        budget=BUDGET,
        operator=OPERATOR,
    )
    assert outcome.record.created_at.tzinfo is not None


def test_run_without_end_time_still_yields_measured_evidence(tmp_path: Any) -> None:
    records, digest = _records_with_catalog(tmp_path)
    base = _run("run-open-ended", context_window=4096)
    open_ended = CampaignRun(
        run_id=base.run_id,
        declaration=base.declaration,
        identity=base.identity,
        started_at=base.started_at,
        ended_at=None,
        status="completed",
    )
    service = _service(
        records,
        (
            (
                open_ended,
                BenchmarkSummary(
                    run_id="run-open-ended", sample_count=2, statistic="p50", ttft_seconds=0.03
                ),
            ),
        ),
    )
    outcome = service.preview(
        machine_id=machine_profile_from_budget(BUDGET).machine_id,
        catalog_digest=digest,
        policy=_policy(),
        budget=BUDGET,
        operator=OPERATOR,
    )
    ttft = next(
        item
        for item in outcome.record.ranked[0].contributions
        if item.metric == "time_to_first_token"
    )
    assert ttft.comparability == "comparable"
    assert ttft.effective_confidence == pytest.approx(1.0)
