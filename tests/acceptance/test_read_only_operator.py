from __future__ import annotations

import json

import httpx
import pytest
from typer.testing import CliRunner

from morpheus.cli import main as cli

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"RUN-006"})
pytestmark = pytest.mark.acceptance


def test_RUN_006_doctor_reports_ready_with_control_api_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def routed_get(url: str, **kwargs: object) -> httpx.Response:
        assert url.endswith("/api/v1/diagnostics")
        assert kwargs["headers"] == {"Authorization": "Bearer operator-key"}
        return httpx.Response(
            200,
            json={
                "inference": {"state": "ready"},
                "configuration": {"secrets_configured": {"api_key": True}},
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(cli.httpx, "get", routed_get)
    monkeypatch.setenv("MORPHEUS_API_KEY", "operator-key")
    result = CliRunner().invoke(cli.app, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready"
    assert payload["diagnostics"]["inference"]["state"] == "ready"
    assert payload["diagnostics"]["configuration"]["secrets_configured"]["api_key"] is True
