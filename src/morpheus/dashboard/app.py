from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def create_dashboard_app(static_root: Path) -> FastAPI:
    root = static_root.resolve()
    if not (root / "index.html").is_file():
        raise FileNotFoundError("dashboard build is missing index.html")
    app = FastAPI(title="Morpheus Dashboard", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self' http://127.0.0.1:7400; "
            "img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/{path:path}", response_class=FileResponse)
    async def single_page_app(path: str) -> Path:
        del path
        return root / "index.html"

    return app


def run() -> None:
    root = Path(os.environ.get("MORPHEUS_DASHBOARD_DIR", "/app/web"))
    app = create_dashboard_app(root)
    host = os.environ.get("MORPHEUS_BIND_ADDRESS", "127.0.0.1")
    uvicorn.run(app, host=host, port=7401, access_log=False)
