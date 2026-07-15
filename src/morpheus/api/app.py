from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from morpheus.adapters.inference.openai import OpenAIInferenceAdapter
from morpheus.config import MorpheusSettings, load_settings
from morpheus.core.capabilities import Capability, CapabilityState
from morpheus.core.health import Evidence
from morpheus.ports.protocols import Clock, InferencePort


class AuthenticationRequired(Exception):
    pass


def _evidence_json(evidence: Evidence) -> dict[str, Any]:
    value = asdict(evidence)
    value["state"] = evidence.state.value
    value["observed_at"] = evidence.observed_at.isoformat()
    value["expires_at"] = evidence.expires_at.isoformat()
    value["duration_ms"] = evidence.duration.total_seconds() * 1000
    value.pop("duration")
    return value


def create_app(*, settings: MorpheusSettings, inference: InferencePort, clock: Clock) -> FastAPI:
    app = FastAPI(title="Morpheus Control API", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.inference = inference
    app.state.clock = clock
    allowed_origins = [
        f"http://127.0.0.1:{settings.dashboard_port}",
        f"http://localhost:{settings.dashboard_port}",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def secure_responses(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(16)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id[:128]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(AuthenticationRequired)
    async def authentication_error(request: Request, error: AuthenticationRequired) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={
                "error": {
                    "code": "authentication_required",
                    "message": "Authentication is required",
                }
            },
        )

    def require_api_key(request: Request) -> None:
        expected = settings.api_key.get_secret_value()
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not expected or not hmac.compare_digest(supplied, expected):
            raise AuthenticationRequired

    def capability_payload() -> dict[str, Any]:
        configured = {Capability.CORE.value: True, **settings.features()}
        result: dict[str, Any] = {}
        for name, enabled in configured.items():
            state = CapabilityState.AVAILABLE if enabled else CapabilityState.DISABLED
            result[name] = {"state": state.value, "blockers": []}
        return result

    @app.get("/healthz")
    async def public_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health", dependencies=[Depends(require_api_key)])
    async def health() -> dict[str, Any]:
        evidence = await inference.health()
        return {"health": _evidence_json(evidence)}

    @app.get("/api/v1/models", dependencies=[Depends(require_api_key)])
    async def models() -> dict[str, Any]:
        discovered = await inference.models()
        return {"models": [asdict(model) for model in discovered]}

    @app.get("/api/v1/capabilities", dependencies=[Depends(require_api_key)])
    async def capabilities() -> dict[str, Any]:
        return {"capabilities": capability_payload()}

    @app.get("/api/v1/overview", dependencies=[Depends(require_api_key)])
    async def overview() -> dict[str, Any]:
        evidence = await inference.health()
        discovered = await inference.models()
        return {
            "observed_at": clock.utc_now().isoformat(),
            "inference": _evidence_json(evidence),
            "models": [asdict(model) for model in discovered],
            "capabilities": capability_payload(),
            "host": {
                "status": "unavailable",
                "reason": "runtime_agent_not_configured",
            },
            "external_controls": [],
        }

    @app.get("/api/v1/diagnostics", dependencies=[Depends(require_api_key)])
    async def diagnostics() -> dict[str, Any]:
        evidence = await inference.health()
        return {
            "observed_at": clock.utc_now().isoformat(),
            "inference": _evidence_json(evidence),
            "configuration": settings.public_dict(),
        }

    return app


class SystemClock:
    def utc_now(self) -> Any:
        from datetime import UTC, datetime

        return datetime.now(UTC)

    def monotonic(self) -> float:
        import time

        return time.monotonic()


def run() -> None:
    settings = load_settings()
    clock = SystemClock()
    inference = OpenAIInferenceAdapter(
        base_url=settings.llm_base_url,
        clock=clock,
        timeout_seconds=settings.request_timeout_seconds,
        api_key=settings.upstream_api_key.get_secret_value(),
    )
    app = create_app(settings=settings, inference=inference, clock=clock)
    uvicorn.run(app, host=settings.bind_address, port=settings.api_port, access_log=False)
