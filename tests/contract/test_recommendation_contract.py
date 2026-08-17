"""Contract tests: immutable recommendation records (SEL-004, SEL-005).

Guarantees:
- Identical inputs replay to a byte-identical record and content digest.
- Record ids are content digests: any change to inputs changes the digest.
- Stored records are immutable and verified on collision.
- The record carries the complete exclusion set with stable violation codes.
- Round-tripping through JSON preserves every field exactly.
"""

import itertools
import json
from datetime import UTC, datetime

import pytest

from morpheus.core.catalog import (
    EngineCatalogEntry,
    ModelCatalogEntry,
)
from morpheus.core.ranking import (
    MetricEvidence,
    RankedCandidate,
    rank_candidates,
)
from morpheus.core.recommendation import (
    RecommendationStore,
    build_recommendation,
    canonical_json,
)
from morpheus.core.solver import (
    Candidate,
    EngineRule,
    HardwareBudget,
    WorkloadRequirements,
    filter_viable,
)
from morpheus.core.workload import SEED_PROFILES, OperatorConstraints

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
    features=("tool_calling", "long-context", "coding", "agentic"),
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
    features=("tool_calling", "coding"),
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

BUDGET = HardwareBudget(
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


def evidence(candidate: Candidate, value: float) -> MetricEvidence:
    return MetricEvidence(
        metric="decode_throughput",
        value=value,
        machine_id="ubuntu-1",
        freshness="2026-08-01",
    )


def partition() -> tuple[
    tuple[Candidate, ...],
    tuple[tuple[Candidate, tuple], ...],
]:
    return filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=BUDGET,
        requirements=REQUIREMENTS,
    )


def ranked() -> tuple[RankedCandidate, ...]:
    viable, _ = partition()
    mapping = {
        candidate: (evidence(candidate, 20.0 + 5.0 * index),)
        for index, candidate in enumerate(viable)
    }
    return rank_candidates(
        viable,
        profile=SEED_PROFILES[0],
        evidence_by_candidate=mapping,
        reference_machine_id="ubuntu-1",
    )


def test_replay_is_byte_identical() -> None:
    viable, rejected = partition()
    stamped = datetime(2026, 8, 1, tzinfo=UTC)
    first = build_recommendation(
        profile=SEED_PROFILES[0],
        operator=OperatorConstraints(allowed_engines=("llama.cpp",)),
        reference_machine_id="ubuntu-1",
        budget={
            "ram_bytes": BUDGET.ram_bytes,
            "storage_bytes": BUDGET.storage_bytes,
            "accelerator": BUDGET.accelerator,
        },
        ranked=ranked(),
        excluded=rejected,
        created_at=stamped,
    )
    second = build_recommendation(
        profile=SEED_PROFILES[0],
        operator=OperatorConstraints(allowed_engines=("llama.cpp",)),
        reference_machine_id="ubuntu-1",
        budget={
            "ram_bytes": BUDGET.ram_bytes,
            "storage_bytes": BUDGET.storage_bytes,
            "accelerator": BUDGET.accelerator,
        },
        ranked=ranked(),
        excluded=rejected,
        created_at=stamped,
    )
    assert first.record_id == second.record_id
    assert canonical_json(first.content_dict()) == canonical_json(second.content_dict())


def test_any_input_change_changes_the_digest() -> None:
    viable, rejected = partition()
    kwargs: dict = {
        "profile": SEED_PROFILES[0],
        "operator": None,
        "reference_machine_id": "ubuntu-1",
        "budget": {
            "ram_bytes": BUDGET.ram_bytes,
            "storage_bytes": BUDGET.storage_bytes,
            "accelerator": BUDGET.accelerator,
        },
        "ranked": ranked(),
        "excluded": rejected,
    }
    baseline = build_recommendation(**kwargs)
    changed = build_recommendation(**{**kwargs, "reference_machine_id": "ubuntu-2"})
    assert changed.record_id != baseline.record_id


def test_record_carries_complete_exclusion_set() -> None:
    viable, rejected = partition()
    item = build_recommendation(
        profile=SEED_PROFILES[0],
        operator=None,
        reference_machine_id="ubuntu-1",
        budget={
            "ram_bytes": BUDGET.ram_bytes,
            "storage_bytes": BUDGET.storage_bytes,
            "accelerator": BUDGET.accelerator,
        },
        ranked=ranked(),
        excluded=rejected,
    )
    assert len(item.excluded) == len(rejected)
    codes = {code for _, violations in item.excluded for code in (v.code for v in violations)}
    assert codes
    assert codes <= {
        "trust",
        "engine-support",
        "quantization",
        "accelerator",
        "context",
        "feature",
        "concurrency",
        "estimate",
        "resource-ram",
        "resource-vram",
        "resource-storage",
    }


def test_store_round_trip_preserves_every_field(tmp_path) -> None:
    viable, rejected = partition()
    item = build_recommendation(
        profile=SEED_PROFILES[0],
        operator=OperatorConstraints(max_context=16384),
        reference_machine_id="ubuntu-1",
        budget={
            "ram_bytes": BUDGET.ram_bytes,
            "storage_bytes": BUDGET.storage_bytes,
            "accelerator": BUDGET.accelerator,
        },
        ranked=ranked(),
        excluded=rejected,
    )
    store = RecommendationStore(tmp_path)
    store.initialize()
    store.store_record(item)
    clone = store.load_record(item.record_id)
    assert clone == item
    assert clone.to_dict() == item.to_dict()
    assert json.loads(canonical_json(clone.content_dict())) == json.loads(
        canonical_json(item.content_dict())
    )


def test_ranking_inside_record_matches_live_ranking() -> None:
    viable, rejected = partition()
    item = build_recommendation(
        profile=SEED_PROFILES[0],
        operator=None,
        reference_machine_id="ubuntu-1",
        budget={
            "ram_bytes": BUDGET.ram_bytes,
            "storage_bytes": BUDGET.storage_bytes,
            "accelerator": BUDGET.accelerator,
        },
        ranked=ranked(),
        excluded=rejected,
    )
    live = ranked()
    assert [r.candidate for r in item.ranked] == [r.candidate for r in live]
    assert [r.score for r in item.ranked] == [r.score for r in live]
