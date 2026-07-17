from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

import httpx
import typer

from morpheus.adapters.runtime.agent import RuntimeAgentClient
from morpheus.config import load_settings
from morpheus.core.lifecycle import LifecycleAction, LifecycleRequest

app = typer.Typer(
    help="Authenticated lifecycle commands for Morpheus-owned resources only",
    no_args_is_help=True,
)


def _execute(request: LifecycleRequest) -> dict[str, Any]:
    settings = load_settings()
    key = settings.agent_key.get_secret_value().encode()
    if not key:
        raise RuntimeError("runtime agent authentication is not configured")
    client = RuntimeAgentClient(
        base_url=settings.runtime_agent_url or "http://127.0.0.1:7402",
        key=key,
        uds=settings.runtime_agent_socket,
    )
    return asyncio.run(client.lifecycle(request)).result


def _run(request: LifecycleRequest, *, as_json: bool) -> None:
    try:
        payload = _execute(request)
    except (httpx.HTTPError, RuntimeError, ValueError) as error:
        payload = {
            "action": request.action.value,
            "error": type(error).__name__,
            "outcome": "failed",
        }
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(2) from None
    typer.echo(json.dumps(payload, sort_keys=True) if as_json else _humanize(payload))


def _humanize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


@app.command()
def install(
    version: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Install one staged Morpheus release without starting it."""
    _run(LifecycleRequest(LifecycleAction.INSTALL, version=version), as_json=as_json)


@app.command()
def validate(
    version: Annotated[str | None, typer.Argument()] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate the staged or active Morpheus release."""
    _run(LifecycleRequest(LifecycleAction.VALIDATE, version=version), as_json=as_json)


@app.command()
def start(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Start only the installed Morpheus release."""
    _run(LifecycleRequest(LifecycleAction.START), as_json=as_json)


@app.command()
def stop(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Stop only running Morpheus services."""
    _run(LifecycleRequest(LifecycleAction.STOP), as_json=as_json)


@app.command()
def migrate(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Apply the bounded current Morpheus state migration."""
    _run(LifecycleRequest(LifecycleAction.MIGRATE), as_json=as_json)


@app.command()
def backup(
    backup_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create one named Morpheus-only backup."""
    _run(LifecycleRequest(LifecycleAction.BACKUP, backup_id=backup_id), as_json=as_json)


@app.command("restore-preflight")
def restore_preflight(
    backup_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a named backup without changing state."""
    _run(
        LifecycleRequest(LifecycleAction.RESTORE_PREFLIGHT, backup_id=backup_id),
        as_json=as_json,
    )


@app.command()
def upgrade(
    version: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Upgrade to one staged Morpheus release with recovery."""
    _run(LifecycleRequest(LifecycleAction.UPGRADE, version=version), as_json=as_json)


@app.command()
def rollback(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Roll back to the recorded prior Morpheus release."""
    _run(LifecycleRequest(LifecycleAction.ROLLBACK), as_json=as_json)


@app.command()
def uninstall(
    purge_confirmation: Annotated[
        str | None,
        typer.Option(
            "--purge-confirmation",
            help="Lab-only exact value purge:<project-id>; omission preserves data.",
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Remove Morpheus runtime resources and preserve data by default."""
    _run(
        LifecycleRequest(
            LifecycleAction.UNINSTALL,
            confirmation=purge_confirmation,
            lab_authorized=purge_confirmation is not None,
        ),
        as_json=as_json,
    )
