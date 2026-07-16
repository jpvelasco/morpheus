from __future__ import annotations

import hmac
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from morpheus.adapters.inference.openai import OpenAIInferenceAdapter
from morpheus.adapters.runtime.agent import RuntimeAgentClient
from morpheus.api.body_limit import BodyLimitMiddleware
from morpheus.api.runtime import runtime_snapshot
from morpheus.api.session import BrowserSession, SessionCodec, SessionValidationError
from morpheus.config import MorpheusSettings, load_settings
from morpheus.core.capabilities import Capability, evaluate_capabilities
from morpheus.core.concurrency import ConcurrencyLimiter, FixedWindowRateLimiter
from morpheus.core.health import Evidence, HealthState
from morpheus.ports.protocols import Clock, InferencePort, RuntimeAgentPort


class AuthenticationRequired(Exception):
    pass


class CsrfValidationError(Exception):
    pass


class SessionUnavailable(Exception):
    pass


class SessionLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, max_length=512)


_SESSION_COOKIE = "morpheus_session"
_CSRF_COOKIE = "morpheus_csrf"


def _evidence_json(evidence: Evidence) -> dict[str, Any]:
    value = asdict(evidence)
    value["state"] = evidence.state.value
    value["observed_at"] = evidence.observed_at.isoformat()
    value["expires_at"] = evidence.expires_at.isoformat()
    value["duration_ms"] = evidence.duration.total_seconds() * 1000
    value.pop("duration")
    return value


