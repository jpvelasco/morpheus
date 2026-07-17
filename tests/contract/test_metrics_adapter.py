from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from morpheus.adapters.metrics.vllm import VllmMetricsAdapter, parse_vllm_metrics

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def test_RUN_003_parses_expected_metrics_and_ignores_unknown_families() -> None:
    text = (ROOT / "tests/fixtures/vllm-metrics.prom").read_text(encoding="utf-8")
    result = parse_vllm_metrics(text)

    assert result.values["requests_running"] == 2
    assert result.values["requests_waiting"] == 1
    assert result.values["gpu_cache_usage"] == 0.42
    assert result.values["prompt_tokens_total"] == 1000
    assert "unknown_future_metric" not in result.values
    assert "generation_tokens_total" in result.available_signals


def test_RUN_003_missing_metrics_are_reported_without_fabricated_zeroes() -> None:
    result = parse_vllm_metrics("vllm:num_requests_running 0\n")
    assert result.values == {"requests_running": 0.0}
    assert "requests_waiting" in result.missing_signals
    assert "requests_waiting" not in result.values


def test_RUN_003_accepts_current_vllm_kv_cache_metric_name() -> None:
    result = parse_vllm_metrics("vllm:kv_cache_usage_perc 0.57\n")

    assert result.values == {"gpu_cache_usage": 0.57}
    assert "gpu_cache_usage" in result.available_signals
    assert "gpu_cache_usage" not in result.missing_signals


def test_RUN_003_malformed_metrics_raise_stable_contract_error() -> None:
    with pytest.raises(ValueError, match="invalid Prometheus metrics"):
        parse_vllm_metrics("not prometheus text")


@pytest.mark.asyncio
async def test_RUN_003_metrics_adapter_fetches_and_parses_public_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://llm.test/metrics")
        return httpx.Response(200, text="vllm:num_requests_running 3\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        snapshot = await VllmMetricsAdapter(
            metrics_url="http://llm.test/metrics", client=http
        ).collect()

    assert snapshot.values == {"requests_running": 3.0}
