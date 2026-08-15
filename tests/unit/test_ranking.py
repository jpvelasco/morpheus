"""Unit tests: evidence-ranked recommendation (SEL-004)."""

import pytest

from morpheus.core.ranking import (
    ESTIMATED_CONFIDENCE_CAP,
    Contribution,
    MetricEvidence,
    RankedCandidate,
    RankingError,
    calibrated_value,
    effective_confidence,
    rank_candidates,
)
from morpheus.core.solver import Candidate
from morpheus.core.workload import SEED_PROFILES

LLAMA_CPP = Candidate(
    model_id="llama-3.1-8b-instruct",
    quantization="q8_0",
    engine_id="llama.cpp",
    context_window=8192,
    concurrency=1,
)
VLLM = Candidate(
    model_id="llama-3.1-8b-instruct",
    quantization="f16",
    engine_id="vllm",
    context_window=8192,
    concurrency=1,
)

PROFILE = SEED_PROFILES[0]


def evidence(
    metric: str,
    value: float,
    *,
    confidence: float = 1.0,
    provenance: str = "measured",
    machine_id: str | None = "ubuntu-1",
    freshness: str | None = "2026-08-01",
) -> MetricEvidence:
    return MetricEvidence(
        metric=metric,
        value=value,
        confidence=confidence,
        provenance=provenance,
        machine_id=machine_id,
        freshness=freshness,
    )


def rank(
    candidates: tuple[Candidate, ...],
    *,
    mapping: dict[Candidate, tuple[MetricEvidence, ...]] | None = None,
    machine_id: str | None = "ubuntu-1",
) -> tuple[RankedCandidate, ...]:
    return rank_candidates(
        candidates,
        profile=PROFILE,
        evidence_by_candidate=mapping or {},
        reference_machine_id=machine_id,
    )


class TestCalibration:
    def test_higher_is_better(self) -> None:
        assert calibrated_value("decode_throughput", 100.0) == pytest.approx(0.5)
        assert calibrated_value("decode_throughput", 200.0) == pytest.approx(1.0)

    def test_lower_is_better(self) -> None:
        assert calibrated_value("time_to_first_token", 0.0) == pytest.approx(1.0)
        assert calibrated_value("time_to_first_token", 2500.0) == pytest.approx(0.5)
        assert calibrated_value("time_to_first_token", 5000.0) == pytest.approx(0.0)

    def test_clamps_out_of_range(self) -> None:
        assert calibrated_value("decode_throughput", 500.0) == pytest.approx(1.0)
        assert calibrated_value("stability", -3.0) == pytest.approx(0.0)

    def test_bounds_are_finite(self) -> None:
        for metric in (
            "coding_correctness",
            "tool_use",
            "agentic_behavior",
            "long_context_coherence",
            "time_to_first_token",
            "decode_throughput",
            "concurrency",
            "stability",
            "memory_headroom",
            "resource_cost",
        ):
            assert calibrated_value(metric, 1.0) >= 0.0


class TestEvidence:
    def test_rejects_unknown_metric(self) -> None:
        with pytest.raises(RankingError):
            MetricEvidence(metric="bogus", value=1.0)

    def test_rejects_bad_confidence(self) -> None:
        with pytest.raises(RankingError):
            MetricEvidence(metric="stability", value=1.0, confidence=0.0)

    def test_rejects_bad_provenance(self) -> None:
        with pytest.raises(RankingError):
            MetricEvidence(metric="stability", value=1.0, provenance="guessed")

    def test_measured_fresh_stays_full(self) -> None:
        assert effective_confidence(evidence("stability", 1.0)) == pytest.approx(1.0)

    def test_estimated_is_capped(self) -> None:
        assert effective_confidence(
            evidence("stability", 1.0, provenance="estimated")
        ) == pytest.approx(ESTIMATED_CONFIDENCE_CAP)

    def test_stale_is_capped(self) -> None:
        assert effective_confidence(
            evidence("stability", 1.0, freshness="2020-01-01")
        ) == pytest.approx(ESTIMATED_CONFIDENCE_CAP)

    def test_malformed_freshness_is_stale(self) -> None:
        assert effective_confidence(
            evidence("stability", 1.0, freshness="not-a-date")
        ) == pytest.approx(ESTIMATED_CONFIDENCE_CAP)


class TestRanking:
    def test_better_evidence_ranks_higher(self) -> None:
        fast = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 120.0),)},
        )[0]
        slow = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 20.0),)},
        )[0]
        assert fast.score > slow.score

    def test_higher_value_never_lowers_score(self) -> None:
        low = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 20.0),)},
        )[0]
        high = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 150.0),)},
        )[0]
        assert high.score >= low.score

    def test_confidence_dilutes_score(self) -> None:
        certain = rank(
            (LLAMA_CPP,),
            mapping={
                LLAMA_CPP: (
                    evidence("decode_throughput", 100.0),
                    evidence("stability", 1.0),
                )
            },
        )[0]
        diluted = rank(
            (LLAMA_CPP,),
            mapping={
                LLAMA_CPP: (
                    evidence("decode_throughput", 100.0, provenance="estimated"),
                    evidence("stability", 1.0, provenance="estimated"),
                )
            },
        )[0]
        assert diluted.score <= certain.score

    def test_incomparable_machine_contributes_zero(self) -> None:
        result = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 120.0, machine_id="other-host"),)},
        )[0]
        contribution = next(
            item for item in result.contributions if item.metric == "decode_throughput"
        )
        assert contribution.comparability == "incomparable"
        assert contribution.contribution == 0.0
        assert "excluded: decode_throughput" in result.summary

    def test_missing_evidence_contributes_zero(self) -> None:
        result = rank((LLAMA_CPP,))[0]
        assert all(item.contribution == 0.0 for item in result.contributions)
        assert "no evidence" in result.summary

    def test_deterministic_order_and_score(self) -> None:
        mapping = {
            LLAMA_CPP: (evidence("decode_throughput", 50.0),),
            VLLM: (evidence("decode_throughput", 90.0),),
        }
        first = rank((LLAMA_CPP, VLLM), mapping=mapping)
        second = rank((VLLM, LLAMA_CPP), mapping=mapping)
        assert first == second
        assert first[0].candidate == VLLM

    def test_score_within_unit_bounds(self) -> None:
        result = rank(
            (LLAMA_CPP,),
            mapping={
                LLAMA_CPP: (
                    evidence("decode_throughput", 150.0),
                    evidence("stability", 1.0),
                    evidence("coding_correctness", 1.0),
                    evidence("tool_use", 1.0),
                    evidence("agentic_behavior", 1.0),
                    evidence("long_context_coherence", 1.0),
                    evidence("time_to_first_token", 1.0),
                    evidence("concurrency", 64.0),
                    evidence("memory_headroom", 1.0),
                    evidence("resource_cost", 1.0),
                )
            },
        )[0]
        assert 0.0 <= result.score <= 1.0

    def test_ranked_candidate_round_trip(self) -> None:
        result = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 50.0),)},
        )[0]
        payload = result.to_dict()
        assert payload["candidate"]["model_id"] == LLAMA_CPP.model_id
        assert payload["score"] == result.score
        assert payload["summary"] == result.summary

    def test_all_contributions_are_contributions(self) -> None:
        result = rank(
            (LLAMA_CPP,),
            mapping={LLAMA_CPP: (evidence("decode_throughput", 50.0),)},
        )[0]
        assert all(isinstance(item, Contribution) for item in result.contributions)
