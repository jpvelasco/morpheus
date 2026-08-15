"""Bounded compatibility endpoint (GATE-001, GATE-003).

Exactly one authenticated endpoint for the selected managed runtime plus a
documented direct bypass; no provider routing, no inline secrets.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from morpheus.gateway.compat import (
    CompatForwarder,
    CompatRoute,
    CompatUpstreamError,
    authenticate,
    build_forward_url,
    resolve_model,
)

_FORWARD_HEADERS = ("authorization", "content-type", "accept", "x-request-id")


def _forward_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in _FORWARD_HEADERS:
        value = request.headers.get(name)
        if value is not None:
            headers[name] = value
    return headers


def _upstream_error(status_code: int) -> HTTPException:
    if status_code >= 500:
        return HTTPException(
            status_code=502,
            detail={"error": {"type": "upstream_error", "upstream_status": status_code}},
        )
    return HTTPException(
        status_code=400,
        detail={"error": {"type": "upstream_rejected", "upstream_status": status_code}},
    )


def compat_router(
    *,
    route: CompatRoute,
    secret: str,
    forwarder: CompatForwarder | None = None,
) -> APIRouter:
    """Build the bounded compatibility surface for one managed runtime."""

    forwarder = forwarder or CompatForwarder()
    router = APIRouter()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        token = None
        if authorization is not None and authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
        if not authenticate(token, secret):
            raise HTTPException(status_code=401, detail="authentication required")

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": route.mode,
            "schema_version": route.schema_version,
        }

    @router.get("/v1/models", dependencies=[Depends(require_auth)])
    async def models(request: Request) -> Response:
        url = build_forward_url(route.active_base_url, "/v1/models")
        try:
            response = await forwarder.forward_once(
                method="GET", url=url, headers=_forward_headers(request)
            )
        except CompatUpstreamError as error:
            raise _upstream_error(error.status_code) from error
        except (httpx.NetworkError, httpx.TimeoutException) as error:
            raise HTTPException(
                status_code=503, detail="upstream runtime is unavailable"
            ) from error
        return Response(
            content=response.content,
            media_type=response.headers.get("content-type", "application/json"),
        )

    @router.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
    async def chat(request: Request) -> Response:
        body = await request.body()
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise HTTPException(status_code=400, detail="request body must be JSON") from error
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be a JSON object")
        model = payload.get("model")
        if model is not None and not isinstance(model, str):
            raise HTTPException(status_code=400, detail="model must be a string when present")
        try:
            resolved = resolve_model(route, model)
        except KeyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if resolved != model:
            payload["model"] = resolved
            body = json.dumps(payload).encode()
        url = build_forward_url(route.active_base_url, "/v1/chat/completions")
        try:
            upstream = await forwarder.open_stream(
                method="POST", url=url, headers=_forward_headers(request), content=body
            )
        except CompatUpstreamError as error:
            raise _upstream_error(error.status_code) from error
        except (httpx.NetworkError, httpx.TimeoutException) as error:
            raise HTTPException(
                status_code=503, detail="upstream runtime is unavailable"
            ) from error

        async def source() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        media_type = upstream.headers.get("content-type", "text/event-stream")
        return StreamingResponse(source(), status_code=upstream.status_code, media_type=media_type)

    return router
