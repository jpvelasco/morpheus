from __future__ import annotations

import httpx
import pytest

from morpheus.ops.live_readonly import (
    LiveReadOnlyConfig,
    LiveReadOnlyGuardTransport,
    LiveValidationError,
    run_live_readonly_probe,
)


def live_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "MORPHEUS_LIVE_TESTS": "1",
        "MORPHEUS_LIVE_MUTATION": "0",
        "MORPHEUS_LIVE_COMPLETIONS": "0",
        "MORPHEUS_LIVE_ALLOWED_HOSTS": "llm.test",
        "MORPHEUS_LIVE_VLLM_URL": "http://llm.test:8000/v1",
        "MORPHEUS_LIVE_VLLM_METRICS_URL": "http://llm.test:8000/metrics",
        "MORPHEUS_LIVE_TIMEOUT_SECONDS": "4",
    }
    environment.update(overrides)
    return environment


def test_LIVE_001_requires_explicit_read_only_opt_in_and_targets() -> None:
    for override in (
        {"MORPHEUS_LIVE_TESTS": "0"},
        {"MORPHEUS_LIVE_MUTATION": "1"},
        {"MORPHEUS_LIVE_COMPLETIONS": "1"},
        {"MORPHEUS_LIVE_VLLM_URL": ""},
        {"MORPHEUS_LIVE_VLLM_METRICS_URL": ""},
        {"MORPHEUS_LIVE_ALLOWED_HOSTS": ""},
    ):
        with pytest.raises(LiveValidationError):
            LiveReadOnlyConfig.from_environment(live_environment(**override))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MORPHEUS_LIVE_VLLM_URL", "http://other.test:8000/v1"),
        ("MORPHEUS_LIVE_VLLM_URL", "http://user:secret@llm.test:8000/v1"),
        ("MORPHEUS_LIVE_VLLM_URL", "http://llm.test:8000/v1/models"),
        ("MORPHEUS_LIVE_VLLM_URL", "file:///v1"),
        ("MORPHEUS_LIVE_VLLM_METRICS_URL", "http://llm.test:8000/admin/metrics"),
        ("MORPHEUS_LIVE_VLLM_METRICS_URL", "http://llm.test:8000/metrics?all=1"),
        ("MORPHEUS_LIVE_TIMEOUT_SECONDS", "0"),
        ("MORPHEUS_LIVE_TIMEOUT_SECONDS", "11"),
    ],
)
def test_LIVE_001_rejects_unallowlisted_or_unsafe_targets(name: str, value: str) -> None:
    with pytest.raises(LiveValidationError):
        LiveReadOnlyConfig.from_environment(live_environment(**{name: value}))


def test_LIVE_001_normalizes_only_declared_read_routes() -> None:
    config = LiveReadOnlyConfig.from_environment(
        live_environment(MORPHEUS_LIVE_ALLOWED_HOSTS="LLM.TEST, metrics.test")
    )

    assert config.inference_base_url == "http://llm.test:8000/v1"
    assert config.models_url == "http://llm.test:8000/v1/models"
    assert config.metrics_url == "http://llm.test:8000/metrics"
    assert config.timeout_seconds == 4
    assert config.allowed_requests == frozenset(
        {
            ("GET", "http://llm.test:8000/v1/models"),
            ("GET", "http://llm.test:8000/metrics"),
        }
    )


@pytest.mark.asyncio
async def test_LIVE_001_transport_blocks_every_undeclared_request_before_network() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json={"data": []})

    config = LiveReadOnlyConfig.from_environment(live_environment())
    transport = LiveReadOnlyGuardTransport(
        allowed_requests=config.allowed_requests,
        inner=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(config.models_url)
        assert response.status_code == 200
        with pytest.raises(LiveValidationError):
            await client.post(config.models_url)
        with pytest.raises(LiveValidationError):
            await client.get("http://llm.test:8000/v1/models?unexpected=1")
        with pytest.raises(LiveValidationError):
            await client.get("http://llm.test:8000/health")

    assert seen == [("GET", config.models_url)]


@pytest.mark.asyncio
async def test_LIVE_003_LIVE_004_probe_reports_models_health_and_metric_compatibility() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/v1/models":
            assert request.headers["Authorization"] == "Bearer private-live-key"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "served-alias",
                            "root": "upstream/model",
                            "max_model_len": 131072,
                        }
                    ]
                },
            )
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            text=(
                "vllm:num_requests_running 1\n"
                "vllm:generation_tokens_total 42\n"
                "vllm:future_signal 7\n"
            ),
        )

    config = LiveReadOnlyConfig.from_environment(
        live_environment(MORPHEUS_LIVE_VLLM_API_KEY="private-live-key")
    )
    report = await run_live_readonly_probe(config, transport=httpx.MockTransport(handler))

    assert requests == [("GET", "/v1/models"), ("GET", "/metrics")]
    assert report.to_dict() == {
        "status": "pass",
        "health": "ready",
        "models": [
            {
                "root": "upstream/model",
                "aliases": ["served-alias"],
                "context_window": 131072,
            }
        ],
        "metrics": {
            "available_signals": ["generation_tokens_total", "requests_running"],
            "missing_signals": [
                "gpu_cache_usage",
                "prompt_tokens_total",
                "request_success_total",
                "requests_waiting",
            ],
        },
        "request_count": 2,
    }
    rendered = report.to_json()
    assert "private-live-key" not in rendered
    assert "llm.test" not in rendered
