"""Analytics and comparison summaries over benchmark and telemetry evidence (OUI-004).

Every comparison carries its classification and sample counts; regressions are
only reported between directly comparable runs on the same configuration.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from morpheus.core.benchmark import BenchmarkSummary
from morpheus.core.benchstore import CampaignRun
from morpheus.core.comparison import COMPARABLE, compare, detect_regressions, export_comparison

SUCCESS_OUTCOME = "success"
CANCELED_OUTCOME = "canceled"
ERROR_OUTCOMES = frozenset(
    {
        "invalid_upstream_response",
        "upstream_connection_error",
        "upstream_http_error",
        "upstream_protocol_error",
        "upstream_timeout",
        "upstream_unreachable",
    }
)

#: The identity fields that make two runs the same configuration.
_IDENTITY_FIELDS = (
    "model_id",
    "quantization",
    "engine_id",
    "benchmark_revision",
)


@dataclass(frozen=True, slots=True)
class UsageSummary:
    requests: int
    successes: int
    cancellations: int
    errors: int
    prompt_tokens: int
    completion_tokens: int
    window_days: int


def usage_summary(records: Sequence[Mapping[str, Any]], *, window_days: int) -> UsageSummary:
    requests = len(records)
    successes = sum(record.get("outcome") == SUCCESS_OUTCOME for record in records)
    cancellations = sum(record.get("outcome") == CANCELED_OUTCOME for record in records)
    errors = requests - successes - cancellations
    prompt_tokens = sum(int(record.get("prompt_tokens") or 0) for record in records)
    completion_tokens = sum(int(record.get("completion_tokens") or 0) for record in records)
    return UsageSummary(
        requests=requests,
        successes=successes,
        cancellations=cancellations,
        errors=errors,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        window_days=window_days,
    )


def scorecard(summary: BenchmarkSummary, run: CampaignRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "model_id": run.identity.model_id,
        "engine_id": run.identity.engine_id,
        "quantization": run.identity.quantization,
        "statistic": summary.statistic,
        "sample_count": summary.sample_count,
        "ttft_seconds": summary.ttft_seconds,
        "tokens_per_second": summary.tokens_per_second,
    }


def analytics_report(
    *,
    runs: Sequence[CampaignRun],
    summaries: Mapping[str, BenchmarkSummary],
    telemetry: Sequence[Mapping[str, Any]],
    window_days: int,
) -> dict[str, Any]:
    """Build the analytics workspace payload from stored evidence.

    Completed runs with summaries are chained in start order: each run is
    compared against its direct predecessor, and regressions are reported only
    for directly comparable chains.
    """
    usage = usage_summary(telemetry, window_days=window_days)
    completed = sorted(
        (run for run in runs if run.status == "completed" and run.run_id in summaries),
        key=lambda item: item.started_at,
    )
    scorecards_list = [scorecard(summaries[run.run_id], run) for run in completed]
    comparisons: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for previous, candidate in itertools.pairwise(completed):
        baseline = summaries[previous.run_id]
        candidate_summary = summaries[candidate.run_id]
        record = compare(previous, candidate, baseline, candidate_summary)
        comparisons.append(export_comparison(record))
        if record.classification == COMPARABLE:
            regressions.extend(
                asdict(regression) for regression in detect_regressions(baseline, candidate_summary)
            )
    return {
        "usage": asdict(usage),
        "scorecards": scorecards_list,
        "comparisons": comparisons,
        "regressions": regressions,
    }
