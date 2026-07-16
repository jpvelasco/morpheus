from __future__ import annotations

import pytest
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
