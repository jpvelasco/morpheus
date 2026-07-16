from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from morpheus.adapters.fakes import FakeClock
from morpheus.adapters.inference.openai import InferenceContractError, OpenAIInferenceAdapter
from morpheus.core.concurrency import RetryPolicy
from morpheus.core.health import HealthState

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def adapter_for(handler: httpx.MockTransport) -> OpenAIInferenceAdapter:
    return OpenAIInferenceAdapter(
        base_url="http://llm.test/v1",
        client=httpx.AsyncClient(transport=handler),
        clock=FakeClock(now=datetime(2026, 7, 15, tzinfo=UTC)),
        timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_RUN_001_groups_aliases_by_root_model() -> None:
    payload = json.loads((ROOT / "tests/fixtures/models-multiple.json").read_text(encoding="utf-8"))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with adapter_for(transport) as adapter:
        models = await adapter.models()

    assert len(models) == 1
    assert models[0].root == "nvidia/Qwen3.6-27B-NVFP4"
    assert models[0].aliases == ("qwen36-27b-nvfp4", "qwopus36-coder-q4km")
    assert models[0].context_window == 131072


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": [{}]}, {"data": [{"id": 4}]}])
async def test_RUN_001_rejects_malformed_model_contract(payload: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with adapter_for(transport) as adapter:
        with pytest.raises(InferenceContractError):
            await adapter.models()


@pytest.mark.asyncio
async def test_RUN_002_health_distinguishes_starting_and_unreachable() -> None:
    starting = httpx.MockTransport(lambda request: httpx.Response(503, json={"detail": "loading"}))
    async with adapter_for(starting) as adapter:
        assert (await adapter.health()).state is HealthState.STARTING

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("fixture timeout", request=request)

    async with adapter_for(httpx.MockTransport(timeout)) as adapter:
        assert (await adapter.health()).state is HealthState.UNREACHABLE


@pytest.mark.asyncio
async def test_REL_002_retries_only_transient_model_discovery_failures() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(503, json={"detail": "loading"})
            if calls == 1
            else httpx.Response(200, json={"data": [{"id": "model"}]})
        )

    adapter = OpenAIInferenceAdapter(
        base_url="http://llm.test/v1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=FakeClock(now=datetime(2026, 7, 15, tzinfo=UTC)),
        timeout_seconds=1,
        retry_policy=RetryPolicy(initial_delay_seconds=0.001, deadline_seconds=1, jitter_ratio=0),
    )
    async with adapter:
        assert (await adapter.models())[0].aliases == ("model",)
    assert calls == 2


@pytest.mark.asyncio
async def test_RUN_002_health_marks_schema_drift_incompatible() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": []}))
    async with adapter_for(transport) as adapter:
        evidence = await adapter.health()
    assert evidence.state is HealthState.INCOMPATIBLE
    assert evidence.reason_code == "inference_contract_incompatible"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"{"),
        httpx.Response(200, json={"data": [{"id": "alias", "root": 4}]}),
        httpx.Response(200, json={"data": [{"id": "alias", "max_model_len": True}]}),
        httpx.Response(200, json={"data": [{"id": "alias", "context_length": 0}]}),
    ],
)
async def test_RUN_001_rejects_model_field_schema_drift(response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    async with adapter_for(transport) as adapter:
        with pytest.raises(InferenceContractError):
            await adapter.models()


@pytest.mark.asyncio
async def test_RUN_002_health_distinguishes_ready_empty_and_failed_models() -> None:
    ready = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "model"}]})
    )
    empty = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    failed = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "failed"}))

    async with adapter_for(ready) as adapter:
        assert (await adapter.health()).state is HealthState.READY
    async with adapter_for(empty) as adapter:
        assert (await adapter.health()).state is HealthState.STARTING
    async with adapter_for(failed) as adapter:
        assert (await adapter.health()).state is HealthState.DEGRADED


@pytest.mark.asyncio
async def test_RUN_001_chat_forwarder_preserves_request_and_response_bytes() -> None:
    body = b'{"model":"alias","messages":[]}'

    class ResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"response-"
            yield b"bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer upstream-key"
        assert request.content == body
        return httpx.Response(200, stream=ResponseStream())

    adapter = OpenAIInferenceAdapter(
        base_url="http://llm.test/v1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=FakeClock(now=datetime(2026, 7, 15, tzinfo=UTC)),
        timeout_seconds=1,
        api_key="upstream-key",
    )
    async with adapter:
        response = b"".join([chunk async for chunk in adapter.forward_chat(body)])
    assert response == b"response-bytes"
