from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

from morpheus.api.body_limit import BodyLimitMiddleware


async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
    del scope
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def invoke(
    middleware: BodyLimitMiddleware, *, body: bytes, headers: list[tuple[bytes, bytes]]
) -> list[Message]:
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    await middleware(
        {"type": "http", "method": "POST", "path": "/", "headers": headers}, receive, send
    )
    return sent


@pytest.mark.asyncio
async def test_SEC_003_body_limit_rejects_oversized_unchunked_body() -> None:
    sent = await invoke(
        BodyLimitMiddleware(downstream, max_body_bytes=4), body=b"12345", headers=[]
    )

    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_SEC_003_body_limit_rejects_invalid_declared_size() -> None:
    sent = await invoke(
        BodyLimitMiddleware(downstream, max_body_bytes=4),
        body=b"",
        headers=[(b"content-length", b"not-a-number")],
    )

    assert sent[0]["status"] == 400


@pytest.mark.asyncio
async def test_TEL_001_body_replay_does_not_synthesize_a_stream_disconnect() -> None:
    request_messages: list[Message] = [
        {"type": "http.request", "body": b"request", "more_body": False}
    ]
    disconnected = asyncio.Event()
    sent: list[Message] = []

    async def receive() -> Message:
        if request_messages:
            return request_messages.pop(0)
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def stream() -> AsyncIterator[bytes]:
        await asyncio.sleep(0)
        yield b"data: first\n\n"
        yield b"data: [DONE]\n\n"

    async def streaming_downstream(scope: Scope, receive: Receive, send: Send) -> None:
        assert (await receive())["body"] == b"request"
        response = StreamingResponse(stream(), media_type="text/event-stream")
        await response(scope, receive, send)

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = BodyLimitMiddleware(streaming_downstream, max_body_bytes=1024)
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-length", b"7")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 7410),
        "state": {},
    }

    await asyncio.wait_for(middleware(scope, receive, send), timeout=1)

    bodies = [message for message in sent if message["type"] == "http.response.body"]
    assert b"".join(message.get("body", b"") for message in bodies) == (
        b"data: first\n\ndata: [DONE]\n\n"
    )
    assert bodies[-1].get("more_body", False) is False
