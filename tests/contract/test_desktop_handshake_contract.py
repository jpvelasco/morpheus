"""Contract tests: authenticated desktop compatibility handshake (DESK-002)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ServedModel

pytestmark = pytest.mark.contract

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def client() -> TestClient:
    app = create_app(
        settings=MorpheusSettings(api_key="test-api-key", session_secret="session-test-secret"),
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
                ServedModel(root="fixture-model", aliases=("fixture-model",), context_window=4096),
            ),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app, base_url="https://testserver")


AUTH = {"Authorization": "Bearer test-api-key"}


def test_DESK_002_compatibility_requires_authentication() -> None:
    response = client().get("/api/v1/system/compatibility")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_DESK_002_compatibility_reports_versions_platform_and_operations() -> None:
    response = client().get(
        "/api/v1/system/compatibility",
        headers={**AUTH, "X-Morpheus-Desktop-Version": "0.1.0"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["api_version"] == 1
    assert payload["backend_version"] == "0.1.0"
    assert payload["os"] in {"windows", "linux", "darwin"}
    assert payload["architecture"]
    assert {"id": "llama.cpp", "tier": "stable"} in payload["adapters"]
    assert "health" in payload["operations"]
    assert payload["compatibility"]["status"] == "compatible"
    assert payload["compatibility"]["desktop_version"] == "0.1.0"


def test_DESK_002_compatibility_reports_unsupported_desktop_range() -> None:
    response = client().get(
        "/api/v1/system/compatibility",
        headers={**AUTH, "X-Morpheus-Desktop-Version": "9.9.9"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["compatibility"]["status"] == "unsupported_desktop"
    assert payload["compatibility"]["supported_desktop_range"] == {
        "min": "0.1.0",
        "max": "0.1.0",
    }


def test_DESK_002_compatibility_reports_missing_desktop_version() -> None:
    response = client().get("/api/v1/system/compatibility", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["compatibility"]["status"] == "missing_desktop_version"


def test_DESK_002_compatibility_route_is_versioned_and_bounded() -> None:
    routes = {route.path for route in client().app.routes}
    assert "/api/v1/system/compatibility" in routes
    assert "/api/v1/system/other" not in routes
