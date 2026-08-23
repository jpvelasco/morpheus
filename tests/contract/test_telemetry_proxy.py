from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.config import MorpheusSettings
from morpheus.core.concurrency import ConcurrencyLimiter
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ServedModel
from morpheus.core.telemetry import TelemetryEvent
from morpheus.ports.protocols import InferencePort
from morpheus.telemetry.app import _finalize_stream, create_proxy_app

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"TEL-001", "TEL-002", "TEL-004", "TEL-005", "REL-002"})
pytestmark = pytest.mark.contract


@dataclass
class MemoryTelemetryStore:
    events: list[TelemetryEvent] = field(default_factory=list)
    initialized: bool = False
    prune_before: list[str] = field(default_factory=list)

    async def initialize(self) -> None:
        self.initialized = True

    async def record_telemetry(self, event: TelemetryEvent) -> None:
        self.events.append(event)

    async def prune_telemetry(self, *, before: str) -> int:
        self.prune_before.append(before)
        return 0


def proxy(
    chunks: list[bytes],
    *,
    inference_override: InferencePort | None = None,
    **settings_overrides: object,
) -> tuple[TestClient, MemoryTelemetryStore]:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    inference = FakeInference(
        health_result=Evidence(
            state=HealthState.READY,
            reason_code="ready",
            summary="ready",
            observed_at=now,
            duration=now - now,
            source="fixture",
            expires_at=now,
        ),
        model_results=(ServedModel(root=None, aliases=("alias",)),),
        chunks=chunks,
    )
    store = MemoryTelemetryStore()
    app = create_proxy_app(
        settings=MorpheusSettings(api_key="proxy-key", enable_telemetry=True, **settings_overrides),
        inference=inference_override or inference,
        store=store,
        clock=FakeClock(now=now, monotonic_value=2),
    )
    return TestClient(app), store


@dataclass
class FailingInference(FakeInference):
    error: BaseException | None = None

    def forward_chat(self, body: bytes) -> AsyncIterator[bytes]:
        del body

        async def failed() -> AsyncIterator[bytes]:
            if self.error is not None:
                raise self.error
            if False:
                yield b""

        return failed()


def failing_inference(error: BaseException | None) -> FailingInference:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    return FailingInference(
        health_result=Evidence(
            state=HealthState.READY,
            reason_code="ready",
            summary="ready",
            observed_at=now,
            duration=now - now,
            source="fixture",
            expires_at=now,
        ),
        model_results=(ServedModel(root=None, aliases=("alias",)),),
        error=error,
    )


def test_TEL_001_streaming_proxy_preserves_sse_bytes() -> None:
    chunks = [
        b'data: {"model":"served","choices":[{"delta":{"content":"hello"}}]}\n\n',
        (
            b'data: {"choices":[{"finish_reason":"stop"}],'
            b'"usage":{"prompt_tokens":2,"completion_tokens":1}}\n\n'
        ),
        b"data: [DONE]\n\n",
    ]
    client, store = proxy(chunks)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "alias", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert response.content == b"".join(chunks)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert store.events[0].prompt_tokens == 2
    assert store.events[0].completion_tokens == 1


def test_TEL_001_nonstreaming_proxy_preserves_json_contract() -> None:
    canary = "private-response-canary"
    payload = {
        "model": "served",
        "choices": [{"message": {"role": "assistant", "content": canary}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }
    client, store = proxy([json.dumps(payload).encode()])
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "alias", "messages": [{"role": "user", "content": "private-prompt"}]},
    )
    assert response.json() == payload
    assert canary not in json.dumps(store.events[0].as_record())
    assert store.events[0].finish_reason == "stop"


@pytest.mark.parametrize("stream", [False, True])
def test_TEL_005_proxy_normalizes_upstream_http_errors_before_response_start(
    stream: bool,
) -> None:
    request = httpx.Request("POST", "http://upstream.test/v1/chat/completions")
    error = httpx.HTTPStatusError(
        "upstream unavailable",
        request=request,
        response=httpx.Response(503, request=request),
    )
    client, store = proxy([], inference_override=failing_inference(error))

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "alias", "messages": [], "stream": stream},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_http_error"
    assert store.events[0].outcome == "upstream_http_error"


