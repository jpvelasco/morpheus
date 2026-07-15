from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from morpheus.cli import main
from morpheus.cli.main import app

runner = CliRunner()


def test_RUN_006_doctor_json_has_stable_exit_code_and_schema(monkeypatch: object) -> None:
    monkeypatch.setenv("MORPHEUS_API_KEY", "test-key")  # type: ignore[attr-defined]
    monkeypatch.setenv("MORPHEUS_CONTROL_URL", "http://127.0.0.1:1")  # type: ignore[attr-defined]
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 2
    assert payload["status"] == "unreachable"
    assert payload["checks"][0]["code"] == "control_api_unreachable"


def test_cli_help_lists_read_only_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "status" in result.stdout
    assert "models" in result.stdout
    assert "doctor" in result.stdout
    assert "start" not in result.stdout
    assert "stop" not in result.stdout


def response(payload: object) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "http://control.test"),
    )


def test_RUN_006_status_and_models_render_successful_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get(url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["timeout"] == 5
        if url.endswith("/health"):
            return response({"health": {"state": "ready"}})
        if url.endswith("/capabilities"):
            return response({"capabilities": {"core": {"state": "available"}}})
        return response({"models": [{"aliases": ["model"]}]})

    monkeypatch.setattr(main.httpx, "get", get)
    status_result = runner.invoke(app, ["status", "--json"])
    models_result = runner.invoke(app, ["models"])

    assert status_result.exit_code == 0
    assert json.loads(status_result.stdout)["health"]["health"]["state"] == "ready"
    assert models_result.exit_code == 0
    assert '"models"' in models_result.stdout


def test_RUN_006_models_reports_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str, **kwargs: object) -> httpx.Response:
        del kwargs
        raise httpx.ConnectError("offline", request=httpx.Request("GET", url))

    monkeypatch.setattr(main.httpx, "get", fail)
    result = runner.invoke(app, ["models", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["status"] == "unreachable"


def test_RUN_006_doctor_reports_ready_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.httpx, "get", lambda url, **kwargs: response({"safe": True}))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "checks": [{"code": "control_api_ready", "status": "pass"}],
        "diagnostics": {"safe": True},
        "status": "ready",
    }
