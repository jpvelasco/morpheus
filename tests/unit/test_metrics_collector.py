from __future__ import annotations

import httpx

from morpheus.adapters.metrics.collector import collect_metrics
from morpheus.core.metrics import MetricsSnapshot

NOW = "2026-08-15T12:00:00+00:00"


class _FailingEngine:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def collect(self) -> MetricsSnapshot:
        raise self._error


class _HealthyEngine:
    async def collect(self) -> MetricsSnapshot:
        return MetricsSnapshot(
            values={
                "requests_running": 2.0,
                "gpu_cache_usage": 41.5,
                "request_success_total": 99.0,
            },
            available_signals=frozenset(
                {"requests_running", "gpu_cache_usage", "request_success_total"}
            ),
            missing_signals=frozenset({"requests_waiting", "prompt_tokens_total"}),
        )


async def test_collect_reports_engine_unavailable_when_no_metrics_url_configured() -> None:
    samples, sources = await collect_metrics(engine=None, host={}, observed_at=NOW)
    assert samples == ()
    assert ("engine", "unavailable", "metrics_url_not_configured") in sources


async def test_collect_maps_engine_failures_to_honest_reasons() -> None:
    for error, expected in (
        (httpx.ConnectError("boom"), "engine_metrics_unreachable"),
        (ValueError("bad prometheus"), "engine_metrics_invalid"),
    ):
        samples, sources = await collect_metrics(
            engine=_FailingEngine(error), host={}, observed_at=NOW
        )
        assert samples == ()
        assert ("engine", "unavailable", expected) in sources


async def test_collect_maps_engine_snapshot_values_to_samples() -> None:
    samples, sources = await collect_metrics(engine=_HealthyEngine(), host={}, observed_at=NOW)
    assert ("engine", "available", None) in sources
    by_signal = {sample.signal: sample for sample in samples}
    assert set(by_signal) == {"requests_running", "gpu_cache_usage", "request_success_total"}
    assert by_signal["gpu_cache_usage"].value == 41.5
    assert all(sample.source == "engine" for sample in samples)
    assert all(sample.observed_at == NOW for sample in samples)


async def test_collect_reports_host_unavailable_without_evidence() -> None:
    samples, sources = await collect_metrics(
        engine=None,
        host={"status": "unavailable", "reason": "runtime_agent_not_configured"},
        observed_at=NOW,
    )
    assert samples == ()
    assert ("host", "unavailable", "runtime_agent_not_configured") in sources


async def test_collect_maps_host_memory_and_gpu_evidence_to_samples() -> None:
    host = {
        "status": "available",
        "memory": {"total_bytes": 64_000_000_000, "available_bytes": 32_000_000_000},
        "gpu": {
            "memory_total_mib": 16_384,
            "memory_used_mib": 12_288,
            "utilization_percent": 71,
            "temperature_c": 62,
        },
    }
    samples, sources = await collect_metrics(engine=None, host=host, observed_at=NOW)
    assert ("host", "available", None) in sources
    by_signal = {sample.signal: sample for sample in samples}
    assert by_signal["memory_available_bytes"].value == 32_000_000_000.0
    assert by_signal["memory_used_bytes"].value == 12_288 * 1024 * 1024
    assert by_signal["utilization_percent"].value == 71.0
    assert by_signal["temperature_c"].value == 62.0
    assert all(sample.source == "host" for sample in samples)


async def test_collect_host_without_gpu_records_only_memory_evidence() -> None:
    host = {
        "status": "available",
        "memory": {"total_bytes": 64_000_000_000, "available_bytes": 32_000_000_000},
    }
    samples, sources = await collect_metrics(engine=None, host=host, observed_at=NOW)
    assert ("host", "available", None) in sources
    assert [sample.signal for sample in samples] == ["memory_available_bytes"]


async def test_collect_combines_engine_and_host_sources() -> None:
    host = {"status": "available", "gpu": {"memory_used_mib": 8_192, "utilization_percent": 50}}
    samples, sources = await collect_metrics(engine=_HealthyEngine(), host=host, observed_at=NOW)
    assert {name for name, _, _ in sources} == {"engine", "host"}
    assert len(samples) == 5


async def test_collect_disk_free_bytes_maps_from_host_evidence() -> None:
    host = {
        "status": "available",
        "disk": {"total_bytes": 1_000_000_000, "free_bytes": 250_000_000},
    }
    samples, _ = await collect_metrics(engine=None, host=host, observed_at=NOW)
    by_signal = {sample.signal: sample for sample in samples}
    assert by_signal["free_bytes"].value == 250_000_000.0


async def test_collect_ignores_unknown_host_fields() -> None:
    samples, _ = await collect_metrics(
        engine=None,
        host={"status": "available", "services": [{"component": "search"}]},
        observed_at=NOW,
    )
    assert samples == ()
