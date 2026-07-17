from __future__ import annotations

import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from morpheus.agent.auth import AgentAuthenticationError, AgentAuthenticator
from morpheus.agent.host import SystemHostInspector
from morpheus.agent.protocol import (
    AgentLifecycleRequest,
    AgentLifecycleResponse,
    AgentRequest,
    AgentResponse,
)
from morpheus.api.body_limit import BodyLimitMiddleware
from morpheus.config import MorpheusSettings, load_settings
from morpheus.core.concurrency import ConcurrencyLimiter, FixedWindowRateLimiter
from morpheus.core.lifecycle import LifecycleRequest


class LifecycleExecutor(Protocol):
    def execute(self, request: LifecycleRequest) -> Any: ...


def create_agent_app(
    *,
    settings: MorpheusSettings,
    inspector: SystemHostInspector,
    lifecycle: LifecycleExecutor | None = None,
) -> FastAPI:
    key = settings.agent_key.get_secret_value().encode()
    authenticator = AgentAuthenticator(key)
    app = FastAPI(title="Morpheus Runtime Agent", docs_url=None, redoc_url=None)
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=4096)
    request_limiter = ConcurrencyLimiter(settings.max_concurrent_requests)
    rate_limiter = FixedWindowRateLimiter(settings.max_requests_per_minute)

    async def authenticated_body(
        request: Request,
        *,
        timestamp: str,
        nonce: str,
        signature: str,
    ) -> bytes | JSONResponse:
        client_key = request.client.host if request.client is not None else "local"
        if not await rate_limiter.allow(client_key):
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={"error": {"code": "request_rate_limited"}},
            )
        content_type = request.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type != "application/json":
            return JSONResponse(
                status_code=415, content={"error": {"code": "unsupported_content_type"}}
            )
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400, content={"error": {"code": "invalid_content_length"}}
                )
            if declared_size < 0:
                return JSONResponse(
                    status_code=400, content={"error": {"code": "invalid_content_length"}}
                )
            if declared_size > 4096:
                return JSONResponse(
                    status_code=413, content={"error": {"code": "request_too_large"}}
                )
        body = await request.body()
        if len(body) > 4096:
            return JSONResponse(status_code=413, content={"error": {"code": "request_too_large"}})
        try:
            authenticator.verify(
                timestamp=timestamp,
                nonce=nonce,
                signature=signature,
                body=body,
                now=datetime.now(UTC),
            )
        except AgentAuthenticationError:
            return JSONResponse(
                status_code=401, content={"error": {"code": "authentication_failed"}}
            )
        return body

    @app.post("/v1/inspect")
    async def inspect(
        request: Request,
        x_morpheus_timestamp: str = Header(),
        x_morpheus_nonce: str = Header(),
        x_morpheus_signature: str = Header(),
    ) -> Any:
        authenticated = await authenticated_body(
            request,
            timestamp=x_morpheus_timestamp,
            nonce=x_morpheus_nonce,
            signature=x_morpheus_signature,
        )
        if isinstance(authenticated, JSONResponse):
            return authenticated
        body = authenticated
        try:
            parsed = AgentRequest.model_validate_json(body)
        except ValidationError:
            return JSONResponse(status_code=422, content={"error": {"code": "invalid_request"}})
        if not await request_limiter.try_acquire():
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "1"},
                content={"error": {"code": "request_capacity_exhausted"}},
            )
        try:
            try:
                result = inspector.inspect(parsed.operation)
            except PermissionError:
                return JSONResponse(
                    status_code=403, content={"error": {"code": "authorization_denied"}}
                )
            return AgentResponse(
                request_id=parsed.request_id, operation=parsed.operation, result=result
            )
        finally:
            await request_limiter.release()

    @app.post("/v1/lifecycle")
    async def execute_lifecycle(
        request: Request,
        x_morpheus_timestamp: str = Header(),
        x_morpheus_nonce: str = Header(),
        x_morpheus_signature: str = Header(),
    ) -> Any:
        authenticated = await authenticated_body(
            request,
            timestamp=x_morpheus_timestamp,
            nonce=x_morpheus_nonce,
            signature=x_morpheus_signature,
        )
        if isinstance(authenticated, JSONResponse):
            return authenticated
        try:
            parsed = AgentLifecycleRequest.model_validate_json(authenticated)
            operation = LifecycleRequest(
                action=parsed.action,
                version=parsed.version,
                backup_id=parsed.backup_id,
                confirmation=parsed.confirmation,
                lab_authorized=settings.lifecycle_lab_authorized,
            )
        except (ValidationError, ValueError):
            return JSONResponse(status_code=422, content={"error": {"code": "invalid_request"}})
        if lifecycle is None:
            return JSONResponse(
                status_code=503, content={"error": {"code": "lifecycle_unavailable"}}
            )
        if not await request_limiter.try_acquire():
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "1"},
                content={"error": {"code": "request_capacity_exhausted"}},
            )
        try:
            try:
                result = lifecycle.execute(operation)
            except PermissionError:
                return JSONResponse(
                    status_code=403, content={"error": {"code": "authorization_denied"}}
                )
            except RuntimeError:
                return JSONResponse(
                    status_code=409, content={"error": {"code": "lifecycle_conflict"}}
                )
            return AgentLifecycleResponse(
                request_id=parsed.request_id,
                action=parsed.action,
                result=result.as_dict(),
            )
        finally:
            await request_limiter.release()

    return app


def run() -> None:
    settings = load_settings()
    inspector = SystemHostInspector(project_id=settings.project_id, data_dir=settings.data_dir)
    lifecycle: LifecycleExecutor | None = None
    if settings.enable_lifecycle:
        from morpheus.adapters.runtime.lifecycle import DockerComposeLifecycleAdapter
        from morpheus.ops.lifecycle import LifecycleCoordinator

        assert settings.lifecycle_deployment_root is not None
        lifecycle = LifecycleCoordinator(
            adapter=DockerComposeLifecycleAdapter(
                project_id=settings.project_id,
                deployment_root=settings.lifecycle_deployment_root,
                data_root=settings.data_dir,
                external_network=settings.external_docker_network,
            ),
            project_id=settings.project_id,
        )
    app = create_agent_app(settings=settings, inspector=inspector, lifecycle=lifecycle)
    if settings.runtime_agent_socket is None:
        uvicorn.run(app, host="127.0.0.1", port=settings.agent_port, access_log=False)
        return
    _run_unix_socket(app, settings.runtime_agent_socket)


def _run_unix_socket(app: FastAPI, path: Path) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if path.exists():
        if not path.is_socket():
            raise ValueError("runtime agent socket path exists and is not a socket")
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        previous_umask = os.umask(0o117)
        try:
            listener.bind(str(path))
        finally:
            os.umask(previous_umask)
        listener.listen(128)
        uvicorn.run(app, fd=listener.fileno(), access_log=False)
    finally:
        listener.close()
        if path.is_socket():
            path.unlink()
