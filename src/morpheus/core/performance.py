from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoadMetrics:
    median_waiting_ms: float
    iterations_per_second: float
    checks_rate: float
    failed_rate: float
    request_count: int

    def __post_init__(self) -> None:
        numbers = (
            self.median_waiting_ms,
            self.iterations_per_second,
            self.checks_rate,
            self.failed_rate,
        )
        if not all(math.isfinite(value) for value in numbers):
            raise ValueError("load metrics must be finite")
        if self.median_waiting_ms < 0 or self.iterations_per_second <= 0:
            raise ValueError("load latency and throughput must be positive")
        if not 0 <= self.checks_rate <= 1 or not 0 <= self.failed_rate <= 1:
            raise ValueError("load result rates must be within zero and one")
        if self.request_count < 1:
            raise ValueError("load request count must be positive")


@dataclass(frozen=True, slots=True)
class LoadOverheadAssessment:
    added_median_waiting_ms: float
    throughput_loss_percent: float
    max_added_median_waiting_ms: float
    max_throughput_loss_percent: float
    passed: bool


def assess_load_overhead(
    *,
    direct: LoadMetrics,
    proxied: LoadMetrics,
    max_added_median_waiting_ms: float = 25.0,
    max_throughput_loss_percent: float = 2.0,
) -> LoadOverheadAssessment:
    if max_added_median_waiting_ms <= 0 or max_throughput_loss_percent <= 0:
        raise ValueError("load overhead thresholds must be positive")
    added = proxied.median_waiting_ms - direct.median_waiting_ms
    loss = (
        (direct.iterations_per_second - proxied.iterations_per_second)
        / direct.iterations_per_second
    ) * 100
    passed = (
        added < max_added_median_waiting_ms
        and loss < max_throughput_loss_percent
        and direct.checks_rate == 1
        and proxied.checks_rate == 1
        and direct.failed_rate == 0
        and proxied.failed_rate == 0
    )
    return LoadOverheadAssessment(
        added_median_waiting_ms=added,
        throughput_loss_percent=loss,
        max_added_median_waiting_ms=max_added_median_waiting_ms,
        max_throughput_loss_percent=max_throughput_loss_percent,
        passed=passed,
    )


@dataclass(frozen=True, slots=True)
class ContainerResourceSample:
    component: str
    container_id: str
    memory_bytes: int
    cpu_percent: float
    pids: int

    def __post_init__(self) -> None:
        if not self.component or not self.container_id:
            raise ValueError("resource sample identity is required")
        if self.memory_bytes < 0 or self.pids < 0:
            raise ValueError("resource counters must not be negative")
        if not math.isfinite(self.cpu_percent) or self.cpu_percent < 0:
            raise ValueError("resource CPU must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ResourceBudgetAssessment:
    total_memory_bytes: int
    total_cpu_percent: float
    total_pids: int
    max_memory_bytes: int
    max_idle_cpu_percent: float | None
    missing_components: tuple[str, ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class ResourceGrowthAssessment:
    start_memory_bytes: int
    end_memory_bytes: int
    peak_memory_bytes: int
    memory_growth_bytes: int
    max_memory_growth_bytes: int
    start_pids: int
    end_pids: int
    peak_pids: int
    pid_growth: int
    max_pid_growth: int
    passed: bool


def assess_resource_budget(
    samples: tuple[ContainerResourceSample, ...],
    *,
    required_components: tuple[str, ...],
    max_memory_bytes: int = 1024**3,
    max_idle_cpu_percent: float | None = 2.0,
) -> ResourceBudgetAssessment:
    if not required_components or len(set(required_components)) != len(required_components):
        raise ValueError("required resource components must be unique and non-empty")
    if max_memory_bytes <= 0 or (max_idle_cpu_percent is not None and max_idle_cpu_percent <= 0):
        raise ValueError("resource budgets must be positive")
    by_component: dict[str, ContainerResourceSample] = {}
    for sample in samples:
        if sample.component in by_component:
            raise ValueError("duplicate resource sample component")
        by_component[sample.component] = sample
    missing = tuple(item for item in required_components if item not in by_component)
    total_memory = sum(item.memory_bytes for item in samples)
    total_cpu = sum(item.cpu_percent for item in samples)
    total_pids = sum(item.pids for item in samples)
    return ResourceBudgetAssessment(
        total_memory_bytes=total_memory,
        total_cpu_percent=total_cpu,
        total_pids=total_pids,
        max_memory_bytes=max_memory_bytes,
        max_idle_cpu_percent=max_idle_cpu_percent,
        missing_components=missing,
        passed=not missing
        and total_memory < max_memory_bytes
        and (max_idle_cpu_percent is None or total_cpu < max_idle_cpu_percent),
    )


def assess_resource_growth(
    series: tuple[ResourceBudgetAssessment, ...],
    *,
    max_memory_growth_bytes: int = 64 * 1024**2,
    max_pid_growth: int = 8,
) -> ResourceGrowthAssessment:
    if len(series) < 2:
        raise ValueError("at least two resource assessments are required")
    if max_memory_growth_bytes < 0 or max_pid_growth < 0:
        raise ValueError("resource growth budgets must not be negative")
    start = series[0]
    end = series[-1]
    memory_growth = end.total_memory_bytes - start.total_memory_bytes
    pid_growth = end.total_pids - start.total_pids
    return ResourceGrowthAssessment(
        start_memory_bytes=start.total_memory_bytes,
        end_memory_bytes=end.total_memory_bytes,
        peak_memory_bytes=max(item.total_memory_bytes for item in series),
        memory_growth_bytes=memory_growth,
        max_memory_growth_bytes=max_memory_growth_bytes,
        start_pids=start.total_pids,
        end_pids=end.total_pids,
        peak_pids=max(item.total_pids for item in series),
        pid_growth=pid_growth,
        max_pid_growth=max_pid_growth,
        passed=all(item.passed for item in series)
        and memory_growth <= max_memory_growth_bytes
        and pid_growth <= max_pid_growth,
    )
