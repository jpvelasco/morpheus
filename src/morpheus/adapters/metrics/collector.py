from __future__ import annotations

from typing import Any

from morpheus.adapters.metrics.vllm import VllmMetricsAdapter
from morpheus.core.metrics_history import MetricSample

_MIB_TO_BYTES = 1024 * 1024


async def collect_metrics(
    *,
    engine: VllmMetricsAdapter | None,
    host: dict[str, Any],
    observed_at: str,
) -> tuple[tuple[MetricSample, ...], tuple[tuple[str, str, str | None], ...]]:
    """Sample configured sources into persisted metric history entries.

    Every source is reported with an explicit state and reason; unconfigured
    or failing sources are never treated as zero-valued evidence.
    """
    samples: list[MetricSample] = []
    sources: list[tuple[str, str, str | None]] = []

    if engine is None:
        sources.append(("engine", "unavailable", "metrics_url_not_configured"))
    else:
        try:
            snapshot = await engine.collect()
        except ValueError:
            sources.append(("engine", "unavailable", "engine_metrics_invalid"))
        except Exception:  # Network failures must never fail the operations API.
            sources.append(("engine", "unavailable", "engine_metrics_unreachable"))
        else:
            sources.append(("engine", "available", None))
            samples.extend(
                MetricSample(
                    observed_at=observed_at,
                    source="engine",
                    signal=signal,
                    value=value,
                )
                for signal, value in snapshot.values.items()
            )

    if host.get("status") not in {"available", "degraded"}:
        sources.append(
            ("host", "unavailable", str(host.get("reason", "runtime_agent_unavailable")))
        )
        return tuple(samples), tuple(sources)

    sources.append(("host", "available", None))
    memory = host.get("memory")
    if isinstance(memory, dict) and isinstance(memory.get("available_bytes"), int | float):
        samples.append(
            MetricSample(
                observed_at=observed_at,
                source="host",
                signal="memory_available_bytes",
                value=float(memory["available_bytes"]),
            )
        )
    disk = host.get("disk")
    if isinstance(disk, dict) and isinstance(disk.get("free_bytes"), int | float):
        samples.append(
            MetricSample(
                observed_at=observed_at,
                source="host",
                signal="free_bytes",
                value=float(disk["free_bytes"]),
            )
        )
    gpu = host.get("gpu")
    if isinstance(gpu, dict):
        if isinstance(gpu.get("memory_used_mib"), int | float):
            samples.append(
                MetricSample(
                    observed_at=observed_at,
                    source="host",
                    signal="memory_used_bytes",
                    value=float(gpu["memory_used_mib"]) * _MIB_TO_BYTES,
                )
            )
        if isinstance(gpu.get("utilization_percent"), int | float):
            samples.append(
                MetricSample(
                    observed_at=observed_at,
                    source="host",
                    signal="utilization_percent",
                    value=float(gpu["utilization_percent"]),
                )
            )
        if isinstance(gpu.get("temperature_c"), int | float):
            samples.append(
                MetricSample(
                    observed_at=observed_at,
                    source="host",
                    signal="temperature_c",
                    value=float(gpu["temperature_c"]),
                )
            )
    return tuple(samples), tuple(sources)
