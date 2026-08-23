"""Contract tests: secure access profiles and desktop parity (ACCESS-001, DESK-003).

Loopback and SSH-tunnel access share one posture: authenticated browser
sessions over loopback, never trusted proxy headers, and identical
authorization and CSRF semantics whether the request arrives directly or
through an operator-established tunnel. Revocation terminates access
predictably and a new session restores the same semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ServedModel

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"ACCESS-001"})

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef0123456789abcdef"


def client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            release_version="0.1.0",
            source_commit=SOURCE_COMMIT,
            **settings_overrides,
        ),
        inference=FakeInference(
            health_result=Evidence(
                state=HealthState.READY,
                reason_code="ok",
                summary="fixture ready",
                observed_at=NOW,
                duration=timedelta(milliseconds=1),
                source="fixture",
                expires_at=NOW,
            ),
            model_results=(
                ServedModel(
                    root="fixture-model", aliases=("fixture-model",), context_window=4096
                ),
            ),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app, base_url="https://testserver")


AUTH = {"Authorization": "Bearer test-api-key"}


def test_ACCESS_001_access_report_requires_authentication(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/v1/system/access")
    assert response.status_code == 401


def test_ACCESS_001_loopback_posture_reported_without_secrets(tmp_path: Path) -> None:
    response = client(tmp_path).get("/api/v1/system/access", headers=AUTH)
    assert response.status_code == 200
    access = response.json()["access"]
    assert access["profile"] == "loopback"
    assert access["bind_address"] == "127.0.0.1"
    assert access["loopback_only"] is True
    assert access["proxy_headers_trusted"] is False
    assert access["cookie_samesite"] == "strict"
    assert "api_key" not in response.text
    assert "session_secret" not in response.text


def test_ACCESS_001_ssh_tunnel_posture_reports_tunnel_command(tmp_path: Path) -> None:
    response = client(tmp_path, access_profile="ssh_tunnel").get(
        "/api/v1/system/access", headers=AUTH
    )
    assert response.status_code == 200
    access = response.json()["access"]
    assert access["profile"] == "ssh_tunnel"
    assert access["loopback_only"] is True
    assert access["tunnel_command"].startswith("ssh -L 7400")
    assert "7401" in access["tunnel_command"]


def _login(test_client: TestClient) -> None:
    login = test_client.post("/api/v1/session", json={"api_key": "test-api-key"})
    assert login.status_code == 200
    assert login.json() == {"status": "authenticated"}


def test_DESK_003_tunneled_access_has_identical_auth_and_csrf_semantics(
    tmp_path: Path,
) -> None:
    tunnel = client(tmp_path)
    tunnel.headers["Host"] = "127.0.0.1:7400"
    _login(tunnel)
    csrf = tunnel.cookies.get("morpheus_csrf")
    assert csrf
    compatibility = tunnel.get(
        "/api/v1/system/compatibility",
        headers={"X-Morpheus-Desktop-Version": "0.1.0", "X-CSRF-Token": csrf},
    )
    assert compatibility.status_code == 200
    assert compatibility.json()["compatibility"]["status"] == "compatible"
    logout = tunnel.delete("/api/v1/session", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 200
    assert logout.json() == {"status": "signed_out"}


def test_ACCESS_001_revocation_terminates_access_predictably(tmp_path: Path) -> None:
    test_client = client(tmp_path)
    _login(test_client)
    csrf = test_client.cookies.get("morpheus_csrf")
    assert csrf
    revoked = test_client.delete("/api/v1/session", headers={"X-CSRF-Token": csrf})
    assert revoked.status_code == 200
    assert "morpheus_session" not in test_client.cookies
    assert "morpheus_csrf" not in test_client.cookies
    stale = test_client.get("/api/v1/health", headers={"X-CSRF-Token": csrf})
    assert stale.status_code == 401


def test_DESK_003_reconnect_after_revocation_restores_same_semantics(
    tmp_path: Path,
) -> None:
    test_client = client(tmp_path)
    _login(test_client)
    csrf = test_client.cookies.get("morpheus_csrf")
    assert csrf
    test_client.delete("/api/v1/session", headers={"X-CSRF-Token": csrf})
    _login(test_client)
    fresh_csrf = test_client.cookies.get("morpheus_csrf")
    assert fresh_csrf and fresh_csrf != csrf
    health = test_client.get(
        "/api/v1/health",
        headers={"Authorization": "Bearer test-api-key", "X-CSRF-Token": fresh_csrf},
    )
    assert health.status_code == 200
    assert health.json()["health"]["state"] == "ready"
