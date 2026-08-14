"""Contract tests: comparison, regression, and cross-host review (BENCH-004)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from morpheus.core.benchmark import (
    BenchmarkSample,
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import BenchmarkStore, CampaignRun
from morpheus.core.campaign import authorization_token, run_campaign
from morpheus.core.comparison import (
    COMPARABLE,
    ESTIMATED,
    INCOMPARABLE,
    compare,
    detect_regressions,
    export_comparison,
)

pytestmark = pytest.mark.contract


def _identity(
    machine_id: str = "fixture-machine", model_id: str = "llama-3.1-8b-instruct"
) -> RunIdentity:
    return RunIdentity(
        machine_id=machine_id,
        model_id=model_id,
        model_revision="v0.1",
        quantization="q8_0",
        engine_id="llama.cpp",
        engine_version="0.1.0",
        benchmark_revision="bench-2026.2",
    )


def _declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="contract-cmp",
        campaign_type="speed",
        benchmark_revision="bench-2026.2",
        duration_seconds=60,
        concurrency=1,
        ownership_target="DEV",
        stop_conditions=(("target_samples", 6),),
    )


def _run(run_id: str, ident: RunIdentity) -> CampaignRun:
    return CampaignRun(
        run_id=run_id,
        declaration=_declaration(),
        identity=ident,
        started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        status="completed",
    )


def _sample(ctx, index: int) -> BenchmarkSample:
    return BenchmarkSample(
        run_id=ctx.run_id,
        started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
        sequence_index=index,
        duration_seconds=0.1,
        ttft_seconds=0.05,
        tokens_per_second=30.0 + index,
        generated_tokens=16,
    )


def test_public_boundary_compare_across_machines(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    base = run_campaign(
        _declaration(),
        _identity(),
        _sample,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="cmp-base",
    )
    cand = run_campaign(
        _declaration(),
        _identity(machine_id="other-host"),
        _sample,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="cmp-cand",
    )
    base_samples = store.load_samples("cmp-base")
    cand_samples = store.load_samples("cmp-cand")
    record = compare(
        base,
        cand,
        summarize_samples("cmp-base", base_samples),
        summarize_samples("cmp-cand", cand_samples),
    )
    assert record.classification == ESTIMATED
    exported = export_comparison(record)
    assert exported["classification"] == ESTIMATED
    assert "different machine" in exported["classification_note"]
    assert exported["percent_change"] is not None
    assert exported["baseline"]["sample_count"] == 6
    assert exported["candidate"]["sample_count"] == 6
    assert exported["statistic"] == "p50"


def test_apples_to_oranges_never_shows_percentage(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    base = run_campaign(
        _declaration(),
        _identity(),
        _sample,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="cmp-o-base",
    )
    cand = run_campaign(
        _declaration(),
        _identity(machine_id="x", model_id="qwen2.5-7b-instruct"),
        _sample,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="cmp-o-cand",
    )
    record = compare(
        base,
        cand,
        summarize_samples("cmp-o-base", store.load_samples("cmp-o-base")),
        summarize_samples("cmp-o-cand", store.load_samples("cmp-o-cand")),
    )
    assert record.classification == INCOMPARABLE
    assert export_comparison(record)["percent_change"] is None


def test_same_host_compare_is_direct(tmp_path) -> None:
    store = BenchmarkStore(tmp_path)
    base = run_campaign(
        _declaration(),
        _identity(),
        _sample,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="cmp-d-base",
    )
    cand = run_campaign(
        _declaration(),
        _identity(),
        _sample,
        store,
        authorized=authorization_token(),
        ownership_target="DEV",
        run_id="cmp-d-cand",
    )
    record = compare(
        base,
        cand,
        summarize_samples("cmp-d-base", store.load_samples("cmp-d-base")),
        summarize_samples("cmp-d-cand", store.load_samples("cmp-d-cand")),
    )
    assert record.classification == COMPARABLE


def test_regression_detection_reports_variation_context() -> None:
    base = summarize_samples("base", _samples_fixed("base", 30.0))
    cand = summarize_samples("cand", _samples_fixed("cand", 24.0))
    regressions = detect_regressions(base, cand, threshold_pct=10.0)
    assert any(r.metric == "tokens_per_second" for r in regressions)
    regression = next(r for r in regressions if r.metric == "tokens_per_second")
    assert regression.change_pct == pytest.approx(-20.0)
    assert regression.baseline_value == pytest.approx(30.0)
    assert regression.candidate_value == pytest.approx(24.0)


def _samples_fixed(run_id: str, tps: float) -> tuple[BenchmarkSample, ...]:
    return tuple(
        BenchmarkSample(
            run_id=run_id,
            started_at=datetime(2026, 8, 1, 12, 0, index, tzinfo=UTC),
            sequence_index=index,
            duration_seconds=1.0,
            ttft_seconds=0.2,
            tokens_per_second=tps,
            generated_tokens=32,
        )
        for index in range(4)
    )
