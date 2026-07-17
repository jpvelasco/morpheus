from __future__ import annotations

import math

import pytest

from morpheus.core.performance import (
    ContainerResourceSample,
    LoadMetrics,
    assess_load_overhead,
    assess_resource_budget,
    assess_resource_growth,
)
from morpheus.ops.performance import parse_docker_stats, parse_k6_summary


def _summary(*, waiting: float, rate: float, checks: float = 1.0, failed: float = 0.0):
    return {
        "metrics": {
            "http_req_waiting": {"values": {"med": waiting}},
            "iterations": {"values": {"rate": rate}},
            "checks": {"values": {"rate": checks}},
            "http_req_failed": {"values": {"rate": failed}},
            "http_reqs": {"values": {"count": 600}},
        }
    }


def test_LOAD_003_k6_summary_parser_and_overhead_budget_pass() -> None:
    direct = parse_k6_summary(_summary(waiting=10.0, rate=100.0))
    proxied = parse_k6_summary(_summary(waiting=29.5, rate=98.5))

    result = assess_load_overhead(direct=direct, proxied=proxied)

    assert direct == LoadMetrics(
        median_waiting_ms=10.0,
        iterations_per_second=100.0,
        checks_rate=1.0,
        failed_rate=0.0,
        request_count=600,
    )
    assert result.added_median_waiting_ms == 19.5
    assert result.throughput_loss_percent == pytest.approx(1.5)
    assert result.passed is True


@pytest.mark.parametrize(
    ("direct", "proxied"),
    [
        (LoadMetrics(10, 100, 1, 0, 10), LoadMetrics(35, 99, 1, 0, 10)),
        (LoadMetrics(10, 100, 1, 0, 10), LoadMetrics(20, 98, 1, 0, 10)),
        (LoadMetrics(10, 100, 1, 0, 10), LoadMetrics(20, 99, 0.99, 0, 10)),
        (LoadMetrics(10, 100, 1, 0, 10), LoadMetrics(20, 99, 1, 0.01, 10)),
    ],
)
def test_LOAD_003_thresholds_are_strict_and_errors_block(direct, proxied) -> None:
    assert assess_load_overhead(direct=direct, proxied=proxied).passed is False


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"metrics": {}},
        _summary(waiting=math.nan, rate=10),
        _summary(waiting=1, rate=0),
        _summary(waiting=1, rate=10, checks=1.1),
    ],
)
def test_LOAD_001_invalid_k6_evidence_fails_closed(document) -> None:
    with pytest.raises(ValueError, match="k6 summary"):
        parse_k6_summary(document)


def test_PERF_002_docker_stats_parser_uses_structured_json_and_binary_units() -> None:
    sample = parse_docker_stats(
        {
            "ID": "a" * 64,
            "Name": "morpheus-api-1",
            "CPUPerc": "0.25%",
            "MemUsage": "12.5MiB / 512MiB",
            "PIDs": "7",
        },
        component="api",
    )

    assert sample == ContainerResourceSample(
        component="api",
        container_id="a" * 64,
        memory_bytes=13_107_200,
        cpu_percent=0.25,
        pids=7,
    )


def test_PERF_002_combined_idle_budget_requires_every_core_component() -> None:
    samples = (
        ContainerResourceSample("api", "a" * 64, 300 * 1024**2, 0.5, 7),
        ContainerResourceSample("dashboard", "b" * 64, 200 * 1024**2, 0.25, 5),
    )

    result = assess_resource_budget(samples, required_components=("api", "dashboard"))

    assert result.total_memory_bytes == 500 * 1024**2
    assert result.total_cpu_percent == 0.75
    assert result.missing_components == ()
    assert result.passed is True


def test_PERF_002_missing_duplicate_or_over_budget_samples_fail_closed() -> None:
    missing = (ContainerResourceSample("api", "a" * 64, 100, 0.1, 1),)
    assert assess_resource_budget(missing, required_components=("api", "dashboard")).passed is False

    duplicate = (
        ContainerResourceSample("api", "a" * 64, 100, 0.1, 1),
        ContainerResourceSample("api", "b" * 64, 100, 0.1, 1),
    )
    with pytest.raises(ValueError, match="duplicate"):
        assess_resource_budget(duplicate, required_components=("api",))

    over = (
        ContainerResourceSample("api", "a" * 64, 1024**3, 2.0, 1),
        ContainerResourceSample("dashboard", "b" * 64, 1, 0.0, 1),
    )
    assert assess_resource_budget(over, required_components=("api", "dashboard")).passed is False


def test_RES_001_active_samples_record_cpu_without_applying_the_idle_cpu_budget() -> None:
    active = (
        ContainerResourceSample("api", "a" * 64, 100 * 1024**2, 37.5, 7),
        ContainerResourceSample("dashboard", "b" * 64, 50 * 1024**2, 4.0, 5),
    )

    result = assess_resource_budget(
        active,
        required_components=("api", "dashboard"),
        max_idle_cpu_percent=None,
    )

    assert result.total_cpu_percent == 41.5
    assert result.max_idle_cpu_percent is None
    assert result.passed is True


def test_SOAK_002_resource_growth_budget_passes_a_stable_series() -> None:
    start = assess_resource_budget(
        (ContainerResourceSample("api", "a" * 64, 100 * 1024**2, 0.1, 7),),
        required_components=("api",),
    )
    end = assess_resource_budget(
        (ContainerResourceSample("api", "a" * 64, 108 * 1024**2, 0.1, 8),),
        required_components=("api",),
    )

    result = assess_resource_growth((start, end))

    assert result.memory_growth_bytes == 8 * 1024**2
    assert result.pid_growth == 1
    assert result.passed is True


def test_SOAK_002_resource_growth_budget_rejects_sustained_growth_below_absolute_cap() -> None:
    start = assess_resource_budget(
        (ContainerResourceSample("api", "a" * 64, 100 * 1024**2, 0.1, 4),),
        required_components=("api",),
    )
    end = assess_resource_budget(
        (ContainerResourceSample("api", "a" * 64, 200 * 1024**2, 0.1, 20),),
        required_components=("api",),
    )

    result = assess_resource_growth((start, end))

    assert result.passed is False
    assert result.memory_growth_bytes == 100 * 1024**2
    assert result.pid_growth == 16


def test_SOAK_002_resource_growth_requires_at_least_two_samples() -> None:
    with pytest.raises(ValueError, match="two resource"):
        assess_resource_growth(())
