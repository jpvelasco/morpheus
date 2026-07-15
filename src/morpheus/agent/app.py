from __future__ import annotations

import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from morpheus.agent.auth import AgentAuthenticationError, AgentAuthenticator
from morpheus.agent.host import SystemHostInspector
from morpheus.agent.protocol import AgentRequest, AgentResponse
from morpheus.config import MorpheusSettings, load_settings


def create_agent_app(*, settings: MorpheusSettings, inspector: SystemHostInspector) -> FastAPI:
    key = settings.agent_key.get_secret_value().encode()
    authenticator = AgentAuthenticator(key)
    app = FastAPI(title="Morpheus Runtime Agent", docs_url=None, redoc_url=None)

    @app.post("/v1/inspect")
    async def inspect(
        request: Request,
        x_morpheus_timestamp: str = Header(),
        x_morpheus_nonce: str = Header(),
        x_morpheus_signature: str = Header(),
    ) -> Any:
        body = await request.body()
        if len(body) > 4096:
            return JSONResponse(status_code=413, content={"error": {"code": "request_too_large"}})
        try:
            authenticator.verify(
                timestamp=x_morpheus_timestamp,
                nonce=x_morpheus_nonce,
                signature=x_morpheus_signature,
                body=body,
                now=datetime.now(UTC),
            )
        except AgentAuthenticationError:
            return JSONResponse(
                status_code=401, content={"error": {"code": "authentication_failed"}}
            )
        parsed = AgentRequest.model_validate_json(body)
        result = inspector.inspect(parsed.operation)
        return AgentResponse(
            request_id=parsed.request_id, operation=parsed.operation, result=result
        )

    return app


def run() -> None:
    settings = load_settings()
    inspector = SystemHostInspector(project_id=settings.project_id, data_dir=settings.data_dir)
    app = create_agent_app(settings=settings, inspector=inspector)
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