@pytest.mark.parametrize("stream", [False, True])
def test_TEL_005_proxy_normalizes_upstream_timeouts_before_response_start(stream: bool) -> None:
    request = httpx.Request("POST", "http://upstream.test/v1/chat/completions")
    client, store = proxy(
        [],
        inference_override=failing_inference(httpx.ReadTimeout("timed out", request=request)),
    )

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "alias", "messages": [], "stream": stream},
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert store.events[0].outcome == "upstream_timeout"


def test_TEL_005_proxy_rejects_an_empty_upstream_stream_before_response_start() -> None:
    client, store = proxy([], inference_override=failing_inference(None))

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key"},
        json={"model": "alias", "messages": [], "stream": True},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_contract_error"
    assert store.events[0].outcome == "upstream_protocol_error"


def test_TEL_002_proxy_initializes_persistence_before_serving() -> None:
    client, store = proxy([])

    with client:
        assert store.initialized is True


def test_TEL_002_proxy_enforces_retention_at_startup_and_after_recording() -> None:
    payload = {
        "model": "served",
        "choices": [{"finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    client, store = proxy([json.dumps(payload).encode()], telemetry_retention_days=30)

    with client:
        assert store.prune_before == ["2026-06-15T00:00:00+00:00"]
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer proxy-key"},
            json={"model": "alias", "messages": []},
        )

    assert response.status_code == 200
    assert store.prune_before == [
        "2026-06-15T00:00:00+00:00",
        "2026-06-15T00:00:00+00:00",
    ]


@pytest.mark.asyncio
async def test_TEL_005_stream_cleanup_survives_an_active_disconnect_cancellation() -> None:
    clock = FakeClock(now=datetime(2026, 7, 15, tzinfo=UTC), monotonic_value=2)
    settings = MorpheusSettings(api_key="proxy-key", enable_telemetry=True)
    store = MemoryTelemetryStore()
    limiter = ConcurrencyLimiter(1)
    event = TelemetryEvent.new(correlation_id="cancel", model_requested="alias", started_at=1)
    event.complete(2, outcome="canceled")
    assert await limiter.try_acquire() is True

    with anyio.CancelScope() as scope:
        scope.cancel()
        await _finalize_stream(
            store=store,
            event=event,
            settings=settings,
            clock=clock,
            request_limiter=limiter,
        )

    assert store.events == [event]
    assert await limiter.try_acquire() is True


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({}, {"model": "alias", "messages": []}, 401),
        ({"Authorization": "Bearer proxy-key"}, {"messages": []}, 422),
        ({"Authorization": "Bearer proxy-key"}, {"model": "alias", "messages": "bad"}, 422),
    ],
)
def test_TEL_004_proxy_enforces_authentication_and_schema(
    headers: dict[str, str], body: dict[str, object], status: int
) -> None:
    client, _ = proxy([])
    response = client.post("/v1/chat/completions", headers=headers, json=body)
    assert response.status_code == status


def test_SEC_003_proxy_rejects_oversized_body_before_upstream() -> None:
    client, store = proxy([])
    body = b"{" + b'"padding":"' + b"x" * 2_100_000 + b'"}'
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer proxy-key", "Content-Type": "application/json"},
        content=body,
    )
    assert response.status_code == 413
    assert store.events == []


def test_SEC_003_proxy_rejects_invalid_declared_body_length() -> None:
    client, store = proxy([])
    response = client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer proxy-key",
            "Content-Type": "application/json",
            "Content-Length": "-1",
        },
        content=b"{}",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_content_length"
    assert store.events == []


def test_SEC_003_proxy_rate_limits_before_upstream() -> None:
    client, store = proxy(
        [
            json.dumps(
                {
                    "choices": [{"finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            ).encode()
        ],
        max_requests_per_minute=1,
    )
    headers = {"Authorization": "Bearer proxy-key"}
    payload = {"model": "alias", "messages": []}

    assert client.post("/v1/chat/completions", headers=headers, json=payload).status_code == 200
    limited = client.post("/v1/chat/completions", headers=headers, json=payload)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "request_rate_limited"
    assert len(store.events) == 1
