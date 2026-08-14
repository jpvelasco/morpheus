"""Immutable benchmark entities and reducers (BENCH-002, BENCH-003)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_BOUNDED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

CAMPAIGN_TYPES = (
    "speed",
    "coding",
    "tools",
    "long-context",
    "context-bump",
    "mtp",
    "supporting-software",
)
RESOURCES = ("ram", "vram", "cpu", "disk")
STOP_CONDITIONS = ("max_errors", "max_runtime_seconds", "target_samples")
STATISTICS = ("mean", "p50", "p95")


class BenchmarkError(ValueError):
    """A benchmark entity or document violates its contract."""


def bounded_identifier(value: str, what: str) -> str:
    if not _BOUNDED.fullmatch(value):
        raise BenchmarkError(f"{what} must be a bounded identifier")
    return value


def key_identifier(value: str, what: str) -> str:
    if not _KEY.fullmatch(value):
        raise BenchmarkError(f"{what} must be a bounded key")
    return value


def positive_int(value: int | None, what: str) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise BenchmarkError(f"{what} must be positive when known")
    return value


def non_negative_float(value: float | None, what: str) -> float | None:
    if value is None:
        return None
    if value < 0 or not math.isfinite(value):
        raise BenchmarkError(f"{what} must be a finite non-negative number")
    return value


def _pairs(value: Any, what: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, list) and len(item) == 2 and all(isinstance(part, str) for part in item)
        for item in value
    ):
        raise BenchmarkError(f"{what} must be a list of string pairs")
    return tuple((key_identifier(k, what), bounded_identifier(v, what)) for k, v in value)


def aware_utc(value: str | None, what: str) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise BenchmarkError(f"{what} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CampaignDeclaration:
    """Declared campaign limits and ownership (BENCH-005)."""

    name: str
    campaign_type: str
    benchmark_revision: str
    duration_seconds: int
    concurrency: int
    ownership_target: str
    workload_parameters: tuple[tuple[str, str], ...] = ()
    resource_envelope: tuple[tuple[str, int], ...] = ()
    request_shape: tuple[tuple[str, str], ...] = ()
    stop_conditions: tuple[tuple[str, int], ...] = (
        ("target_samples", 1_000),
        ("max_runtime_seconds", 7_200),
    )

    def __post_init__(self) -> None:
        bounded_identifier(self.name, "campaign name")
        if self.campaign_type not in CAMPAIGN_TYPES:
            raise BenchmarkError(f"unknown campaign type: {self.campaign_type}")
        bounded_identifier(self.benchmark_revision, "benchmark revision")
        positive_int(self.duration_seconds, "duration")
        positive_int(self.concurrency, "concurrency")
        bounded_identifier(self.ownership_target, "ownership target")
        for key, _ in self.workload_parameters:
            key_identifier(key, "workload parameter")
        for resource, amount in self.resource_envelope:
            if resource not in RESOURCES:
                raise BenchmarkError(f"unknown resource: {resource}")
            positive_int(amount, "resource envelope amount")
        for condition, limit in self.stop_conditions:
            if condition not in STOP_CONDITIONS:
                raise BenchmarkError(f"unknown stop condition: {condition}")
            positive_int(limit, "stop condition limit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "campaign_type": self.campaign_type,
            "benchmark_revision": self.benchmark_revision,
            "duration_seconds": self.duration_seconds,
            "concurrency": self.concurrency,
            "ownership_target": self.ownership_target,
            "workload_parameters": [list(pair) for pair in self.workload_parameters],
            "resource_envelope": [[k, str(v)] for k, v in self.resource_envelope],
            "request_shape": [list(pair) for pair in self.request_shape],
            "stop_conditions": [[k, str(v)] for k, v in self.stop_conditions],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CampaignDeclaration:
        return cls(
            name=payload["name"],
            campaign_type=payload["campaign_type"],
            benchmark_revision=payload["benchmark_revision"],
            duration_seconds=payload["duration_seconds"],
            concurrency=payload["concurrency"],
            ownership_target=payload["ownership_target"],
            workload_parameters=_pairs(
                payload.get("workload_parameters", []), "workload_parameters"
            ),
            resource_envelope=tuple(
                (k, int(v))
                for k, v in _pairs(payload.get("resource_envelope", []), "resource_envelope")
            ),
            request_shape=_pairs(payload.get("request_shape", []), "request_shape"),
            stop_conditions=tuple(
                (k, int(v))
                for k, v in _pairs(payload.get("stop_conditions", []), "stop_conditions")
            ),
        )


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Complete provenance identity for a campaign run (BENCH-002)."""

    machine_id: str
    model_id: str
    model_revision: str
    quantization: str
    engine_id: str
    engine_version: str
    benchmark_revision: str
    launch_configuration: tuple[tuple[str, str], ...] = ()
    model_digest: str | None = None
    context_window: int | None = None
    warmup_samples: int = 0
    software_version: str | None = None

    def __post_init__(self) -> None:
        for field, value in {
            "machine_id": self.machine_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "benchmark_revision": self.benchmark_revision,
        }.items():
            bounded_identifier(value, field)

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "benchmark_revision": self.benchmark_revision,
            "launch_configuration": [list(pair) for pair in self.launch_configuration],
            "model_digest": self.model_digest,
            "context_window": self.context_window,
            "warmup_samples": self.warmup_samples,
            "software_version": self.software_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunIdentity:
        return cls(
            machine_id=payload["machine_id"],
            model_id=payload["model_id"],
            model_revision=payload["model_revision"],
            quantization=payload["quantization"],
            engine_id=payload["engine_id"],
            engine_version=payload["engine_version"],
            benchmark_revision=payload["benchmark_revision"],
            launch_configuration=_pairs(
                payload.get("launch_configuration", []), "launch_configuration"
            ),
            model_digest=payload.get("model_digest"),
            context_window=positive_int(payload.get("context_window"), "context window"),
            warmup_samples=payload.get("warmup_samples", 0),
            software_version=payload.get("software_version"),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    """One normalized request observation from a campaign run."""

    run_id: str
    started_at: datetime
    sequence_index: int
    duration_seconds: float | None = None
    ttft_seconds: float | None = None
    tokens_per_second: float | None = None
    generated_tokens: int | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        bounded_identifier(self.run_id, "run id")
        if self.started_at.tzinfo is None:
            raise BenchmarkError("sample timestamp must be timezone-aware")
        if self.sequence_index < 0:
            raise BenchmarkError("sequence index must be non-negative")
        non_negative_float(self.duration_seconds, "duration")
        non_negative_float(self.ttft_seconds, "ttft")
        non_negative_float(self.tokens_per_second, "tokens per second")
        positive_int(self.generated_tokens, "generated tokens")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "sequence_index": self.sequence_index,
            "duration_seconds": self.duration_seconds,
            "ttft_seconds": self.ttft_seconds,
            "tokens_per_second": self.tokens_per_second,
            "generated_tokens": self.generated_tokens,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkSample:
        return cls(
            run_id=payload["run_id"],
            started_at=aware_utc(payload["started_at"], "sample timestamp") or datetime.now(UTC),
            sequence_index=payload["sequence_index"],
            duration_seconds=non_negative_float(payload.get("duration_seconds"), "duration"),
            ttft_seconds=non_negative_float(payload.get("ttft_seconds"), "ttft"),
            tokens_per_second=non_negative_float(
                payload.get("tokens_per_second"), "tokens per second"
            ),
            generated_tokens=positive_int(payload.get("generated_tokens"), "generated tokens"),
            error=payload.get("error"),
        )


def _statistic(values: list[float], statistic: str) -> float | None:
    if not values:
        return None
    if statistic == "mean":
        return sum(values) / len(values)
    if statistic == "p50":
        ordered = sorted(values)
        return ordered[len(ordered) // 2]
    if statistic == "p95":
        ordered = sorted(values)
        index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
        return ordered[index]
    raise BenchmarkError(f"unknown statistic: {statistic}")


def _dispersion(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    """Normalized summary over samples with explicit run variation (BENCH-004)."""

    run_id: str
    sample_count: int
    statistic: str
    baseline_run_id: str | None = None
    ttft_seconds: float | None = None
    tokens_per_second: float | None = None
    duration_seconds: float | None = None
    run_variation: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        bounded_identifier(self.run_id, "run id")
        if self.sample_count < 0:
            raise BenchmarkError("sample count must be non-negative")
        if self.statistic not in STATISTICS:
            raise BenchmarkError(f"unknown statistic: {self.statistic}")
        for metric, _ in self.run_variation:
            key_identifier(metric, "variation metric")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sample_count": self.sample_count,
            "statistic": self.statistic,
            "baseline_run_id": self.baseline_run_id,
            "ttft_seconds": self.ttft_seconds,
            "tokens_per_second": self.tokens_per_second,
            "duration_seconds": self.duration_seconds,
            "run_variation": [[metric, str(value)] for metric, value in self.run_variation],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkSummary:
        return cls(
            run_id=payload["run_id"],
            sample_count=payload["sample_count"],
            statistic=payload["statistic"],
            baseline_run_id=payload.get("baseline_run_id"),
            ttft_seconds=non_negative_float(payload.get("ttft_seconds"), "ttft"),
            tokens_per_second=non_negative_float(
                payload.get("tokens_per_second"), "tokens per second"
            ),
            duration_seconds=non_negative_float(payload.get("duration_seconds"), "duration"),
            run_variation=tuple(
                (k, float(v)) for k, v in _pairs(payload.get("run_variation", []), "run_variation")
            ),
        )


def summarize_samples(
    run_id: str,
    samples: tuple[BenchmarkSample, ...],
    statistic: str = "p50",
    baseline_run_id: str | None = None,
) -> BenchmarkSummary:
    """Reduce samples into a summary with the declared statistic and dispersion."""
    completed = [sample for sample in samples if sample.error is None]
    ttft = [sample.ttft_seconds for sample in completed if sample.ttft_seconds is not None]
    tokens = [
        sample.tokens_per_second for sample in completed if sample.tokens_per_second is not None
    ]
    duration = [
        sample.duration_seconds for sample in completed if sample.duration_seconds is not None
    ]
    variation = tuple(
        (metric, value)
        for metric, value in (
            ("ttft_seconds", _dispersion(ttft)),
            ("tokens_per_second", _dispersion(tokens)),
        )
        if value is not None
    )
    return BenchmarkSummary(
        run_id=run_id,
        sample_count=len(completed),
        statistic=statistic,
        baseline_run_id=baseline_run_id,
        ttft_seconds=_statistic(ttft, statistic),
        tokens_per_second=_statistic(tokens, statistic),
        duration_seconds=_statistic(duration, statistic),
        run_variation=variation,
    )


def regenerate_summary(samples: tuple[BenchmarkSample, ...], statistic: str) -> BenchmarkSummary:
    """Recompute a summary from raw samples; must reproduce the original."""
    if not samples:
        raise BenchmarkError("cannot regenerate from an empty sample set")
    return summarize_samples(samples[0].run_id, samples, statistic)
