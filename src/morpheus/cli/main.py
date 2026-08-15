from __future__ import annotations

import json
import os
from typing import Annotated, Any

import httpx
import typer

app = typer.Typer(help="Read-only Morpheus operator commands", no_args_is_help=True)


def _request(path: str) -> dict[str, Any]:
    base_url = os.environ.get("MORPHEUS_CONTROL_URL", "http://127.0.0.1:7400").rstrip("/")
    api_key = os.environ.get("MORPHEUS_API_KEY", "")
    response = httpx.get(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=5,
    )
    response.raise_for_status()
    value: dict[str, Any] = response.json()
    return value


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(_humanize(payload))


def _humanize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


@app.command()
def status(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Show inference and capability status."""
    try:
        payload = {
            "health": _request("/api/v1/health"),
            "capabilities": _request("/api/v1/capabilities"),
        }
    except httpx.HTTPError as error:
        _emit({"status": "unreachable", "error": type(error).__name__}, as_json=as_json)
        raise typer.Exit(2) from None
    _emit(payload, as_json=as_json)


@app.command()
def models(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """List served model identities and aliases."""
    try:
        payload = _request("/api/v1/models")
    except httpx.HTTPError as error:
        _emit({"status": "unreachable", "error": type(error).__name__}, as_json=as_json)
        raise typer.Exit(2) from None
    _emit(payload, as_json=as_json)


@app.command()
def recommend(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Show the latest model recommendation with exclusion explanations."""
    try:
        payload = _request("/api/v1/recommendations/latest")
    except httpx.HTTPError as error:
        _emit(
            {
                "status": "unavailable",
                "error": type(error).__name__,
                "hint": "Generate one via the dashboard or the POST "
                "/api/v1/recommendations endpoint",
            },
            as_json=as_json,
        )
        raise typer.Exit(2) from None
    _emit(payload, as_json=as_json)


@app.command()
def doctor(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Run read-only configuration and dependency diagnostics."""
    checks: list[dict[str, Any]] = []
    try:
        diagnostics = _request("/api/v1/diagnostics")
        checks.append({"code": "control_api_ready", "status": "pass"})
        diagnostic_status = diagnostics.get("status", "ready")
        status = (
            diagnostic_status
            if diagnostic_status in {"ready", "degraded", "unhealthy"}
            else "unhealthy"
        )
        payload = {"status": status, "checks": checks, "diagnostics": diagnostics}
        exit_code = 0 if status == "ready" else 1
    except httpx.HTTPError as error:
        checks.append(
            {
                "code": "control_api_unreachable",
                "status": "fail",
                "summary": type(error).__name__,
            }
        )
        payload = {"status": "unreachable", "checks": checks}
        exit_code = 2
    _emit(payload, as_json=as_json)
    if exit_code:
        raise typer.Exit(exit_code)
