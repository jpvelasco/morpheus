"""Unit tests: hard compatibility and resource constraint solver (SEL-002)."""

from __future__ import annotations

import pytest

from morpheus.core.catalog import (
    EngineCatalogEntry,
    ModelCatalogEntry,
    TrustViolation,
)
from morpheus.core.solver import (
    Candidate,
    ConstraintViolation,
    EngineRule,
    HardwareBudget,
    ResourceEstimate,
    SolverError,
    WorkloadRequirements,
    check_constraints,
    estimate_resource_use,
    filter_viable,
)

LLAMA = ModelCatalogEntry(
    id="llama-3.1-8b-instruct",
    name="Llama 3.1 8B Instruct",
    license="llama3.1",
    architecture="llama",
    modalities=("text",),
    formats=("gguf", "safetensors"),
    quantizations=("f16", "q8_0", "q4_0"),
    context_window=131072,
    artifact_size_bytes=16_384_000_000,
    validation_freshness=__import__("datetime").date(2026, 8, 1),
    source_digest="a" * 64,
    revision="v0.1",
    engine_support=("llama.cpp", "vllm"),
    features=("tools", "structured-output", "long-context"),
)

QWEN = ModelCatalogEntry(
    id="qwen2.5-7b-instruct",
    name="Qwen 2.5 7B Instruct",
    license="apache-2.0",
    architecture="qwen",
    modalities=("text",),
    formats=("gguf", "safetensors"),
    quantizations=("f16", "q8_0"),
    context_window=32768,
    artifact_size_bytes=14_336_000_000,
    validation_freshness=__import__("datetime").date(2026, 8, 1),
    source_digest="b" * 64,
    revision="v0.1",
    engine_support=("llama.cpp",),
    features=("tools",),
)

LLAMACPP = EngineCatalogEntry(
    id="llama.cpp",
    name="llama.cpp",
    license="mit",
    version="b4000",
    platforms=("linux", "windows", "darwin"),
    features=("tools", "structured-output"),
)

VLLM = EngineCatalogEntry(
    id="vllm",
    name="vLLM",
    license="apache-2.0",
    version="0.8.0",
    platforms=("linux",),
    features=("tools", "structured-output"),
)

RULES = {
    "llama.cpp": EngineRule(engine_id="llama.cpp"),
    "vllm": EngineRule(engine_id="vllm", accelerator="cuda", max_context=131072),
}

BUDGETS = {
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
}


def candidate(**overrides) -> Candidate:
    fields = dict(
        model_id="llama-3.1-8b-instruct",
        quantization="q8_0",
        engine_id="llama.cpp",
        context_window=8192,
        concurrency=1,
    )
    fields.update(overrides)
    return Candidate(**fields)


def requirements(**overrides) -> WorkloadRequirements:
    fields = dict(features=(), context_tokens=4096, concurrency=1)
    fields.update(overrides)
    return WorkloadRequirements(**fields)


def context(
    cand: Candidate | None = None,
    budget: HardwareBudget | None = None,
    needs: WorkloadRequirements | None = None,
    violations: tuple[TrustViolation, ...] = (),
    model: ModelCatalogEntry = LLAMA,
    engine: EngineCatalogEntry = LLAMACPP,
    rule: EngineRule | None = None,
):
    return dict(
        candidate=cand or candidate(),
        model=model,
        engine=engine,
        engine_rule=rule or RULES[cand.engine_id if cand else "llama.cpp"],
        budget=budget or BUDGETS["ubuntu-nvidia"],
        requirements=needs or requirements(),
        trust_violations=violations,
    )


def codes(result) -> tuple[str, ...]:
    return tuple(violation.code for violation in result)


class TestDecisionTables:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            (dict(), ()),
            (dict(model_id="qwen2.5-7b-instruct"), ()),
            (dict(quantization="q4_0"), ()),
        ],
    )
    def test_ubuntu_nvidia_table(self, overrides: dict, expected: tuple[str, ...]) -> None:
        cand = candidate(**overrides)
        assert (
            codes(check_constraints(**context(cand, budget=BUDGETS["ubuntu-nvidia"]))) == expected
        )

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            (dict(), ()),
            (dict(engine_id="vllm"), ()),
            (dict(quantization="q4_0"), ()),
            (dict(context_window=65536), ()),
        ],
    )
    def test_windows_nvidia_table(self, overrides: dict, expected: tuple[str, ...]) -> None:
        cand = candidate(**overrides)
        assert (
            codes(check_constraints(**context(cand, budget=BUDGETS["windows-nvidia"]))) == expected
        )

    def test_apple_silicon_unified_memory(self) -> None:
        cand = candidate(engine_id="llama.cpp")
        assert check_constraints(**context(cand, budget=BUDGETS["apple-silicon"])) == ()

    def test_cpu_only_rejects_cuda_engine(self) -> None:
        cand = candidate(engine_id="vllm")
        result = check_constraints(**context(cand, budget=BUDGETS["cpu-only"]))
        assert "accelerator" in codes(result)

    def test_vram_exhaustion_on_windows(self) -> None:
        cand = candidate(engine_id="vllm", quantization="f16", context_window=131072, concurrency=8)
        result = check_constraints(**context(cand, budget=BUDGETS["windows-nvidia"]))
        assert "resource-vram" in codes(result)

    def test_context_exceeds_engine_ceiling(self) -> None:
        cand = candidate(context_window=200_000)
        result = check_constraints(**context(cand, budget=BUDGETS["ubuntu-nvidia"]))
        assert "context" in codes(result)

    def test_trust_violation_rejects(self) -> None:
        result = check_constraints(
            **context(
                violations=(
                    TrustViolation(
                        entry_id="llama-3.1-8b-instruct", reason="missing sha256 digest"
                    ),
                )
            )
        )
        assert codes(result) == ("trust",)

    def test_required_feature_missing(self) -> None:
        cand = candidate(model_id="qwen2.5-7b-instruct")
        result = check_constraints(**context(cand, needs=requirements(features=("long-context",))))
        assert "feature" in codes(result)

    def test_workload_context_need_not_met(self) -> None:
        result = check_constraints(**context(needs=requirements(context_tokens=32768)))
        assert "context" in codes(result)

    def test_workload_concurrency_need_not_met(self) -> None:
        result = check_constraints(**context(needs=requirements(concurrency=4)))
        assert "concurrency" in codes(result)

    def test_unsupported_engine(self) -> None:
        cand = candidate(engine_id="vllm", model_id="qwen2.5-7b-instruct")
        result = check_constraints(**context(cand, model=QWEN))
        assert "engine-support" in codes(result)

    def test_unknown_quantization_estimate_fails(self) -> None:
        cand = candidate(quantization="q3_k")
        result = check_constraints(**context(cand))
        assert "estimate" in codes(result)