def create_app(
    *,
    settings: MorpheusSettings,
    inference: InferencePort,
    clock: Clock,
    runtime_agent: RuntimeAgentPort | None = None,
) -> FastAPI:
    app = FastAPI(title="Morpheus Control API", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.inference = inference
    app.state.clock = clock
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_request_bytes)
    session_secret = settings.session_secret.get_secret_value().encode()
    session_codec = (
        SessionCodec(secret=session_secret, ttl_seconds=settings.session_ttl_seconds)
        if session_secret
        else None
    )
    request_limiter = ConcurrencyLimiter(settings.max_concurrent_requests)
    rate_limiter = FixedWindowRateLimiter(settings.max_requests_per_minute)
    allowed_origins = [
        f"http://127.0.0.1:{settings.dashboard_port}",
        f"http://localhost:{settings.dashboard_port}",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )

    @app.middleware("http")
    async def secure_responses(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(16)

        def secured(response: Response) -> Response:
            response.headers["X-Request-ID"] = request_id[:128]
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; frame-ancestors 'none'"
            )
            return response

        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return secured(
                    JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "invalid_content_length",
                                "message": "Content-Length must be a non-negative integer",
                            }
                        },
                    )
                )
            if declared_size < 0:
                return secured(
                    JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "invalid_content_length",
                                "message": "Content-Length must be a non-negative integer",
                            }
                        },
                    )
                )
            if declared_size > settings.max_request_bytes:
                return secured(
                    JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "request_too_large",
                                "message": "Request body is too large",
                            }
                        },
                    )
                )
        limited = request.url.path.startswith("/api/") and request.method != "OPTIONS"
        client_key = request.client.host if request.client is not None else "local"
        if limited and not await rate_limiter.allow(client_key):
            return secured(
                JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                    content={
                        "error": {
                            "code": "request_rate_limited",
                            "message": "Request rate is temporarily limited",
                        }
                    },
                )
            )
        if limited and not await request_limiter.try_acquire():
            return secured(
                JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "1"},
                    content={
                        "error": {
                            "code": "request_capacity_exhausted",
                            "message": "Request capacity is temporarily exhausted",
                        }
                    },
                )
            )
        try:
            return secured(await call_next(request))
        finally:
            if limited:
                await request_limiter.release()

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

    @app.exception_handler(CsrfValidationError)
    async def csrf_error(request: Request, error: CsrfValidationError) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=403,
            content={
                "error": {"code": "csrf_validation_failed", "message": "CSRF validation failed"}
            },
        )

    @app.exception_handler(SessionUnavailable)
    async def session_unavailable(request: Request, error: SessionUnavailable) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "session_unavailable",
                    "message": "Browser sessions are unavailable",
                }
            },
        )

    def browser_session(request: Request) -> BrowserSession:
        if session_codec is None:
            raise AuthenticationRequired
        token = request.cookies.get(_SESSION_COOKIE, "")
        try:
            return session_codec.verify(token, now=clock.utc_now())
        except SessionValidationError:
            raise AuthenticationRequired from None

    def require_api_key(request: Request) -> None:
        expected = settings.api_key.get_secret_value()
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if expected and hmac.compare_digest(supplied, expected):
            return
        browser_session(request)

    def set_session_cookies(response: Response, *, token: str, session: BrowserSession) -> None:
        response.set_cookie(
            _SESSION_COOKIE,
            token,
            max_age=settings.session_ttl_seconds,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            _CSRF_COOKIE,
            session.csrf_token,
            max_age=settings.session_ttl_seconds,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=False,
            samesite="strict",
        )

    def clear_session_cookies(response: Response) -> None:
        response.delete_cookie(
            _SESSION_COOKIE,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.delete_cookie(
            _CSRF_COOKIE,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=False,
            samesite="strict",
        )

    def capability_payload(evidence: Evidence) -> dict[str, Any]:
        configured: dict[Capability, bool] = {
            Capability.CORE: True,
            **{Capability(name): enabled for name, enabled in settings.features().items()},
        }
        dependency_health = {Capability.CORE: evidence.state is HealthState.READY}
        blockers: dict[Capability, tuple[str, ...]] = {
            capability: (f"{capability.value}_dependency_health_not_integrated",)
            for capability, enabled in configured.items()
            if capability is not Capability.CORE and enabled
        }
        if evidence.state is not HealthState.READY:
            blockers[Capability.CORE] = (evidence.reason_code,)
        report = evaluate_capabilities(
            configured=configured,
            dependency_health=dependency_health,
            blockers=blockers,
        )
        return {
            capability.value: {
                "state": status.state.value,
                "blockers": list(status.blockers),
            }
            for capability, status in report.items()
        }

    @app.get("/healthz")
    async def public_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/session")
    async def login(credentials: SessionLogin, response: Response) -> dict[str, str]:
        expected = settings.api_key.get_secret_value()
        if not expected or not hmac.compare_digest(credentials.api_key, expected):
            raise AuthenticationRequired
        if session_codec is None:
            raise SessionUnavailable
        token, session = session_codec.issue(now=clock.utc_now())
        set_session_cookies(response, token=token, session=session)
        return {"status": "authenticated"}

    @app.delete("/api/v1/session")
    async def logout(
        request: Request,
        response: Response,
        x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, str]:
        session = browser_session(request)
        if not x_csrf_token or not hmac.compare_digest(x_csrf_token, session.csrf_token):
            raise CsrfValidationError
        clear_session_cookies(response)
        return {"status": "signed_out"}

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
        evidence = await inference.health()
        return {"capabilities": capability_payload(evidence)}

    @app.get("/api/v1/overview", dependencies=[Depends(require_api_key)])
    async def overview() -> dict[str, Any]:
        evidence = await inference.health()
        discovered = await inference.models()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        observed_at = clock.utc_now().isoformat()
        return {
            "observed_at": observed_at,
            "inference": _evidence_json(evidence),
            "models": [asdict(model) for model in discovered],
            "capabilities": capability_payload(evidence),
            "host": host,
            "diagnostics": _diagnostics_payload(
                settings=settings,
                evidence=evidence,
                model_contract_ready=bool(discovered),
                host=host,
                observed_at=observed_at,
            ),
            "external_controls": [],
        }

    @app.get("/api/v1/diagnostics", dependencies=[Depends(require_api_key)])
    async def diagnostics() -> dict[str, Any]:
        evidence = await inference.health()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        try:
            discovered = await inference.models()
            model_contract_ready = bool(discovered)
        except (httpx.HTTPError, OSError, ValueError):
            model_contract_ready = False
        observed_at = clock.utc_now().isoformat()
        payload = _diagnostics_payload(
            settings=settings,
            evidence=evidence,
            model_contract_ready=model_contract_ready,
            host=host,
            observed_at=observed_at,
        )
        return {
            **payload,
            "inference": _evidence_json(evidence),
            "host": host,
            "configuration": settings.public_dict(),
        }

    return app


def _diagnostic_check(
    code: str,
    status: str,
    reason_code: str,
    summary: str,
    observed_at: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "reason_code": reason_code,
        "summary": summary,
        "observed_at": observed_at,
        "freshness": "current",
        "next_action": next_action,
    }


def _diagnostics_payload(
    *,
    settings: MorpheusSettings,
    evidence: Evidence,
    model_contract_ready: bool,
    host: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    candidate_identified = bool(settings.release_version and settings.source_commit)
    host_ready = host["status"] in {"available", "degraded"}
    services = host.get("services")
    service_items: list[Any] = services if isinstance(services, list) else []
    services_inspected = bool(service_items)
    image_pinned = bool(
        candidate_identified
        and services_inspected
        and all(
            isinstance(service, dict)
            and service.get("source_commit") == settings.source_commit
            and service.get("release_version") == settings.release_version
            and isinstance(service.get("image_id"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", service["image_id"])
            for service in service_items
        )
    )
    image_pin_status = (
        "pass"
        if image_pinned
        else "fail"
        if candidate_identified and services_inspected
        else "unavailable"
    )
    checks = [
        _diagnostic_check(
            "configuration",
            "pass",
            "configuration_valid",
            "Configuration passed schema and network-posture validation",
            observed_at,
        ),
        _diagnostic_check(
            "network_endpoint",
            "pass" if evidence.state is HealthState.READY else "fail",
            evidence.reason_code,
            evidence.summary,
            evidence.observed_at.isoformat(),
            evidence.next_action,
        ),
        _diagnostic_check(
            "service_contract",
            "pass" if model_contract_ready else "fail",
            "model_contract_ready" if model_contract_ready else "model_contract_unavailable",
            "Inference model discovery returned a compatible contract"
            if model_contract_ready
            else "Inference model discovery did not return a compatible contract",
            observed_at,
            None
            if model_contract_ready
            else "Verify the configured /v1/models endpoint and model response schema",
        ),
        _diagnostic_check(
            "storage",
            "pass" if host_ready and "disk" in host else "unavailable",
            "storage_evidence_ready"
            if host_ready and "disk" in host
            else "storage_evidence_unavailable",
            "Runtime-agent storage evidence is available"
            if host_ready and "disk" in host
            else "Runtime-agent storage evidence is unavailable",
            str(host.get("observed_at", observed_at)),
            None
            if host_ready and "disk" in host
            else "Configure and start the signed runtime agent",
        ),
        _diagnostic_check(
            "clock",
            "pass" if host_ready and "clock" in host else "unavailable",
            "clock_evidence_ready"
            if host_ready and "clock" in host
            else "clock_evidence_unavailable",
            "Runtime-agent clock evidence is available"
            if host_ready and "clock" in host
            else "Runtime-agent clock evidence is unavailable",
            str(host.get("observed_at", observed_at)),
            None
            if host_ready and "clock" in host
            else "Configure and start the signed runtime agent",
        ),
        _diagnostic_check(
            "image_pin",
            image_pin_status,
            "candidate_identity_ready" if image_pinned else "candidate_identity_unavailable",
            "Every running Morpheus service matches the immutable candidate identity"
            if image_pinned
            else "Running service image identity could not be verified against the candidate",
            observed_at,
            None
            if image_pinned
            else "Run the immutable candidate images and verify the signed runtime agent",
        ),
        _diagnostic_check(
            "runtime_agent",
            "pass" if host["status"] == "available" else "unavailable",
            "runtime_agent_ready"
            if host["status"] == "available"
            else str(host.get("reason", "runtime_agent_partial_failure")),
            "All runtime-agent probes passed"
            if host["status"] == "available"
            else "One or more runtime-agent probes are unavailable",
            str(host.get("observed_at", observed_at)),
            None
            if host["status"] == "available"
            else "Verify the runtime agent service and its dedicated credential",
        ),
    ]
    failed = any(check["status"] == "fail" for check in checks)
    incomplete = any(check["status"] == "unavailable" for check in checks)
    return {
        "status": "unhealthy" if failed else "degraded" if incomplete else "ready",
        "observed_at": observed_at,
        "checks": checks,
    }


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
    agent_key = settings.agent_key.get_secret_value().encode()
    runtime_endpoint_configured = bool(settings.runtime_agent_url or settings.runtime_agent_socket)
    runtime_agent = (
        RuntimeAgentClient(
            base_url=settings.runtime_agent_url or "http://runtime-agent",
            key=agent_key,
            timeout_seconds=min(settings.request_timeout_seconds, 5),
            uds=settings.runtime_agent_socket,
        )
        if runtime_endpoint_configured and agent_key
        else None
    )
    app = create_app(
        settings=settings,
        inference=inference,
        clock=clock,
        runtime_agent=runtime_agent,
    )
    uvicorn.run(app, host=settings.bind_address, port=settings.api_port, access_log=False)
