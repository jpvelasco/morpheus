"""Hard compatibility and resource constraint solver (SEL-002).

Infeasible model/quantization/engine/context/concurrency tuples are rejected
here, before any ranking exists. Rejected tuples carry stable violation codes
and can never re-enter through ranking weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from morpheus.core.catalog import (
    EngineCatalogEntry,
    ModelCatalogEntry,
    TrustViolation,
)
from morpheus.core.workload import OperatorConstraints

ACCELERATORS = ("cpu", "cuda", "metal")

_QUANT_BYTES_PER_PARAM = {
    "f16": 2.0,
    "q8_0": 1.0625,
    "q6_k": 0.75,
    "q5_k_m": 0.6875,
    "q4_k_m": 0.59375,
    "q4_0": 0.5625,
    "awq": 1.0,
    "gptq": 1.0,
}
_KV_BYTES_PER_TOKEN = 512
_OVERHEAD_BYTES = 512 * 1024 * 1024
_DEFAULT_MARGIN = 1.2


class SolverError(ValueError):
    """A solver input violates its contract."""


@dataclass(frozen=True, slots=True)
class HardwareBudget:
    """Declared host budgets. ``vram_bytes`` 0 with accelerator cpu means no
    accelerator memory; metal hosts report unified memory as ``ram_bytes``."""

    ram_bytes: int
    storage_bytes: int
    accelerator: str = "cpu"
    vram_bytes: int = 0

    def __post_init__(self) -> None:
        if self.ram_bytes <= 0 or self.storage_bytes <= 0 or self.vram_bytes < 0:
            raise SolverError("budgets must be positive bytes")
        if self.accelerator not in ACCELERATORS:
            raise SolverError(f"unknown accelerator: {self.accelerator}")


@dataclass(frozen=True, slots=True)
class WorkloadRequirements:
    """Required behaviors for the selected developer workload."""

    features: tuple[str, ...] = ()
    context_tokens: int = 4096
    concurrency: int = 1

    def __post_init__(self) -> None:
        if self.context_tokens < 1 or self.concurrency < 1:
            raise SolverError("workload context and concurrency must be positive")


@dataclass(frozen=True, slots=True)
class Candidate:
    """A model/quantization/engine/context/concurrency tuple."""

    model_id: str
    quantization: str
    engine_id: str
    context_window: int
    concurrency: int
    launch_configuration: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.context_window < 1 or self.concurrency < 1:
            raise SolverError("candidate context and concurrency must be positive")


@dataclass(frozen=True, slots=True)
class EngineRule:
    """Solver knowledge about an engine: accelerator needs, context ceiling,
    and quantizations it can execute."""

    engine_id: str
    accelerator: str | None = None
    max_context: int | None = None
    quantizations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResourceEstimate:
    """Deterministic resource use with a declared safety margin and confidence."""

    ram_bytes: int
    vram_bytes: int
    storage_bytes: int
    margin: float = _DEFAULT_MARGIN
    confidence: float = 0.5

    def __post_init__(self) -> None:
        if self.margin < 1.0:
            raise SolverError("margin must be at least 1.0")
        if not 0 < self.confidence <= 1.0:
            raise SolverError("confidence must be in (0, 1]")

    def ram_with_margin(self) -> int:
        return int(self.ram_bytes * self.margin)

    def vram_with_margin(self) -> int:
        return int(self.vram_bytes * self.margin)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ram_bytes": self.ram_bytes,
            "vram_bytes": self.vram_bytes,
            "storage_bytes": self.storage_bytes,
            "margin": self.margin,
            "confidence": self.confidence,
        }


def estimate_resource_use(
    model: ModelCatalogEntry,
    candidate: Candidate,
    budget: HardwareBudget,
    *,
    margin: float = _DEFAULT_MARGIN,
    confidence: float = 0.5,
) -> ResourceEstimate:
    """Estimate weights + KV cache + overhead for a candidate tuple.

    Weight bytes derive from the catalog artifact size (f16 reference) scaled
    by the quantization's bytes-per-parameter. The KV cache uses a documented
    per-token overhead per concurrent stream. Deterministic for identical
    inputs; margin and confidence are operator-declared.
    """
    if candidate.quantization not in _QUANT_BYTES_PER_PARAM:
        raise SolverError(f"unknown quantization: {candidate.quantization}")
    reference = model.artifact_size_bytes
    if reference is None or reference <= 0:
        raise SolverError(f"model {model.id} has no artifact size")
    weights = int(reference * _QUANT_BYTES_PER_PARAM[candidate.quantization] / 2.0)
    kv = candidate.context_window * candidate.concurrency * _KV_BYTES_PER_TOKEN
    memory = weights + kv + _OVERHEAD_BYTES
    vram = weights + kv if budget.accelerator == "cuda" else 0
    return ResourceEstimate(
        ram_bytes=memory,
        vram_bytes=vram,
        storage_bytes=reference,
        margin=margin,
        confidence=confidence,
    )


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    code: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}


def check_constraints(
    candidate: Candidate,
    *,
    model: ModelCatalogEntry,
    engine: EngineCatalogEntry,
    engine_rule: EngineRule,
    budget: HardwareBudget,
    requirements: WorkloadRequirements,
    trust_violations: tuple[TrustViolation, ...] = (),
    operator: OperatorConstraints | None = None,
) -> tuple[ConstraintViolation, ...]:
    """Return every violated hard constraint in stable order."""
    violations: list[ConstraintViolation] = []
    if operator is not None:
        if operator.max_context is not None and candidate.context_window > operator.max_context:
            violations.append(
                ConstraintViolation(
                    "operator-context",
                    f"operator cap {operator.max_context} below candidate context "
                    f"{candidate.context_window}",
                )
            )
        if (
            operator.max_concurrency is not None
            and candidate.concurrency > operator.max_concurrency
        ):
            violations.append(
                ConstraintViolation(
                    "operator-concurrency",
                    f"operator cap {operator.max_concurrency} below candidate "
                    f"concurrency {candidate.concurrency}",
                )
            )
        if operator.allowed_engines and candidate.engine_id not in operator.allowed_engines:
            violations.append(
                ConstraintViolation(
                    "operator-engine", f"engine {candidate.engine_id} not allowed by operator"
                )
            )
        if (
            operator.allowed_quantizations
            and candidate.quantization not in operator.allowed_quantizations
        ):
            violations.append(
                ConstraintViolation(
                    "operator-quantization",
                    f"quantization {candidate.quantization} not allowed by operator",
                )
            )
    model_trust = next(
        (violation for violation in trust_violations if violation.entry_id == model.id), None
    )
    if model_trust is not None:
        violations.append(ConstraintViolation("trust", model_trust.reason))
    if candidate.engine_id not in model.engine_support:
        violations.append(
            ConstraintViolation(
                "engine-support", f"{model.id} does not support engine {candidate.engine_id}"
            )
        )
    if candidate.quantization not in model.quantizations:
        violations.append(
            ConstraintViolation(
                "quantization", f"{model.id} has no {candidate.quantization} artifact"
            )
        )
    elif engine_rule.quantizations and candidate.quantization not in engine_rule.quantizations:
        violations.append(
            ConstraintViolation(
                "quantization",
                f"engine {engine.id} cannot execute {candidate.quantization}",
            )
        )
    if engine_rule.accelerator is not None and budget.accelerator != engine_rule.accelerator:
        violations.append(
            ConstraintViolation(
                "accelerator",
                f"engine {engine.id} requires {engine_rule.accelerator}, "
                f"host has {budget.accelerator}",
            )
        )
    context_ceiling = model.context_window
    if engine_rule.max_context is not None:
        context_ceiling = (
            min(context_ceiling, engine_rule.max_context)
            if context_ceiling is not None
            else engine_rule.max_context
        )
    if context_ceiling is not None and candidate.context_window > context_ceiling:
        violations.append(
            ConstraintViolation(
                "context",
                f"context {candidate.context_window} exceeds ceiling {context_ceiling}",
            )
        )
    missing = [
        feature
        for feature in requirements.features
        if feature not in model.features or feature not in engine.features
    ]
    if missing:
        violations.append(
            ConstraintViolation(
                "feature",
                f"workload requires features unavailable on tuple: {', '.join(sorted(missing))}",
            )
        )
    if candidate.context_window < requirements.context_tokens:
        violations.append(
            ConstraintViolation(
                "context",
                f"context {candidate.context_window} below workload need "
                f"{requirements.context_tokens}",
            )
        )
    if candidate.concurrency < requirements.concurrency:
        violations.append(
            ConstraintViolation(
                "concurrency",
                f"concurrency {candidate.concurrency} below workload need "
                f"{requirements.concurrency}",
            )
        )
    try:
        estimate = estimate_resource_use(model, candidate, budget)
    except SolverError as exc:
        violations.append(ConstraintViolation("estimate", str(exc)))
        return tuple(violations)
    if estimate.ram_with_margin() > budget.ram_bytes:
        violations.append(
            ConstraintViolation(
                "resource-ram",
                f"estimated ram {estimate.ram_with_margin()} exceeds budget {budget.ram_bytes}",
            )
        )
    if estimate.vram_with_margin() > budget.vram_bytes:
        violations.append(
            ConstraintViolation(
                "resource-vram",
                f"estimated vram {estimate.vram_with_margin()} exceeds budget {budget.vram_bytes}",
            )
        )
    if estimate.storage_bytes > budget.storage_bytes:
        violations.append(
            ConstraintViolation(
                "resource-storage",
                f"artifact {estimate.storage_bytes} exceeds storage budget {budget.storage_bytes}",
            )
        )
    if operator is not None:
        if (
            operator.max_ram_bytes is not None
            and estimate.ram_with_margin() > operator.max_ram_bytes
        ):
            violations.append(
                ConstraintViolation(
                    "operator-ram",
                    f"estimated ram {estimate.ram_with_margin()} exceeds operator cap "
                    f"{operator.max_ram_bytes}",
                )
            )
        if (
            operator.max_vram_bytes is not None
            and estimate.vram_with_margin() > operator.max_vram_bytes
        ):
            violations.append(
                ConstraintViolation(
                    "operator-vram",
                    f"estimated vram {estimate.vram_with_margin()} exceeds operator cap "
                    f"{operator.max_vram_bytes}",
                )
            )
        if (
            operator.max_storage_bytes is not None
            and estimate.storage_bytes > operator.max_storage_bytes
        ):
            violations.append(
                ConstraintViolation(
                    "operator-storage",
                    f"artifact {estimate.storage_bytes} exceeds operator cap "
                    f"{operator.max_storage_bytes}",
                )
            )
    return tuple(violations)


def filter_viable(
    candidates: tuple[Candidate, ...],
    *,
    models: dict[str, ModelCatalogEntry],
    engines: dict[str, EngineCatalogEntry],
    engine_rules: dict[str, EngineRule],
    budget: HardwareBudget,
    requirements: WorkloadRequirements,
    trust_violations: tuple[TrustViolation, ...] = (),
    operator: OperatorConstraints | None = None,
) -> tuple[tuple[Candidate, ...], tuple[tuple[Candidate, tuple[ConstraintViolation, ...]], ...]]:
    """Partition candidates into viable and rejected-with-reasons.

    This is the only gate ranking may consume; weights can never resurrect a
    rejected tuple.
    """
    viable: list[Candidate] = []
    rejected: list[tuple[Candidate, tuple[ConstraintViolation, ...]]] = []
    for candidate in candidates:
        model = models.get(candidate.model_id)
        engine = engines.get(candidate.engine_id)
        if model is None:
            rejected.append(
                (
                    candidate,
                    (ConstraintViolation("model", f"unknown model {candidate.model_id}"),),
                )
            )
            continue
        if engine is None:
            rejected.append(
                (
                    candidate,
                    (ConstraintViolation("engine", f"unknown engine {candidate.engine_id}"),),
                )
            )
            continue
        rule = engine_rules.get(candidate.engine_id, EngineRule(engine_id=candidate.engine_id))
        violations = check_constraints(
            candidate,
            model=model,
            engine=engine,
            engine_rule=rule,
            budget=budget,
            requirements=requirements,
            trust_violations=trust_violations,
            operator=operator,
        )
        if violations:
            rejected.append((candidate, violations))
        else:
            viable.append(candidate)
    return tuple(viable), tuple(rejected)
