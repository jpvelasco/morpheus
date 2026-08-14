"""Comparability, regression detection, and public comparison export (BENCH-004).

Comparisons never present a bare percentage: every exported record carries
sample counts, the statistic, the baseline, configuration, and an explicit
classification (COMPARABLE / ESTIMATED / INCOMPARABLE) with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from morpheus.core.benchmark import BenchmarkSummary, RunIdentity
from morpheus.core.benchstore import CampaignRun

COMPARABLE = "COMPARABLE"
ESTIMATED = "ESTIMATED"
INCOMPARABLE = "INCOMPARABLE"
COMPARISON_CLASSES = (COMPARABLE, ESTIMATED, INCOMPARABLE)

_DIRECTION = {
    "tokens_per_second": "higher_is_better",
    "ttft_seconds": "lower_is_better",
    "duration_seconds": "lower_is_better",
}

_IDENTITY_FIELDS = (
    "model_id",
    "quantization",
    "engine_id",
    "benchmark_revision",
)


def classification_for(baseline: RunIdentity, candidate: RunIdentity) -> str:
    """Classify run pairs: direct, estimated (foreign machine), or invalid."""
    direct = all(
        getattr(baseline, field) == getattr(candidate, field) for field in _IDENTITY_FIELDS
    )
    if not direct:
        return INCOMPARABLE
    if baseline.machine_id != candidate.machine_id:
        return ESTIMATED
    return COMPARABLE


def _percent_change(baseline: float, candidate: float) -> float:
    return (candidate - baseline) / baseline * 100.0


def _worse(metric: str, baseline: float, candidate: float, threshold_pct: float) -> bool:
    change = _percent_change(baseline, candidate)
    if _DIRECTION[metric] == "higher_is_better":
        return change <= -threshold_pct
    return change >= threshold_pct


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    baseline_run_id: str
    candidate_run_id: str
    classification: str
    metric: str
    baseline_value: float | None
    candidate_value: float | None
    percent_change: float | None
    baseline_sample_count: int
    candidate_sample_count: int
    statistic: str
    baseline_run_variation: float | None
    candidate_run_variation: float | None
    note: str


def compare(
    baseline_run: CampaignRun,
    candidate_run: CampaignRun,
    baseline_summary: BenchmarkSummary,
    candidate_summary: BenchmarkSummary,
    metric: str = "tokens_per_second",
) -> ComparisonRecord:
    """Compare two runs on one metric, classifying and explaining the result."""
    if metric not in _DIRECTION:
        raise ValueError(f"unknown comparison metric: {metric}")
    classification = classification_for(baseline_run.identity, candidate_run.identity)
    baseline_value = getattr(baseline_summary, metric)
    candidate_value = getattr(candidate_summary, metric)
    change = None
    if (
        classification != INCOMPARABLE
        and baseline_value is not None
        and candidate_value is not None
    ):
        change = _percent_change(baseline_value, candidate_value)
    if classification == COMPARABLE:
        note = "directly comparable on the same machine and configuration"
    elif classification == ESTIMATED:
        note = "normalized estimate: candidate ran on a different machine"
    else:
        differing = [
            field
            for field in _IDENTITY_FIELDS
            if getattr(baseline_run.identity, field) != getattr(candidate_run.identity, field)
        ]
        note = f"apples-to-oranges: differing {', '.join(differing)}"
    return ComparisonRecord(
        baseline_run_id=baseline_run.run_id,
        candidate_run_id=candidate_run.run_id,
        classification=classification,
        metric=metric,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        percent_change=change,
        baseline_sample_count=baseline_summary.sample_count,
        candidate_sample_count=candidate_summary.sample_count,
        statistic=baseline_summary.statistic,
        baseline_run_variation=_variation(baseline_summary, metric),
        candidate_run_variation=_variation(candidate_summary, metric),
        note=note,
    )


def _variation(summary: BenchmarkSummary, metric: str) -> float | None:
    return dict(summary.run_variation).get(metric)


@dataclass(frozen=True, slots=True)
class Regression:
    metric: str
    baseline_value: float
    candidate_value: float
    threshold_pct: float
    change_pct: float


def detect_regressions(
    baseline: BenchmarkSummary,
    candidate: BenchmarkSummary,
    threshold_pct: float = 5.0,
) -> tuple[Regression, ...]:
    """Report candidate regressions beyond the threshold on comparable metrics."""
    regressions: list[Regression] = []
    for metric in _DIRECTION:
        base = getattr(baseline, metric)
        cand = getattr(candidate, metric)
        if base is None or cand is None:
            continue
        change = _percent_change(base, cand)
        if _worse(metric, base, cand, threshold_pct):
            regressions.append(
                Regression(
                    metric=metric,
                    baseline_value=base,
                    candidate_value=cand,
                    threshold_pct=threshold_pct,
                    change_pct=change,
                )
            )
    return tuple(regressions)


def export_comparison(record: ComparisonRecord) -> dict[str, Any]:
    """Public query boundary: every percentage carries its full context."""
    return {
        "baseline_run_id": record.baseline_run_id,
        "candidate_run_id": record.candidate_run_id,
        "classification": record.classification,
        "classification_note": record.note,
        "metric": record.metric,
        "statistic": record.statistic,
        "baseline": {
            "value": record.baseline_value,
            "sample_count": record.baseline_sample_count,
            "run_variation": record.baseline_run_variation,
        },
        "candidate": {
            "value": record.candidate_value,
            "sample_count": record.candidate_sample_count,
            "run_variation": record.candidate_run_variation,
        },
        "percent_change": record.percent_change,
    }
