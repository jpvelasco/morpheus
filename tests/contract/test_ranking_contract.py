"""Contract tests: evidence-ranked recommendation guarantees (SEL-004).

Guarantees:
- Only viable tuples are ever ranked; rejected tuples cannot re-enter through
  any weight configuration.
- Rankings are deterministic for identical inputs.
- Per-metric monotonicity: improving a higher-is-better evidence value never
  lowers a candidate's score; the same holds inversely for lower-is-better.
- Confidence and calibration are bounded and dilution-safe.
- Incomparable (foreign-machine) evidence is excluded and flagged, never
  silently averaged.
"""

import itertools

import pytest

from morpheus.core.catalog import (
    EngineCatalogEntry,
    ModelCatalogEntry,
)
from morpheus.core.ranking import (
    MetricEvidence,
    rank_candidates,
)
from morpheus.core.solver import (
    Candidate,
    EngineRule,
    HardwareBudget,
    WorkloadRequirements,
    filter_viable,
)
from morpheus.core.workload import (
    SEED_PROFILES,
    WEIGHT_METRICS,
    WorkloadProfile,
)

pytestmark = pytest.mark.contract

LLAMA = ModelCatalogEntry(
    id="llama-3.1-8b-instruct",
    name="Llama 3.1 8B Instruct",
    license="llama3.1",
    architecture="auto",
    modalities=("text",),
    formats=("gguf", "safetensors"),
    quantizations=("q4_0", "q8_0", "f16"),
    context_window=131072,
    artifact_size_bytes=16_000_000_000,
    validation_freshness="2026-02-01T00:00:00+00:00",
    source_url="https://example.invalid/llama3.1-8b",
    source_digest="sha256:" + "a" * 64,
    revision="v1",
    engine_support=("llama.cpp", "vllm"),
    features=("tools", "long-context", "coding", "agentic"),
)

QWEN = ModelCatalogEntry(
    id="qwen2.5-7b-instruct",
    name="Qwen 2.5 7B Instruct",
    license="apache-2.0",
    architecture="auto",
    modalities=("text",),
    formats=("gguf", "safetensors"),
    quantizations=("q4_0", "q8_0", "f16"),
    context_window=131072,
    artifact_size_bytes=15_000_000_000,
    validation_freshness="2026-02-01T00:00:00+00:00",
    source_url="https://example.invalid/qwen2.5-7b",
    source_digest="sha256:" + "b" * 64,
    revision="v1",
    engine_support=("llama.cpp",),
    features=("tools", "coding"),
)

LLAMACPP = EngineCatalogEntry(
    id="llama.cpp",
    name="llama.cpp",
    license="mit",
    version="b4167",
    platforms=("linux", "windows", "macos"),
    features=("gguf", "metal", "cuda", "cpu"),
    released="2026-01-15T00:00:00+00:00",
    source_url="https://example.invalid/llamacpp",
    source_digest="sha256:" + "d" * 64,
)

VLLM = EngineCatalogEntry(
    id="vllm",
    name="vLLM",
    license="apache-2.0",
    version="0.8.5",
    platforms=("linux",),
    features=("safetensors", "cuda"),
    released="2026-01-15T00:00:00+00:00",
    source_url="https://example.invalid/vllm",
    source_digest="sha256:" + "e" * 64,
)

RULES = {
    "llama.cpp": EngineRule(
        engine_id="llama.cpp",
        accelerator="cpu",
        max_context=131072,
        quantizations=("q4_0", "q8_0", "f16"),
    ),
    "vllm": EngineRule(
        engine_id="vllm",
        accelerator="cuda",
        max_context=131072,
        quantizations=("f16",),
    ),
}

MODELS = {"llama-3.1-8b-instruct": LLAMA, "qwen2.5-7b-instruct": QWEN}
ENGINES = {"llama.cpp": LLAMACPP, "vllm": VLLM}

CPU_BUDGET = HardwareBudget(
    ram_bytes=64 * 1024**3,
    storage_bytes=500 * 1024**3,
    accelerator="cpu",
)
CUDA_BUDGET = HardwareBudget(
    ram_bytes=64 * 1024**3,
    vram_bytes=48 * 1024**3,
    storage_bytes=500 * 1024**3,
    accelerator="cuda",
)

CANDIDATES = tuple(
    Candidate(
        model_id=model,
        quantization=quant,
        engine_id=engine,
        context_window=context,
        concurrency=concurrency,
    )
    for model, quant, engine, context, concurrency in itertools.product(
        ("llama-3.1-8b-instruct", "qwen2.5-7b-instruct"),
        ("q8_0", "f16"),
        ("llama.cpp", "vllm"),
        (8192, 65536),
        (1, 4),
    )
)

REQUIREMENTS = WorkloadRequirements(context_tokens=8192, concurrency=1)


def evidence(
    metric: str,
    value: float,
    *,
    provenance: str = "measured",
    machine_id: str | None = "ubuntu-1",
) -> MetricEvidence:
    return MetricEvidence(
        metric=metric,
        value=value,
        provenance=provenance,
        machine_id=machine_id,
        freshness="2026-08-01",
    )


