from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    """Bound a complete HTTP request body before FastAPI parses it."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared_size = _declared_size(scope)
        if declared_size is None:
            await _error(send, 400, "invalid_content_length", "Content-Length is invalid")
            return
        if declared_size > self.max_body_bytes:
            await _error(send, 413, "request_too_large", "Request body is too large")
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                await _error(send, 413, "request_too_large", "Request body is too large")
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)


def _declared_size(scope: Scope) -> int | None:
    headers = [value for name, value in scope["headers"] if name.lower() == b"content-length"]
    if not headers:
        return 0
    if len(headers) != 1:
        return None
    try:
        size = int(headers[0])
    except ValueError:
        return None
    return size if size >= 0 else None


async def _error(send: Send, status_code: int, code: str, message: str) -> None:
    response = JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )
    await response({"type": "http"}, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.disconnect"}
