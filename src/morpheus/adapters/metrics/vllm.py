from __future__ import annotations

from io import StringIO

import httpx
from prometheus_client.parser import text_fd_to_metric_families

from morpheus.core.metrics import MetricsSnapshot

EXPECTED_SIGNALS = {
    "vllm:num_requests_running": "requests_running",
    "vllm:num_requests_waiting": "requests_waiting",
    "vllm:gpu_cache_usage_perc": "gpu_cache_usage",
    "vllm:kv_cache_usage_perc": "gpu_cache_usage",
    "vllm:prompt_tokens_total": "prompt_tokens_total",
    "vllm:generation_tokens_total": "generation_tokens_total",
    "vllm:request_success_total": "request_success_total",
}


def parse_vllm_metrics(text: str) -> MetricsSnapshot:
    values: dict[str, float] = {}
    found: set[str] = set()
    try:
        families = text_fd_to_metric_families(StringIO(text))
        for family in families:
            for sample in family.samples:
                output_name = EXPECTED_SIGNALS.get(sample.name)
                if output_name is None:
                    continue
                found.add(output_name)
                values[output_name] = values.get(output_name, 0.0) + float(sample.value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid Prometheus metrics") from error
    if (
        not values
        and text.strip()
        and not any(marker in text for marker in ("# HELP", "# TYPE", "{"))
        and " " not in text.strip()
    ):
        raise ValueError("invalid Prometheus metrics")
    expected = frozenset(EXPECTED_SIGNALS.values())
    return MetricsSnapshot(
        values=values,
        available_signals=frozenset(found),
        missing_signals=expected.difference(found),
    )


class VllmMetricsAdapter:
    def __init__(
        self,
        *,
        metrics_url: str,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._metrics_url = metrics_url
        self._timeout = timeout_seconds
        self._client = client

    async def collect(self) -> MetricsSnapshot:
        if self._client is None:
            async with httpx.AsyncClient() as client:
                response = await client.get(self._metrics_url, timeout=self._timeout)
        else:
            response = await self._client.get(self._metrics_url, timeout=self._timeout)
        response.raise_for_status()
        return parse_vllm_metrics(response.text)
