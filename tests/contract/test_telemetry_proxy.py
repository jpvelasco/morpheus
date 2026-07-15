from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity
from morpheus.core.telemetry import TelemetryEvent
from morpheus.telemetry.app import create_proxy_app

pytestmark = pytest.mark.contract


@dataclass
class MemoryTelemetryStore:
    events: list[TelemetryEvent] = field(default_factory=list)
    initialized: bool = False

    async def initialize(self) -> None:
        self.initialized = True

    async def record_telemetry(self, event: TelemetryEvent) -> None:
        self.events.append(event)


def proxy(chunks: list[bytes]) -> tuple[TestClient, MemoryTelemetryStore]:
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
        model_results=(ModelIdentity(root=None, aliases=("alias",)),),
        chunks=chunks,
    )
    store = MemoryTelemetryStore()
    app = create_proxy_app(
        settings=MorpheusSettings(api_key="proxy-key", enable_telemetry=True),
        inference=inference,
        store=store,
        clock=FakeClock(now=now, monotonic_value=2),
    )
    return TestClient(app), store


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


def test_TEL_002_proxy_initializes_persistence_before_serving() -> None:
    client, store = proxy([])

    with client:
        assert store.initialized is True


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