class TestFilterViable:
    def test_rejected_cannot_enter_ranking(self) -> None:
        viable, rejected = filter_viable(
            (
                candidate(),
                candidate(engine_id="vllm"),
                candidate(model_id="qwen2.5-7b-instruct"),
                candidate(
                    quantization="f16", engine_id="vllm", context_window=131072, concurrency=8
                ),
                candidate(quantization="f16", context_window=200_000),
            ),
            models={"llama-3.1-8b-instruct": LLAMA, "qwen2.5-7b-instruct": QWEN},
            engines={"llama.cpp": LLAMACPP, "vllm": VLLM},
            engine_rules=RULES,
            budget=BUDGETS["windows-nvidia"],
            requirements=requirements(),
        )
        assert sorted(item.model_id for item in viable) == [
            "llama-3.1-8b-instruct",
            "llama-3.1-8b-instruct",
            "qwen2.5-7b-instruct",
        ]
        assert len(rejected) == 2
        assert "resource-vram" in codes(rejected[0][1])
        assert "context" in codes(rejected[1][1])

    def test_unknown_model_rejected(self) -> None:
        viable, rejected = filter_viable(
            (candidate(model_id="gpt-4"),),
            models={"llama-3.1-8b-instruct": LLAMA},
            engines={"llama.cpp": LLAMACPP},
            engine_rules=RULES,
            budget=BUDGETS["ubuntu-nvidia"],
            requirements=requirements(),
        )
        assert viable == ()
        assert codes(rejected[0][1]) == ("model",)

    def test_unknown_engine_rejected(self) -> None:
        viable, rejected = filter_viable(
            (candidate(engine_id="tensorrt"),),
            models={"llama-3.1-8b-instruct": LLAMA},
            engines={"llama.cpp": LLAMACPP},
            engine_rules=RULES,
            budget=BUDGETS["ubuntu-nvidia"],
            requirements=requirements(),
        )
        assert viable == ()
        assert codes(rejected[0][1]) == ("engine",)


class TestEstimator:
    def test_deterministic(self) -> None:
        first = estimate_resource_use(LLAMA, candidate(), BUDGETS["ubuntu-nvidia"])
        second = estimate_resource_use(LLAMA, candidate(), BUDGETS["ubuntu-nvidia"])
        assert first == second
        assert first.ram_with_margin() > first.ram_bytes

    def test_quantization_scales_weights(self) -> None:
        f16 = estimate_resource_use(LLAMA, candidate(quantization="f16"), BUDGETS["ubuntu-nvidia"])
        q8 = estimate_resource_use(LLAMA, candidate(quantization="q8_0"), BUDGETS["ubuntu-nvidia"])
        assert f16.ram_bytes > q8.ram_bytes

    def test_cuda_host_reports_vram(self) -> None:
        estimate = estimate_resource_use(LLAMA, candidate(), BUDGETS["ubuntu-nvidia"])
        assert estimate.vram_bytes > 0
        cpu = estimate_resource_use(LLAMA, candidate(), BUDGETS["cpu-only"])
        assert cpu.vram_bytes == 0

    def test_unknown_quantization_raises(self) -> None:
        with pytest.raises(SolverError, match="unknown quantization"):
            estimate_resource_use(LLAMA, candidate(quantization="q3_k"), BUDGETS["ubuntu-nvidia"])

    def test_estimate_round_trip(self) -> None:
        estimate = estimate_resource_use(LLAMA, candidate(), BUDGETS["ubuntu-nvidia"])
        assert ResourceEstimate(**estimate.to_dict()) == estimate


class TestContracts:
    def test_budget_validation(self) -> None:
        with pytest.raises(SolverError):
            HardwareBudget(ram_bytes=0, storage_bytes=1)
        with pytest.raises(SolverError):
            HardwareBudget(ram_bytes=1, storage_bytes=1, accelerator="rocm")

    def test_violation_round_trip(self) -> None:
        violation = ConstraintViolation("trust", "missing sha256 digest")
        assert ConstraintViolation(**violation.to_dict()) == violation
