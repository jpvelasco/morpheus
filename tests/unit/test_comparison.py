"""Unit tests: comparability decision tables, regressions, and export."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from morpheus.core.benchmark import (
    BenchmarkSample,
    BenchmarkSummary,
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import CampaignRun
from morpheus.core.comparison import (
    COMPARABLE,
    ESTIMATED,
    INCOMPARABLE,
    ComparisonRecord,
    classification_for,
    compare,
    detect_regressions,
    export_comparison,
)


def identity(**overrides) -> RunIdentity:
    fields = {
        "machine_id": "fixture-machine",
        "model_id": "llama-3.1-8b-instruct",
        "model_revision": "v0.1",
        "quantization": "q8_0",
        "engine_id": "llama.cpp",
        "engine_version": "0.1.0",
        "benchmark_revision": "bench-2026.2",
    }
    fields.update(overrides)
    return RunIdentity(**fields)


def declaration() -> CampaignDeclaration:
    return CampaignDeclaration(
        name="cmp",
        campaign_type="speed",
        benchmark_revision="bench-2026.2",
        duration_seconds=60,
        concurrency=1,
        ownership_target="DEV",
    )


def run(run_id: str, ident: RunIdentity) -> CampaignRun:
    return CampaignRun(
        run_id=run_id,
        declaration=declaration(),
        identity=ident,
        started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        status="completed",
    )


def summary(run_id: str, tps: float, ttft: float, count: int = 10) -> BenchmarkSummary:
    return BenchmarkSummary(
        run_id=run_id,
        sample_count=count,
        statistic="p50",
        ttft_seconds=ttft,
        tokens_per_second=tps,
        run_variation=(("tokens_per_second", 0.5), ("ttft_seconds", 0.05)),
    )


def samples(run_id: str, count: int, tps: float) -> tuple[BenchmarkSample, ...]:
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
        for index in range(count)
    )


class TestClassification:
    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            ({}, COMPARABLE),
            ({"machine_id": "other-host"}, ESTIMATED),
            ({"model_id": "qwen2.5-7b-instruct"}, INCOMPARABLE),
            ({"quantization": "q4_0"}, INCOMPARABLE),
            ({"engine_id": "vllm"}, INCOMPARABLE),
            ({"benchmark_revision": "bench-2026.1"}, INCOMPARABLE),
        ],
    )
    def test_decision_table(self, candidate: dict, expected: str) -> None:
        assert classification_for(identity(), identity(**candidate)) == expected


class TestCompare:
    def test_comparable_delta(self) -> None:
        record = compare(
            run("base", identity()),
            run("cand", identity()),
            summary("base", 40.0, 0.2),
            summary("cand", 44.0, 0.18),
        )
        assert record.classification == COMPARABLE
        assert record.percent_change == pytest.approx(10.0)
        assert record.metric == "tokens_per_second"

    def test_estimated_foreign_machine_still_reports_delta(self) -> None:
        record = compare(
            run("base", identity()),
            run("cand", identity(machine_id="other-host")),
            summary("base", 40.0, 0.2),
            summary("cand", 44.0, 0.18),
        )
        assert record.classification == ESTIMATED
        assert record.percent_change == pytest.approx(10.0)
        assert "different machine" in record.note

    def test_incomparable_no_percentage(self) -> None:
        record = compare(
            run("base", identity()),
            run("cand", identity(model_id="qwen2.5-7b-instruct")),
            summary("base", 40.0, 0.2),
            summary("cand", 60.0, 0.1),
        )
        assert record.classification == INCOMPARABLE
        assert record.percent_change is None
        assert "apples-to-oranges" in record.note
        assert "model_id" in record.note

    def test_ttft_metric_used(self) -> None:
        record = compare(
            run("base", identity()),
            run("cand", identity()),
            summary("base", 40.0, 0.2),
            summary("cand", 44.0, 0.18),
            metric="ttft_seconds",
        )
        assert record.percent_change == pytest.approx(-10.0)

    def test_unknown_metric_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown comparison metric"):
            compare(
                run("base", identity()),
                run("cand", identity()),
                summary("base", 40.0, 0.2),
                summary("cand", 44.0, 0.18),
                metric="latency",
            )

    def test_round_trip_via_dict_fields(self) -> None:
        record = compare(
            run("base", identity()),
            run("cand", identity()),
            summary("base", 40.0, 0.2),
            summary("cand", 44.0, 0.18),
        )
        exported = export_comparison(record)
        assert exported["percent_change"] == pytest.approx(10.0)
        assert exported["classification"] == COMPARABLE


class TestRegressions:
    def test_tps_regression_detected(self) -> None:
        regressions = detect_regressions(summary("base", 40.0, 0.2), summary("cand", 30.0, 0.2))
        metrics = [regression.metric for regression in regressions]
        assert "tokens_per_second" in metrics
        found = next(
            regression for regression in regressions if regression.metric == "tokens_per_second"
        )
        assert found.change_pct == pytest.approx(-25.0)

    def test_ttft_regression_detected(self) -> None:
        regressions = detect_regressions(summary("base", 40.0, 0.2), summary("cand", 40.0, 0.3))
        metrics = [regression.metric for regression in regressions]
        assert "ttft_seconds" in metrics

    def test_improvement_not_regression(self) -> None:
        regressions = detect_regressions(summary("base", 40.0, 0.2), summary("cand", 44.0, 0.18))
        assert regressions == ()

    def test_threshold_respected(self) -> None:
        small = detect_regressions(
            summary("base", 40.0, 0.2), summary("cand", 39.0, 0.2), threshold_pct=5.0
        )
        assert small == ()
        tight = detect_regressions(
            summary("base", 40.0, 0.2), summary("cand", 39.0, 0.2), threshold_pct=1.0
        )
        assert any(regression.metric == "tokens_per_second" for regression in tight)

    def test_missing_metrics_skipped(self) -> None:
        sparse = BenchmarkSummary(
            run_id="cand",
            sample_count=3,
            statistic="p50",
            tokens_per_second=30.0,
        )
        regressions = detect_regressions(summary("base", 40.0, 0.2), sparse)
        assert [regression.metric for regression in regressions] == ["tokens_per_second"]


class TestExport:
    REQUIRED = (
        "baseline_run_id",
        "candidate_run_id",
        "classification",
        "classification_note",
        "metric",
        "statistic",
        "baseline",
        "candidate",
        "percent_change",
    )

    @pytest.mark.parametrize("classification", (COMPARABLE, ESTIMATED, INCOMPARABLE))
    def test_export_never_bare_percentage(self, classification: str) -> None:
        candidate = (
            identity(model_id="qwen2.5-7b-instruct")
            if classification == INCOMPARABLE
            else identity()
        )
        if classification == ESTIMATED:
            candidate = identity(machine_id="other-host")
        record = compare(
            run("base", identity()),
            run("cand", candidate),
            summary("base", 40.0, 0.2),
            summary("cand", 44.0, 0.18),
        )
        exported = export_comparison(record)
        assert record.classification == classification
        for key in self.REQUIRED:
            assert key in exported
        assert exported["baseline"]["sample_count"] >= 0
        assert exported["baseline"]["run_variation"] is not None
        assert exported["candidate"]["sample_count"] >= 0
        if classification == INCOMPARABLE:
            assert exported["percent_change"] is None
        else:
            assert exported["percent_change"] is not None

    def test_export_completeness_from_real_summary(self) -> None:
        real = summarize_samples("run-1", samples("run-1", 5, 40.0))
        exported = export_comparison(
            compare(
                run("base", identity()),
                run("cand", identity()),
                real,
                summarize_samples("run-1", samples("run-1", 5, 42.0)),
            )
        )
        assert exported["baseline"]["sample_count"] == 5
        assert exported["candidate"]["run_variation"] is not None
        assert exported["statistic"] == "p50"

    def test_comparison_record_is_immutable(self) -> None:
        record = compare(
            run("base", identity()),
            run("cand", identity()),
            summary("base", 40.0, 0.2),
            summary("cand", 44.0, 0.18),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.percent_change = 0.0
        assert isinstance(record, ComparisonRecord)
