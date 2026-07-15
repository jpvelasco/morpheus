from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from morpheus.core.telemetry import TelemetryEvent
from morpheus.ports.protocols import Clock

MAX_FRAME_BYTES = 65_536


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def observe_payload(payload: dict[str, Any], event: TelemetryEvent) -> None:
    model = payload.get("model")
    if isinstance(model, str):
        event.model_reported = model
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str):
                event.finish_reason = finish_reason
    usage = payload.get("usage")
    if isinstance(usage, dict):
        event.prompt_tokens = _positive_int(usage.get("prompt_tokens"))
        event.completion_tokens = _positive_int(usage.get("completion_tokens"))


async def observe_stream(
    upstream: AsyncIterator[bytes], *, event: TelemetryEvent, clock: Clock
) -> AsyncIterator[bytes]:
    buffer = b""
    try:
        async for chunk in upstream:
            event.observe_first_byte(clock.monotonic())
            buffer += chunk
            if len(buffer) > MAX_FRAME_BYTES and b"\n" not in buffer:
                raise ValueError("stream frame exceeded the configured size limit")
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if len(line) > MAX_FRAME_BYTES:
                    raise ValueError("stream frame exceeded the configured size limit")
                stripped = line.strip()
                if not stripped.startswith(b"data:"):
                    continue
                data = stripped.removeprefix(b"data:").strip()
                if not data or data == b"[DONE]":
                    continue
                try:
                    payload = json.loads(data)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError("upstream returned a malformed streaming frame") from error
                if isinstance(payload, dict):
                    observe_payload(payload, event)
            yield chunk
        if buffer.strip():
            raise ValueError("upstream ended with an incomplete streaming frame")
    except ValueError:
        event.complete(clock.monotonic(), outcome="upstream_protocol_error")
        raise
    except BaseException:
        event.complete(clock.monotonic(), outcome="canceled")
        raise
    else:
        event.complete(clock.monotonic())


async def observe_nonstream(
    upstream: AsyncIterator[bytes],
    *,
    event: TelemetryEvent,
    clock: Clock,
    max_bytes: int,
) -> bytes:
    body = bytearray()
    try:
        async for chunk in upstream:
            event.observe_first_byte(clock.monotonic())
            body.extend(chunk)
            if len(body) > max_bytes:
                raise ValueError("upstream response exceeded the configured size limit")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("upstream returned malformed JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("upstream returned an incompatible JSON response")
        observe_payload(payload, event)
    except ValueError:
        event.complete(clock.monotonic(), outcome="upstream_protocol_error")
        raise
    except BaseException:
        event.complete(clock.monotonic(), outcome="canceled")
        raise
    else:
        event.complete(clock.monotonic())
        return bytes(body)
