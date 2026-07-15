from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from morpheus.adapters.fakes import FakeClock
from morpheus.core.telemetry import TelemetryEvent
from morpheus.telemetry.stream import observe_nonstream, observe_stream


async def chunks(values: list[bytes]) -> AsyncIterator[bytes]:
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_TEL_001_forwards_stream_bytes_unchanged_and_incrementally() -> None:
    values = [
        b'data: {"model":"served","choices":[{"delta":{"content":"secret"}}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":4,',
        b'"completion_tokens":2}}\n\ndata: [DONE]\n\n',
    ]
    clock = FakeClock(monotonic_value=10)
    event = TelemetryEvent.new(correlation_id="corr-1", model_requested="alias", started_at=10)
    observed = observe_stream(chunks(values), event=event, clock=clock)

    first = await anext(observed)
    assert first == values[0]
    clock.monotonic_value = 11
    remaining = [item async for item in observed]
    assert remaining == values[1:]
    assert event.first_byte_seconds == 0
    assert event.model_reported == "served"
    assert event.finish_reason == "stop"
    assert event.prompt_tokens == 4
    assert event.completion_tokens == 2


@pytest.mark.asyncio
async def test_TEL_003_event_serialization_never_contains_stream_content() -> None:
    canary = "private-prompt-response-canary"
    values = [
        (
            f'data: {{"choices":[{{"delta":{{"content":"{canary}"}},"finish_reason":null}}]}}\n\n'
        ).encode(),
        b"data: [DONE]\n\n",
    ]
    clock = FakeClock(monotonic_value=4)
    event = TelemetryEvent.new(correlation_id="corr-2", model_requested="alias", started_at=4)
    async for _ in observe_stream(chunks(values), event=event, clock=clock):
        pass
    assert canary not in json.dumps(event.as_record())
    assert set(event.as_record()) == {
        "correlation_id",
        "model_requested",
        "model_reported",
        "started_at",
        "first_byte_seconds",
        "completed_seconds",
        "prompt_tokens",
        "completion_tokens",
        "finish_reason",
        "outcome",
    }


@pytest.mark.asyncio
async def test_TEL_005_oversized_or_malformed_sse_frame_is_bounded() -> None:
    clock = FakeClock(monotonic_value=1)
    event = TelemetryEvent.new(correlation_id="corr-3", model_requested="alias", started_at=1)
    stream = observe_stream(chunks([b"data: " + b"x" * 70_000]), event=event, clock=clock)
    with pytest.raises(ValueError, match="frame exceeded"):
        async for _ in stream:
            pass
    assert event.outcome == "upstream_protocol_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [b"data: {\n\n", b"data: {}"],
)
async def test_TEL_005_rejects_malformed_or_incomplete_stream(value: bytes) -> None:
    clock = FakeClock(monotonic_value=1)
    event = TelemetryEvent.new(correlation_id="corr-stream", model_requested="alias", started_at=1)
    with pytest.raises(ValueError):
        async for _ in observe_stream(chunks([value]), event=event, clock=clock):
            pass
    assert event.outcome == "upstream_protocol_error"


async def failed_chunks() -> AsyncIterator[bytes]:
    if False:
        yield b""
    raise RuntimeError("client disconnected")


@pytest.mark.asyncio
async def test_TEL_005_marks_stream_cancellation() -> None:
    clock = FakeClock(monotonic_value=2)
    event = TelemetryEvent.new(correlation_id="corr-cancel", model_requested="alias", started_at=1)
    with pytest.raises(RuntimeError, match="disconnected"):
        async for _ in observe_stream(failed_chunks(), event=event, clock=clock):
            pass
    assert event.outcome == "canceled"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [b"{", b"[]", b"12345"])
async def test_TEL_005_nonstream_response_is_bounded_and_typed(value: bytes) -> None:
    clock = FakeClock(monotonic_value=2)
    event = TelemetryEvent.new(
        correlation_id=f"corr-{len(value)}", model_requested="alias", started_at=1
    )
    with pytest.raises(ValueError):
        await observe_nonstream(chunks([value]), event=event, clock=clock, max_bytes=4)
    assert event.outcome == "upstream_protocol_error"


@pytest.mark.asyncio
async def test_TEL_005_marks_nonstream_cancellation() -> None:
    clock = FakeClock(monotonic_value=2)
    event = TelemetryEvent.new(correlation_id="corr-failed", model_requested="alias", started_at=1)
    with pytest.raises(RuntimeError):
        await observe_nonstream(failed_chunks(), event=event, clock=clock, max_bytes=4)
    assert event.outcome == "canceled"


def test_TEL_002_rejects_empty_telemetry_identity() -> None:
    with pytest.raises(ValueError, match="identity"):
        TelemetryEvent.new(correlation_id="", model_requested="alias", started_at=1)
