from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from morpheus.adapters.inference.openai import OpenAIInferenceAdapter
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.api.app import SystemClock
from morpheus.api.body_limit import BodyLimitMiddleware
from morpheus.config import MorpheusSettings, load_settings
from morpheus.core.concurrency import ConcurrencyLimiter, FixedWindowRateLimiter
from morpheus.core.telemetry import TelemetryEvent
from morpheus.ports.protocols import Clock, InferencePort
from morpheus.telemetry.stream import observe_nonstream, observe_stream


class TelemetryStore(Protocol):
    async def initialize(self) -> None: ...

    async def record_telemetry(self, event: TelemetryEvent) -> None: ...


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _authorized(request: Request, settings: MorpheusSettings) -> bool:
    expected = settings.api_key.get_secret_value()
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return bool(expected) and hmac.compare_digest(supplied, expected)


def _parse_request(body: bytes) -> tuple[dict[str, Any], JSONResponse | None]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, _error(400, "invalid_json", "Request body must be valid JSON")
    if not isinstance(payload, dict):
        return {}, _error(422, "invalid_request", "Request body must be an object")
    if not isinstance(payload.get("model"), str) or not payload["model"]:
        return {}, _error(422, "invalid_model", "A non-empty model is required")
    if not isinstance(payload.get("messages"), list):
        return {}, _error(422, "invalid_messages", "Messages must be an array")
    return payload, None


def create_proxy_app(
    *,
    settings: MorpheusSettings,
    inference: InferencePort,
    store: TelemetryStore,
    clock: Clock,
) -> FastAPI:
    if not settings.enable_telemetry:
        raise ValueError("telemetry proxy requires enable_telemetry=true")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        del application
        await store.initialize()
        yield

    app = FastAPI(
        title="Morpheus Telemetry Proxy",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_request_bytes)
    request_limiter = ConcurrencyLimiter(settings.max_concurrent_requests)
    rate_limiter = FixedWindowRateLimiter(settings.max_requests_per_minute)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        client_key = request.client.host if request.client is not None else "local"
        if not await rate_limiter.allow(client_key):
            return _error(429, "request_rate_limited", "Request rate is temporarily limited")
        if not _authorized(request, settings):
            return _error(401, "authentication_required", "Authentication is required")
        content_type = request.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type != "application/json":
            return _error(415, "unsupported_content_type", "Content-Type must be application/json")
        if request.headers.get("Content-Length"):
            try:
                declared_size = int(request.headers["Content-Length"])
            except ValueError:
                return _error(400, "invalid_content_length", "Content-Length is invalid")
            if declared_size < 0:
                return _error(400, "invalid_content_length", "Content-Length is invalid")
            if declared_size > settings.max_request_bytes:
                return _error(413, "request_too_large", "Request body exceeds the configured limit")
        body = await request.body()
        if len(body) > settings.max_request_bytes:
            return _error(413, "request_too_large", "Request body exceeds the configured limit")
        payload, validation_error = _parse_request(body)
        if validation_error is not None:
            return validation_error

        if not await request_limiter.try_acquire():
            return _error(
                429, "request_capacity_exhausted", "Request capacity is temporarily exhausted"
            )
        release_slot = True

        try:
            event = TelemetryEvent.new(
                correlation_id=secrets.token_hex(16),
                model_requested=payload["model"],
                started_at=clock.monotonic(),
            )
            upstream = inference.forward_chat(body)
            if payload.get("stream") is True:

                async def streamed() -> Any:
                    try:
                        async for chunk in observe_stream(upstream, event=event, clock=clock):
                            yield chunk
                    finally:
                        await store.record_telemetry(event)
                        await request_limiter.release()

                release_slot = False
                return StreamingResponse(
                    streamed(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

            try:
                response_body = await observe_nonstream(
                    upstream,
                    event=event,
                    clock=clock,
                    max_bytes=16 * 1024 * 1024,
                )
            except ValueError:
                return _error(
                    502, "upstream_contract_error", "Upstream returned an incompatible response"
                )
            finally:
                await store.record_telemetry(event)
            return Response(content=response_body, media_type="application/json")
        finally:
            if release_slot:
                await request_limiter.release()

    return app


def run() -> None:
    settings = load_settings()
    clock = SystemClock()
    store = SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
    inference = OpenAIInferenceAdapter(
        base_url=settings.llm_base_url,
        clock=clock,
        timeout_seconds=settings.request_timeout_seconds,
        api_key=settings.upstream_api_key.get_secret_value(),
    )
    app = create_proxy_app(settings=settings, inference=inference, store=store, clock=clock)
    uvicorn.run(app, host=settings.bind_address, port=7410, access_log=False)
