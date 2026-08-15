from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from morpheus.core.analytics import analytics_report, scorecard, usage_summary
from morpheus.core.benchmark import (
    BenchmarkSample,
    BenchmarkSummary,
    CampaignDeclaration,
    RunIdentity,
    summarize_samples,
)
from morpheus.core.benchstore import CampaignRun

NOW = datetime(2026, 8, 1, tzinfo=UTC)

DECLARATION = CampaignDeclaration(
    name="fixture-campaign",
    campaign_type="speed",
    benchmark_revision="rev-1",
    duration_seconds=60,
    concurrency=1,
    ownership_target="external_observed",
)

IDENTITY = RunIdentity(
    machine_id="machine-a",
    model_id="qwen36-27b-nvfp4",
    model_revision="rev-1",
    quantization="nvfp4",
    engine_id="vllm",
    engine_version="0.8",
    benchmark_revision="rev-1",
)


def run(
    run_id: str,
    *,
    started_at: datetime = NOW,
    status: str = "completed",
    identity: RunIdentity = IDENTITY,
) -> CampaignRun:
    return CampaignRun(
        run_id=run_id,
        declaration=DECLARATION,
        identity=identity,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=1),
        status=status,
    )


def summary(run_id: str, *, ttft: float, tokens: float) -> BenchmarkSummary:
    sample = BenchmarkSample(
        run_id=run_id,
        started_at=NOW,
        sequence_index=0,
        ttft_seconds=ttft,
        tokens_per_second=tokens,
        duration_seconds=1.0,
        error=None,
    )
    return summarize_samples(run_id, (sample,))


TELEMETRY = [
    {
        "correlation_id": "c-1",
        "model_requested": "alias",
        "model_reported": "qwen36-27b-nvfp4",
        "started_at": 1.0,
        "first_byte_seconds": 0.2,
        "completed_seconds": 1.0,
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "finish_reason": "stop",
        "outcome": "success",
    },
    {
        "correlation_id": "c-2",
        "model_requested": "alias",
        "model_reported": None,
        "started_at": 2.0,
        "first_byte_seconds": None,
        "completed_seconds": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "finish_reason": None,
        "outcome": "upstream_timeout",
    },
    {
        "correlation_id": "c-3",
        "model_requested": "alias",
        "model_reported": "qwen36-27b-nvfp4",
        "started_at": 3.0,
        "first_byte_seconds": 0.5,
        "completed_seconds": 3.0,
        "prompt_tokens": 5,
        "completion_tokens": 15,
        "finish_reason": "stop",
        "outcome": "canceled",
    },
]


def test_usage_summary_counts_outcomes_and_tokens() -> None:
    usage = usage_summary(TELEMETRY, window_days=30)
    assert usage.requests == 3
    assert usage.successes == 1
    assert usage.cancellations == 1
    assert usage.errors == 1
    assert usage.prompt_tokens == 15
    assert usage.completion_tokens == 35
    assert usage.window_days == 30


def test_usage_summary_treats_unknown_outcomes_as_errors() -> None:
    usage = usage_summary([{"outcome": "mystery"}, {"outcome": "success"}], window_days=7)
    assert usage.requests == 2
    assert usage.errors == 1
    assert usage.successes == 1
    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0


def test_usage_summary_is_empty_for_no_records() -> None:
    usage = usage_summary([], window_days=30)
    assert (usage.requests, usage.successes, usage.errors, usage.prompt_tokens) == (0, 0, 0, 0)


def test_scorecard_carries_identity_and_statistics() -> None:
    card = scorecard(summary("run-1", ttft=0.4, tokens=42.0), run("run-1"))
    assert card == {
        "run_id": "run-1",
        "model_id": "qwen36-27b-nvfp4",
        "engine_id": "vllm",
        "quantization": "nvfp4",
        "statistic": "p50",
        "sample_count": 1,
        "ttft_seconds": 0.4,
        "tokens_per_second": 42.0,
    }


