"""Contract tests: hard compatibility solver boundary (SEL-002)."""

from __future__ import annotations

from datetime import date

import pytest

from morpheus.core.catalog import EngineCatalogEntry, ModelCatalogEntry
from morpheus.core.solver import (
    Candidate,
    EngineRule,
    HardwareBudget,
    WorkloadRequirements,
    filter_viable,
)

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"SEL-002"})

pytestmark = pytest.mark.contract

FIXTURE_BUDGETS = {
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
    "apple-silicon": HardwareBudget(
        ram_bytes=32 * 1024**3, vram_bytes=0, storage_bytes=512 * 1024**3, accelerator="metal"
    ),
    "cpu-only": HardwareBudget(
        ram_bytes=16 * 1024**3, vram_bytes=0, storage_bytes=100 * 1024**3, accelerator="cpu"
    ),
    "ubuntu-1": HardwareBudget(
        ram_bytes=128 * 1024**3,
        vram_bytes=48 * 1024**3,
        storage_bytes=1 * 1024**4,
        accelerator="cuda",
    ),
    "ubuntu-2": HardwareBudget(
        ram_bytes=64 * 1024**3,
        vram_bytes=16 * 1024**3,
        storage_bytes=2 * 1024**4,
        accelerator="cuda",
    ),
}

MODELS = {
    "llama-3.1-8b-instruct": ModelCatalogEntry(
        id="llama-3.1-8b-instruct",
        name="Llama 3.1 8B Instruct",
        license="llama3.1",
        architecture="llama",
        modalities=("text",),
        formats=("gguf", "safetensors"),
        quantizations=("f16", "q8_0", "q4_0"),
        context_window=131072,
        artifact_size_bytes=16_384_000_000,
        validation_freshness=date(2026, 8, 1),
        source_digest="a" * 64,
        revision="v0.1",
        engine_support=("llama.cpp", "vllm"),
        features=("tools", "structured-output", "long-context"),
    ),
    "qwen2.5-7b-instruct": ModelCatalogEntry(
        id="qwen2.5-7b-instruct",
        name="Qwen 2.5 7B Instruct",
        license="apache-2.0",
        architecture="qwen",
        modalities=("text",),
        formats=("gguf", "safetensors"),
        quantizations=("f16", "q8_0"),
        context_window=32768,
        artifact_size_bytes=14_336_000_000,
        validation_freshness=date(2026, 8, 1),
        source_digest="b" * 64,
        revision="v0.1",
        engine_support=("llama.cpp",),
        features=("tools",),
    ),
    "mistral-7b-instruct": ModelCatalogEntry(
        id="mistral-7b-instruct",
        name="Mistral 7B Instruct",
        license="apache-2.0",
        architecture="mistral",
        modalities=("text",),
        formats=("gguf", "safetensors"),
        quantizations=("f16", "q8_0", "q4_0"),
        context_window=32768,
        artifact_size_bytes=14_336_000_000,
        validation_freshness=date(2026, 8, 1),
        source_digest="c" * 64,
        revision="v0.1",
        engine_support=("llama.cpp",),
        features=(),
    ),
}

ENGINES = {
    "llama.cpp": EngineCatalogEntry(
        id="llama.cpp",
        name="llama.cpp",
        license="mit",
        version="b4000",
        platforms=("linux", "windows", "darwin"),
        features=("tools", "structured-output"),
    ),
    "vllm": EngineCatalogEntry(
        id="vllm",
        name="vLLM",
        license="apache-2.0",
        version="0.8.0",
        platforms=("linux",),
        features=("tools", "structured-output"),
    ),
}

RULES = {
    "llama.cpp": EngineRule(engine_id="llama.cpp"),
    "vllm": EngineRule(engine_id="vllm", accelerator="cuda", max_context=131072),
}

CANDIDATES = (
    Candidate("llama-3.1-8b-instruct", "q8_0", "llama.cpp", 8192, 1),
    Candidate("llama-3.1-8b-instruct", "f16", "llama.cpp", 131072, 4),
    Candidate("llama-3.1-8b-instruct", "q8_0", "vllm", 8192, 1),
    Candidate("llama-3.1-8b-instruct", "f16", "vllm", 131072, 8),
    Candidate("qwen2.5-7b-instruct", "q8_0", "llama.cpp", 32768, 1),
    Candidate("qwen2.5-7b-instruct", "q8_0", "vllm", 8192, 1),
    Candidate("mistral-7b-instruct", "q8_0", "llama.cpp", 32768, 2),
)


@pytest.mark.parametrize("host", sorted(FIXTURE_BUDGETS))
def test_partition_covers_all_candidates(host: str) -> None:
    viable, rejected = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=FIXTURE_BUDGETS[host],
        requirements=WorkloadRequirements(context_tokens=4096),
    )
    assert len(viable) + len(rejected) == len(CANDIDATES)
    assert len({candidate for candidate, _ in rejected}) == len(rejected)
    assert len(set(viable)) == len(viable)


def test_partition_is_deterministic() -> None:
    baseline = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=FIXTURE_BUDGETS["windows-nvidia"],
        requirements=WorkloadRequirements(context_tokens=32_768, concurrency=2),
    )
    repeated = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=FIXTURE_BUDGETS["windows-nvidia"],
        requirements=WorkloadRequirements(context_tokens=32_768, concurrency=2),
    )
    assert baseline[0] == repeated[0]
    assert baseline[1] == repeated[1]


def test_rejections_carry_stable_codes() -> None:
    _, rejected = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=FIXTURE_BUDGETS["cpu-only"],
        requirements=WorkloadRequirements(features=("long-context",)),
    )
    codes = {violation.code for _, violations in rejected for violation in violations}
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


def test_viable_never_contradicts_rejected() -> None:
    viable, rejected = filter_viable(
        CANDIDATES,
        models=MODELS,
        engines=ENGINES,
        engine_rules=RULES,
        budget=FIXTURE_BUDGETS["apple-silicon"],
        requirements=WorkloadRequirements(context_tokens=4096),
    )
    viable_set = set(viable)
    rejected_set = {candidate for candidate, _ in rejected}
    assert viable_set.isdisjoint(rejected_set)
