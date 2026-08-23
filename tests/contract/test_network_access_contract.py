"""Contract tests: TLS network access profile (ACCESS-002).

The network profile enforces explicit origins, TLS posture, never-trusted
proxy headers, and rate limits; exposure, origin, proxy-header,
brute-force, and recovery behavior is deterministic and fixture-driven.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ModelIdentity

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"ACCESS-002"})

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef0123456789abcdef"


def network_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
            api_key="network-test-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            release_version="0.1.0",
            source_commit=SOURCE_COMMIT,
            bind_address="192.168.1.10",
            allow_lan=True,
            access_profile="network",
            tls_cert_path="C:/certs/server.crt",
            tls_key_path="C:/certs/server.key",
            allowed_origins="https://inference.example",
            session_cookie_secure=True,
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
                ModelIdentity(
                    root="fixture-model", aliases=("fixture-model",), context_window=4096
                ),
            ),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app, base_url="https://inference.example")


AUTH = {"Authorization": "Bearer network-test-key"}


def test_ACCESS_002_network_report_shows_tls_and_origin_posture(tmp_path: Path) -> None:
    response = network_client(tmp_path).get("/api/v1/system/access", headers=AUTH)
    assert response.status_code == 200
    access = response.json()["access"]
    assert access["profile"] == "network"
    assert access["tls_enabled"] is True
    assert access["allowed_origins"] == ["https://inference.example"]
    assert access["loopback_only"] is False
    assert access["proxy_headers_trusted"] is False


def test_ACCESS_002_allowed_origin_is_served(tmp_path: Path) -> None:
    response = network_client(tmp_path).get("/api/v1/system/access", headers=AUTH)
    assert response.status_code == 200


def test_ACCESS_002_disallowed_host_is_rejected(tmp_path: Path) -> None:
    test_client = network_client(tmp_path)
    test_client.headers["Host"] = "evil.example"
    response = test_client.get("/api/v1/system/access", headers=AUTH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_ACCESS_002_proxy_headers_never_bypass_origin_or_auth(tmp_path: Path) -> None:
    test_client = network_client(tmp_path)
    test_client.headers["Host"] = "evil.example"
    test_client.headers["X-Forwarded-For"] = "127.0.0.1"
    test_client.headers["X-Forwarded-Host"] = "inference.example"
    response = test_client.get("/api/v1/health", headers=AUTH)
    assert response.status_code == 403
    spoofed = network_client(tmp_path)
    spoofed.headers["X-Forwarded-For"] = "203.0.113.5"
    response = spoofed.get("/api/v1/health")
    assert response.status_code == 401


def test_ACCESS_002_login_uses_secure_cookies_over_network(tmp_path: Path) -> None:
    test_client = network_client(tmp_path)
    login = test_client.post("/api/v1/session", json={"api_key": "network-test-key"})
    assert login.status_code == 200
    assert "Secure" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]
    assert "HttpOnly" in login.headers["set-cookie"]


def test_ACCESS_002_brute_force_login_is_rate_limited(tmp_path: Path) -> None:
    test_client = network_client(tmp_path, max_requests_per_minute=5)
    statuses = [
        test_client.post("/api/v1/session", json={"api_key": "wrong-key"}).status_code
        for _ in range(8)
    ]
    assert statuses[0] in {401, 429}
    assert 429 in statuses
    assert statuses[-1] == 429


def test_ACCESS_002_recovery_after_restart_restores_login(tmp_path: Path) -> None:
    first = network_client(tmp_path, max_requests_per_minute=5)
    for _ in range(8):
        first.post("/api/v1/session", json={"api_key": "wrong-key"})
    assert first.post("/api/v1/session", json={"api_key": "wrong-key"}).status_code == 429
    restarted = network_client(tmp_path, max_requests_per_minute=5)
    login = restarted.post("/api/v1/session", json={"api_key": "network-test-key"})
    assert login.status_code == 200
    assert login.json() == {"status": "authenticated"}


def test_ACCESS_002_loopback_profiles_are_unaffected_by_origin_controls(
    tmp_path: Path,
) -> None:
    from morpheus.config import MorpheusSettings as Settings

    app = create_app(
        settings=Settings(
            api_key="test-api-key",
            session_secret="session-test-secret",
            data_dir=tmp_path,
            release_version="0.1.0",
            source_commit=SOURCE_COMMIT,
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
            model_results=(),
        ),
        clock=FakeClock(now=NOW),
    )
    test_client = TestClient(app, base_url="https://testserver")
    test_client.headers["Host"] = "anything.example"
    response = test_client.get("/api/v1/health", headers={"Authorization": "Bearer test-api-key"})
    assert response.status_code == 200
