"""Evidence-ranked recommendation of viable tuples (SEL-004)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from morpheus.core.solver import Candidate
from morpheus.core.workload import WEIGHT_METRICS, WorkloadPolicy

_DIRECTION: dict[str, str] = {
    "coding_correctness": "higher_is_better",
    "tool_use": "higher_is_better",
    "agentic_behavior": "higher_is_better",
    "long_context_coherence": "higher_is_better",
    "time_to_first_token": "lower_is_better",
    "decode_throughput": "higher_is_better",
    "concurrency": "higher_is_better",
    "stability": "higher_is_better",
    "memory_headroom": "higher_is_better",
    "resource_cost": "lower_is_better",
}

# Absolute calibration bounds per metric: (floor, ceiling) in documented units.
_CALIBRATION: dict[str, tuple[float, float]] = {
    "coding_correctness": (0.0, 1.0),
    "tool_use": (0.0, 1.0),
    "agentic_behavior": (0.0, 1.0),
    "long_context_coherence": (0.0, 1.0),
    "time_to_first_token": (0.0, 5000.0),  # ms
    "decode_throughput": (0.0, 200.0),  # tokens/s
    "concurrency": (0.0, 64.0),
    "stability": (0.0, 1.0),
    "memory_headroom": (0.0, 1.0),
    "resource_cost": (0.0, 1.0),
}

STALE_AFTER_DAYS = 90
ESTIMATED_CONFIDENCE_CAP = 0.5


class RankingError(ValueError):
    """Ranking inputs violate their contract."""


@dataclass(frozen=True, slots=True)
class MetricEvidence:
    """One measured or estimated value for a ranking metric."""

    metric: str
    value: float
    confidence: float = 1.0
    provenance: str = "measured"  # measured | estimated
    source: str = ""
    machine_id: str | None = None  # None when derived from the catalog
    freshness: str | None = None  # ISO timestamp of the measurement

    def __post_init__(self) -> None:
        if self.metric not in WEIGHT_METRICS:
            raise RankingError(f"unknown ranking metric: {self.metric}")
        if not 0 < self.confidence <= 1.0:
            raise RankingError("evidence confidence must be in (0, 1]")
        if self.provenance not in ("measured", "estimated"):
            raise RankingError(f"unknown provenance: {self.provenance}")


@dataclass(frozen=True, slots=True)
class Contribution:
    """Per-metric contribution to a ranking score."""

    metric: str
    weight: float
    calibrated: float
    effective_confidence: float
    contribution: float
    comparability: str  # comparable | incomparable | missing


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: Candidate
    score: float
    contributions: tuple[Contribution, ...]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": {
                "model_id": self.candidate.model_id,
                "quantization": self.candidate.quantization,
                "engine_id": self.candidate.engine_id,
                "context_window": self.candidate.context_window,
                "concurrency": self.candidate.concurrency,
            },
            "score": self.score,
            "contributions": [
                {
                    "metric": item.metric,
                    "weight": item.weight,
                    "calibrated": item.calibrated,
                    "effective_confidence": item.effective_confidence,
                    "contribution": item.contribution,
                    "comparability": item.comparability,
                }
                for item in self.contributions
            ],
            "summary": self.summary,
        }


def calibrated_value(metric: str, value: float) -> float:
    """Normalize an evidence value into [0, 1] using absolute calibration bounds."""
    floor, ceiling = _CALIBRATION[metric]
    raw = (value - floor) / (ceiling - floor) if ceiling > floor else 0.0
    normalized = min(1.0, max(0.0, raw))
    if _DIRECTION[metric] == "lower_is_better":
        return 1.0 - normalized
    return normalized


def effective_confidence(evidence: MetricEvidence) -> float:
    """Cap confidence for estimated or stale evidence."""
    confidence = evidence.confidence
    if evidence.provenance != "measured":
        confidence = min(confidence, ESTIMATED_CONFIDENCE_CAP)
    if evidence.freshness is not None:
        try:
            from datetime import UTC, date, datetime

            measured = date.fromisoformat(evidence.freshness[:10])
            age_days = (datetime.now(UTC).date() - measured).days
        except ValueError:
            age_days = STALE_AFTER_DAYS + 1
        if age_days > STALE_AFTER_DAYS:
            confidence = min(confidence, ESTIMATED_CONFIDENCE_CAP)
    return confidence


def rank_candidates(
    viable: tuple[Candidate, ...],
    *,
    profile: WorkloadPolicy,
    evidence_by_candidate: dict[Candidate, tuple[MetricEvidence, ...]],
    reference_machine_id: str | None = None,
) -> tuple[RankedCandidate, ...]:
    """Rank viable tuples by weighted, calibrated, confidence-aware evidence.

    Only tuples that survived the hard-constraint partition may be ranked; a
    rejected tuple cannot enter this function and therefore cannot re-enter
    through any weight choice. Scores are deterministic: stable sort on score
    descending, then candidate fields.
    """
    scored: list[RankedCandidate] = []
    for candidate in viable:
        evidence = {item.metric: item for item in evidence_by_candidate.get(candidate, ())}
        contributions: list[Contribution] = []
        total = 0.0
        for metric, weight in profile.weights:
            item = evidence.get(metric)
            if item is None:
                contributions.append(
                    Contribution(
                        metric=metric,
                        weight=weight,
                        calibrated=0.0,
                        effective_confidence=0.0,
                        contribution=0.0,
                        comparability="missing",
                    )
                )
                continue
            if (
                item.machine_id is not None
                and reference_machine_id is not None
                and item.machine_id != reference_machine_id
            ):
                contributions.append(
                    Contribution(
                        metric=metric,
                        weight=weight,
                        calibrated=calibrated_value(metric, item.value),
                        effective_confidence=0.0,
                        contribution=0.0,
                        comparability="incomparable",
                    )
                )
                continue
            confidence = effective_confidence(item)
            contribution = calibrated_value(metric, item.value) * confidence
            total += weight * contribution
            contributions.append(
                Contribution(
                    metric=metric,
                    weight=weight,
                    calibrated=calibrated_value(metric, item.value),
                    effective_confidence=confidence,
                    contribution=contribution,
                    comparability="comparable",
                )
            )
        summary = summarize(profile, tuple(contributions))
        scored.append(RankedCandidate(candidate, total, tuple(contributions), summary))
    return tuple(
        sorted(
            scored,
            key=lambda ranked: (
                -ranked.score,
                ranked.candidate.model_id,
                ranked.candidate.quantization,
                ranked.candidate.engine_id,
                ranked.candidate.context_window,
                ranked.candidate.concurrency,
            ),
        )
    )


def summarize(profile: WorkloadPolicy, contributions: tuple[Contribution, ...]) -> str:
    """One-line explanation: strongest metric, weakest metric, incomparables."""
    ranked = sorted(
        (item for item in contributions if item.comparability == "comparable"),
        key=lambda item: item.weight * item.contribution,
        reverse=True,
    )
    parts: list[str] = []
    if ranked:
        strongest = ranked[0]
        weakest = ranked[-1]
        parts.append(f"strongest: {strongest.metric}")
        if weakest.metric != strongest.metric:
            parts.append(f"weakest: {weakest.metric}")
    incomparable = [item.metric for item in contributions if item.comparability == "incomparable"]
    if incomparable:
        parts.append(f"excluded: {', '.join(sorted(incomparable))}")
    return "; ".join(parts) or "no evidence for any profile metric"
