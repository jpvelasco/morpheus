from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

app = typer.Typer(help="Read-only Morpheus operator commands", no_args_is_help=True)


def _base_url() -> str:
    return os.environ.get("MORPHEUS_CONTROL_URL", "http://127.0.0.1:7400").rstrip("/")


def _api_key() -> str:
    return os.environ.get("MORPHEUS_API_KEY", "")


def _request(path: str) -> dict[str, Any]:
    response = httpx.get(
        f"{_base_url()}{path}",
        headers={"Authorization": f"Bearer {_api_key()}"},
        timeout=5,
    )
    response.raise_for_status()
    value: dict[str, Any] = response.json()
    return value


def _send(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Authenticated state-changing request: session sign-in, then CSRF POST."""
    with httpx.Client(base_url=_base_url(), timeout=10) as client:
        signin = client.post("/api/v1/session", json={"api_key": _api_key()})
        signin.raise_for_status()
        csrf = client.cookies.get("morpheus_csrf") or ""
        response = client.post(
            path,
            json=payload,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "X-CSRF-Token": csrf,
            },
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
                "hint": "No recommendation stored yet; generate one with "
                "morpheus recommend-generate --profile <id> --catalog-digest <sha256>",
            },
            as_json=as_json,
        )
        raise typer.Exit(2) from None
    _emit(payload, as_json=as_json)


@app.command()
def recommend_generate(
    profile: Annotated[str, typer.Option("--profile", help="Workload policy id")],
    catalog_digest: Annotated[
        str, typer.Option("--catalog-digest", help="Retained catalog snapshot digest")
    ],
    operator: Annotated[
        str | None,
        typer.Option("--operator", help="Operator caps as JSON, e.g. '{\"max_concurrency\": 1}'"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate an evidence-backed recommendation from retained repositories."""
    try:
        payload = _send(
            "/api/v1/recommendations",
            {
                "profile": profile,
                "catalog_digest": catalog_digest,
                **({"operator": json.loads(operator)} if operator else {}),
            },
        )
    except (httpx.HTTPError, ValueError) as error:
        _emit(
            {
                "status": "unavailable",
                "error": type(error).__name__,
                "hint": "Seed a catalog first: morpheus catalog-seed --file catalog.json",
            },
            as_json=as_json,
        )
        raise typer.Exit(2) from None
    _emit(payload, as_json=as_json)


@app.command()
def choose_plan(
    recommendation_id: Annotated[str, typer.Option("--recommendation-id")],
    plan_id: Annotated[str, typer.Option("--plan-id")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Choose one ranked canonical plan; the choice is audited, not silent."""
    try:
        payload = _send(
            "/api/v1/plans/from-recommendation",
            {
                "recommendation_id": recommendation_id,
                "plan_id": plan_id,
                "ownership": "managed",
            },
        )
    except httpx.HTTPError as error:
        _emit(
            {"status": "failed", "error": type(error).__name__},
            as_json=as_json,
        )
        raise typer.Exit(2) from None
    _emit(payload, as_json=as_json)


@app.command("catalog-seed")
def catalog_seed(
    file: Annotated[Path, typer.Option("--file", help="Catalog JSON document to retain")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explicitly retain one catalog snapshot for evidence-backed selection."""
    try:
        catalog = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        _emit({"status": "failed", "error": f"unreadable catalog file: {error}"}, as_json=as_json)
        raise typer.Exit(2) from None
    try:
        payload = _send("/api/v1/catalog/snapshots", {"catalog": catalog})
    except httpx.HTTPError as error:
        _emit({"status": "failed", "error": type(error).__name__}, as_json=as_json)
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