def test_analytics_report_compares_consecutive_same_identity_runs() -> None:
    report = analytics_report(
        runs=(run("run-1", started_at=NOW), run("run-2", started_at=NOW + timedelta(hours=1))),
        summaries={
            "run-1": summary("run-1", ttft=0.4, tokens=42.0),
            "run-2": summary("run-2", ttft=0.5, tokens=40.0),
        },
        telemetry=TELEMETRY,
        window_days=30,
    )
    assert len(report["comparisons"]) == 1
    comparison = report["comparisons"][0]
    assert comparison["baseline_run_id"] == "run-1"
    assert comparison["candidate_run_id"] == "run-2"
    assert comparison["classification"] == "COMPARABLE"
    assert comparison["percent_change"] == pytest.approx(-4.761904, rel=1e-5)
    assert [entry["metric"] for entry in report["regressions"]] == ["ttft_seconds"]
    assert len(report["scorecards"]) == 2


def test_analytics_report_flags_regressions_beyond_threshold() -> None:
    report = analytics_report(
        runs=(run("run-1"), run("run-2", started_at=NOW + timedelta(hours=1))),
        summaries={
            "run-1": summary("run-1", ttft=0.3, tokens=50.0),
            "run-2": summary("run-2", ttft=0.9, tokens=30.0),
        },
        telemetry=[],
        window_days=30,
    )
    metrics = {entry["metric"] for entry in report["regressions"]}
    assert metrics == {"ttft_seconds", "tokens_per_second"}


def test_analytics_report_marks_differing_identity_as_incomparable() -> None:
    other = RunIdentity(
        machine_id="machine-b",
        model_id="qwen36-27b-nvfp4",
        model_revision="rev-1",
        quantization="nvfp4",
        engine_id="llamacpp",
        engine_version="0.1",
        benchmark_revision="rev-1",
    )
    report = analytics_report(
        runs=(run("run-1"), run("run-2", started_at=NOW + timedelta(hours=1), identity=other)),
        summaries={
            "run-1": summary("run-1", ttft=0.4, tokens=42.0),
            "run-2": summary("run-2", ttft=0.3, tokens=50.0),
        },
        telemetry=[],
        window_days=30,
    )
    assert report["comparisons"][0]["classification"] == "INCOMPARABLE"
    assert report["regressions"] == []


def test_analytics_report_marks_cross_machine_runs_as_estimated() -> None:
    other = RunIdentity(
        machine_id="machine-b",
        model_id="qwen36-27b-nvfp4",
        model_revision="rev-1",
        quantization="nvfp4",
        engine_id="vllm",
        engine_version="0.9",
        benchmark_revision="rev-1",
    )
    report = analytics_report(
        runs=(run("run-1"), run("run-2", started_at=NOW + timedelta(hours=1), identity=other)),
        summaries={
            "run-1": summary("run-1", ttft=0.4, tokens=42.0),
            "run-2": summary("run-2", ttft=0.3, tokens=50.0),
        },
        telemetry=[],
        window_days=30,
    )
    comparison = report["comparisons"][0]
    assert comparison["classification"] == "ESTIMATED"
    assert comparison["percent_change"] is not None
    assert report["regressions"] == []


def test_analytics_report_skips_unfinished_runs() -> None:
    report = analytics_report(
        runs=(
            run("run-1", status="completed"),
            run("run-2", started_at=NOW + timedelta(hours=1), status="failed"),
            run("run-3", started_at=NOW + timedelta(hours=2), status="started"),
        ),
        summaries={"run-1": summary("run-1", ttft=0.4, tokens=42.0)},
        telemetry=[],
        window_days=30,
    )
    assert [card["run_id"] for card in report["scorecards"]] == ["run-1"]
    assert report["comparisons"] == []
    assert report["regressions"] == []


def test_analytics_report_is_empty_for_no_evidence() -> None:
    report = analytics_report(runs=(), summaries={}, telemetry=[], window_days=30)
    assert report == {
        "usage": {
            "requests": 0,
            "successes": 0,
            "cancellations": 0,
            "errors": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "window_days": 30,
        },
        "scorecards": [],
        "comparisons": [],
        "regressions": [],
    }


def test_analytics_report_skips_runs_without_summaries() -> None:
    report = analytics_report(
        runs=(run("run-1"), run("run-2", started_at=NOW + timedelta(hours=1))),
        summaries={"run-1": summary("run-1", ttft=0.4, tokens=42.0)},
        telemetry=[],
        window_days=30,
    )
    assert [card["run_id"] for card in report["scorecards"]] == ["run-1"]
    assert report["comparisons"] == []
