"""Contract tests: workload profiles and operator constraints (SEL-003).

Guarantees for the phase 14.2 surface:
- Weight normalization is deterministic and sums to 1.
- Relaxing a budget (component-wise monotonic) never removes a viable tuple.
- Relaxing operator caps never removes a viable tuple.
- Operator caps can only shrink the viable set relative to the budget alone.
- Profile round-trips are byte-stable.
"""

import itertools

import pytest

from morpheus.core.catalog import (
    EngineCatalogEntry,
    ModelCatalogEntry,
)
from morpheus.core.solver import (
    Candidate,
    EngineRule,
    HardwareBudget,
    WorkloadRequirements,
    check_constraints,
    filter_viable,
)
from morpheus.core.workload import (
    SEED_PROFILES,
    WorkloadProfile,
    monotonic_budget_holds,
)

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"SEL-003"})

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

MISTRAL = ModelCatalogEntry(
    id="mistral-7b-instruct",
    name="Mistral 7B Instruct",
    license="apache-2.0",
    architecture="auto",
    modalities=("text",),
    formats=("gguf", "safetensors"),
    quantizations=("q4_0", "q8_0", "f16"),
    context_window=32768,
    artifact_size_bytes=15_000_000_000,
    validation_freshness="2026-02-01T00:00:00+00:00",
    source_url="https://example.invalid/mistral-7b",
    source_digest="sha256:" + "c" * 64,
    revision="v1",
    engine_support=("llama.cpp", "vllm"),
    features=("coding",),
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

MODELS = {
    "llama-3.1-8b-instruct": LLAMA,
    "qwen2.5-7b-instruct": QWEN,
    "mistral-7b-instruct": MISTRAL,
}
ENGINES = {"llama.cpp": LLAMACPP, "vllm": VLLM}

BUDGETS = {
    "cpu-only": HardwareBudget(
        ram_bytes=16 * 1024**3, storage_bytes=100 * 1024**3, accelerator="cpu"
    ),
    "ubuntu-nvidia": HardwareBudget(
        ram_bytes=64 * 1024**3,
        vram_bytes=48 * 1024**3,
        storage_bytes=500 * 1024**3,
        accelerator="cuda",
    ),
    "windows-nvidia": HardwareBudget(
        ram_bytes=64 * 1024**3,
        vram_bytes=16 * 1024**3,
        storage_bytes=2 * 1024**4,
        accelerator="cuda",
    ),
}

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


def partition(
    budget: HardwareBudget,
    requirements: WorkloadRequirements = REQUIREMENTS,
) -> tuple[tuple[Candidate, ...], tuple[tuple[Candidate, tuple], ...]]:
    return filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=budget,
        requirements=requirements,
    )


def test_budget_relaxation_is_monotonic() -> None:
    smaller = HardwareBudget(ram_bytes=32 * 1024**3, storage_bytes=100 * 1024**3, accelerator="cpu")
    larger = HardwareBudget(
        ram_bytes=64 * 1024**3,
        storage_bytes=200 * 1024**3,
        accelerator="cpu",
    )
    assert monotonic_budget_holds(
        (("ram", smaller.ram_bytes), ("storage", smaller.storage_bytes)),
        (("ram", larger.ram_bytes), ("storage", larger.storage_bytes)),
    )
    smaller_viable, _ = partition(smaller)
    larger_viable, _ = partition(larger)
    assert set(smaller_viable) <= set(larger_viable)


def test_budget_relaxation_never_removes_viable() -> None:
    viable, _ = partition(BUDGETS["cpu-only"])
    relaxed, _ = partition(
        HardwareBudget(
            ram_bytes=64 * 1024**3,
            storage_bytes=500 * 1024**3,
            accelerator="cpu",
        )
    )
    assert set(viable) <= set(relaxed)
    assert len(relaxed) > len(viable)


def test_operator_caps_only_shrink_viable() -> None:
    from morpheus.core.workload import OperatorConstraints

    baseline, _ = partition(BUDGETS["ubuntu-nvidia"])
    capped, _ = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=BUDGETS["ubuntu-nvidia"],
        requirements=REQUIREMENTS,
        operator=OperatorConstraints(max_context=16384, allowed_engines=("llama.cpp",)),
    )
    assert set(capped) <= set(baseline)
    assert len(capped) < len(baseline)


def test_operator_relaxation_is_monotonic() -> None:
    from morpheus.core.workload import OperatorConstraints

    strict, _ = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=BUDGETS["windows-nvidia"],
        requirements=REQUIREMENTS,
        operator=OperatorConstraints(max_context=8192),
    )
    loose, _ = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=BUDGETS["windows-nvidia"],
        requirements=REQUIREMENTS,
        operator=OperatorConstraints(max_context=131072),
    )
    assert set(strict) <= set(loose)


def test_operator_cap_outranks_budget() -> None:
    from morpheus.core.workload import OperatorConstraints

    cand = Candidate(
        model_id="llama-3.1-8b-instruct",
        quantization="f16",
        engine_id="vllm",
        context_window=8192,
        concurrency=1,
    )
    unconstrained = check_constraints(
        cand,
        model=MODELS[cand.model_id],
        engine=ENGINES[cand.engine_id],
        engine_rule=RULES[cand.engine_id],
        budget=BUDGETS["ubuntu-nvidia"],
        requirements=REQUIREMENTS,
    )
    assert unconstrained == ()
    constrained = check_constraints(
        cand,
        model=MODELS[cand.model_id],
        engine=ENGINES[cand.engine_id],
        engine_rule=RULES[cand.engine_id],
        budget=BUDGETS["ubuntu-nvidia"],
        requirements=REQUIREMENTS,
        operator=OperatorConstraints(max_ram_bytes=1_000_000),
    )
    assert "operator-ram" in {violation.code for violation in constrained}


def test_seed_profiles_normalize_and_round_trip() -> None:
    for profile in SEED_PROFILES:
        assert sum(weight for _, weight in profile.weights) == pytest.approx(1.0)
        assert WorkloadProfile.from_dict(profile.to_dict()) == profile


def test_identical_inputs_produce_identical_partitions() -> None:
    first = partition(BUDGETS["windows-nvidia"])
    second = partition(BUDGETS["windows-nvidia"])
    assert first == second


def test_partition_is_consistent_across_profiles() -> None:
    viable_by_profile = {
        profile.id: partition(BUDGETS["ubuntu-nvidia"], profile_requirements(profile))[0]
        for profile in SEED_PROFILES
    }
    assert all(len(tuples) == len(set(tuples)) for tuples in viable_by_profile.values())


def profile_requirements(profile: WorkloadProfile) -> WorkloadRequirements:
    return WorkloadRequirements(
        features=profile.features,
        context_tokens=profile.context_tokens,
        concurrency=profile.concurrency,
    )