def build_evidence(viable: tuple[Candidate, ...]) -> dict[Candidate, tuple[MetricEvidence, ...]]:
    mapping: dict[Candidate, tuple[MetricEvidence, ...]] = {}
    for index, candidate in enumerate(viable):
        mapping[candidate] = (
            evidence("decode_throughput", 20.0 + 5.0 * index),
            evidence("stability", 0.8 + 0.01 * index),
        )
    return mapping


def viable_for(budget: HardwareBudget) -> tuple[Candidate, ...]:
    viable, rejected = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=budget,
        requirements=REQUIREMENTS,
    )
    return viable


def test_only_viable_tuples_are_ranked() -> None:
    viable = viable_for(CUDA_BUDGET)
    _, rejected = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=CUDA_BUDGET,
        requirements=REQUIREMENTS,
    )
    ranking = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate=build_evidence(viable),
        reference_machine_id="ubuntu-1",
    )
    ranked_ids = {item.candidate for item in ranking}
    assert ranked_ids == set(viable)
    assert not ranked_ids.intersection(candidate for candidate, _ in rejected)


def test_extreme_weights_cannot_resurrect_rejected_tuple() -> None:
    viable = viable_for(CPU_BUDGET)
    rejected = [candidate for candidate in CANDIDATES if candidate not in set(viable)]
    extreme = WorkloadProfile(
        id="extreme",
        version="1",
        name="Extreme",
        weights=tuple(
            (metric, 1.0) if metric == "decode_throughput" else (metric, 0.0)
            for metric in WEIGHT_METRICS
        ),
    )
    ranking = rank_candidates(
        viable,
        profile=extreme,
        evidence_by_candidate=build_evidence(viable),
        reference_machine_id="ubuntu-1",
    )
    assert all(item.candidate not in rejected for item in ranking)


def test_ranking_is_deterministic() -> None:
    viable = viable_for(CUDA_BUDGET)
    evidence_map = build_evidence(viable)
    first = rank_candidates(
        viable,
        profile=SEED_PROFILES[1],
        evidence_by_candidate=evidence_map,
        reference_machine_id="ubuntu-1",
    )
    second = rank_candidates(
        tuple(reversed(viable)),
        profile=SEED_PROFILES[1],
        evidence_by_candidate=evidence_map,
        reference_machine_id="ubuntu-1",
    )
    assert first == second
    assert [item.score for item in first] == sorted((item.score for item in first), reverse=True)


def test_improving_evidence_never_lowers_score() -> None:
    viable = viable_for(CUDA_BUDGET)[:1]
    candidate = viable[0]
    low = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate={candidate: (evidence("decode_throughput", 10.0),)},
        reference_machine_id="ubuntu-1",
    )[0]
    high = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate={candidate: (evidence("decode_throughput", 190.0),)},
        reference_machine_id="ubuntu-1",
    )[0]
    assert high.score >= low.score


def test_calibration_and_confidence_are_bounded() -> None:
    viable = viable_for(CUDA_BUDGET)[:1]
    candidate = viable[0]
    ranking = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate={candidate: (evidence("decode_throughput", 75.0),)},
        reference_machine_id="ubuntu-1",
    )[0]
    assert 0.0 <= ranking.score <= 1.0
    for contribution in ranking.contributions:
        assert 0.0 <= contribution.calibrated <= 1.0
        assert 0.0 <= contribution.effective_confidence <= 1.0
        assert 0.0 <= contribution.contribution <= 1.0


def test_foreign_machine_evidence_excluded_and_flagged() -> None:
    viable = viable_for(CUDA_BUDGET)[:1]
    candidate = viable[0]
    ranking = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate={
            candidate: (evidence("decode_throughput", 190.0, machine_id="elsewhere"),)
        },
        reference_machine_id="ubuntu-1",
    )[0]
    contribution = next(
        item for item in ranking.contributions if item.metric == "decode_throughput"
    )
    assert contribution.comparability == "incomparable"
    assert contribution.contribution == 0.0
    assert "excluded" in ranking.summary


def test_estimated_evidence_is_diluted_not_dropped() -> None:
    viable = viable_for(CUDA_BUDGET)[:1]
    candidate = viable[0]
    measured = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate={candidate: (evidence("stability", 1.0),)},
        reference_machine_id="ubuntu-1",
    )[0]
    estimated = rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate={candidate: (evidence("stability", 1.0, provenance="estimated"),)},
        reference_machine_id="ubuntu-1",
    )[0]
    assert estimated.score < measured.score
    assert estimated.score > 0.0


def test_all_seed_profiles_rank_consistently() -> None:
    viable = viable_for(CUDA_BUDGET)
    evidence_map = build_evidence(viable)
    for profile in SEED_PROFILES:
        ranking = rank_candidates(
            viable,
            profile=profile,
            evidence_by_candidate=evidence_map,
            reference_machine_id="ubuntu-1",
        )
        assert {item.candidate for item in ranking} == set(viable)
        assert len(ranking) == len(set(ranking))
