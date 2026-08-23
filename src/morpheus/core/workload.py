"""Versioned developer workload profiles (SEL-003)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WEIGHT_METRICS = (
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
)


class WorkloadError(ValueError):
    """A workload profile violates its contract."""


def _bounded(value: str, what: str) -> str:
    if not value or len(value) > 128 or any(character.isspace() for character in value):
        raise WorkloadError(f"{what} must be a bounded identifier")
    return value


def _weights(pairs: Any, what: str) -> tuple[tuple[str, float], ...]:
    if not isinstance(pairs, list) or not all(
        isinstance(item, list) and len(item) == 2 for item in pairs
    ):
        raise WorkloadError(f"{what} must be a list of metric/weight pairs")
    result: list[tuple[str, float]] = []
    for metric, weight in pairs:
        if metric not in WEIGHT_METRICS:
            raise WorkloadError(f"unknown weight metric: {metric}")
        value = float(weight)
        if value < 0:
            raise WorkloadError(f"weight for {metric} must be non-negative")
        result.append((metric, value))
    return tuple(result)


def normalize_weights(pairs: tuple[tuple[str, float], ...]) -> tuple[tuple[str, float], ...]:
    """Scale weights to sum to 1; zero-weight metrics are dropped."""
    total = sum(weight for _, weight in pairs)
    if total <= 0:
        raise WorkloadError("profile must declare at least one positive weight")
    return tuple((metric, weight / total) for metric, weight in pairs if weight > 0)


@dataclass(frozen=True, slots=True)
class WorkloadPolicy:
    id: str
    version: str
    name: str
    weights: tuple[tuple[str, float], ...]
    features: tuple[str, ...] = ()
    context_tokens: int = 4096
    concurrency: int = 1

    def __post_init__(self) -> None:
        _bounded(self.id, "workload id")
        _bounded(self.version, "workload version")
        if self.context_tokens < 1 or self.concurrency < 1:
            raise WorkloadError("context and concurrency must be positive")
        normalized = normalize_weights(self.weights)
        if normalized != self.weights:
            object.__setattr__(self, "weights", normalized)

    def weight(self, metric: str) -> float:
        return dict(self.weights).get(metric, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "weights": [[metric, weight] for metric, weight in self.weights],
            "features": list(self.features),
            "context_tokens": self.context_tokens,
            "concurrency": self.concurrency,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkloadPolicy:
        return cls(
            id=str(payload["id"]),
            version=str(payload["version"]),
            name=str(payload["name"]),
            weights=_weights(payload["weights"], "weights"),
            features=tuple(str(item) for item in payload.get("features", [])),
            context_tokens=int(payload.get("context_tokens", 4096)),
            concurrency=int(payload.get("concurrency", 1)),
        )


SEED_PROFILES: tuple[WorkloadPolicy, ...] = (
    WorkloadPolicy(
        id="developer-default",
        version="2026.2",
        name="Developer default",
        weights=(
            ("coding_correctness", 0.2),
            ("tool_use", 0.15),
            ("agentic_behavior", 0.1),
            ("long_context_coherence", 0.1),
            ("time_to_first_token", 0.1),
            ("decode_throughput", 0.1),
            ("concurrency", 0.05),
            ("stability", 0.1),
            ("memory_headroom", 0.05),
            ("resource_cost", 0.05),
        ),
        features=("tool_calling",),
        context_tokens=8192,
        concurrency=1,
    ),
    WorkloadPolicy(
        id="agentic-light",
        version="2026.2",
        name="Agentic light",
        weights=(
            ("agentic_behavior", 0.35),
            ("tool_use", 0.25),
            ("coding_correctness", 0.2),
            ("time_to_first_token", 0.1),
            ("decode_throughput", 0.1),
        ),
        features=("tool_calling",),
        context_tokens=16_384,
        concurrency=1,
    ),
    WorkloadPolicy(
        id="long-context-batch",
        version="2026.2",
        name="Long-context batch",
        weights=(
            ("long_context_coherence", 0.4),
            ("decode_throughput", 0.3),
            ("stability", 0.2),
            ("resource_cost", 0.1),
        ),
        features=("long-context",),
        context_tokens=32_768,
        concurrency=2,
    ),
)


@dataclass(frozen=True, slots=True)
class OperatorConstraints:
    """Operator caps applied on top of hardware budgets (SEL-003)."""

    max_context: int | None = None
    max_concurrency: int | None = None
    allowed_engines: tuple[str, ...] = ()
    allowed_quantizations: tuple[str, ...] = ()
    max_ram_bytes: int | None = None
    max_vram_bytes: int | None = None
    max_storage_bytes: int | None = None

    def __post_init__(self) -> None:
        for field in (
            self.max_context,
            self.max_concurrency,
            self.max_ram_bytes,
            self.max_vram_bytes,
            self.max_storage_bytes,
        ):
            if field is not None and field <= 0:
                raise WorkloadError("operator caps must be positive when declared")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_context": self.max_context,
            "max_concurrency": self.max_concurrency,
            "allowed_engines": self.allowed_engines,
            "allowed_quantizations": self.allowed_quantizations,
            "max_ram_bytes": self.max_ram_bytes,
            "max_vram_bytes": self.max_vram_bytes,
            "max_storage_bytes": self.max_storage_bytes,
        }


def monotonic_budget_holds(
    smaller: tuple[tuple[str, int], ...],
    larger: tuple[tuple[str, int], ...],
) -> bool:
    """True when every declared budget dimension of ``larger`` >= ``smaller``."""
    dims = dict(larger)
    return all(dims.get(key, 0) >= value for key, value in smaller)
