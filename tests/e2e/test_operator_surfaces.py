from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ServedModel

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"UI-001"})


def test_UI_001_operator_overview_traverses_the_public_control_api() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    control_app = create_app(
        settings=MorpheusSettings(api_key="e2e-key"),
        inference=FakeInference(
            health_result=Evidence(
                state=HealthState.READY,
                reason_code="ready",
                summary="ready",
                observed_at=now,
                duration=timedelta(0),
                source="e2e",
                expires_at=now + timedelta(seconds=30),
            ),
            model_results=(ServedModel(root=None, aliases=("model",)),),
        ),
        clock=FakeClock(now=now),
    )

    overview = (
        TestClient(control_app)
        .get("/api/v1/overview", headers={"Authorization": "Bearer e2e-key"})
        .json()
    )
    assert overview["inference"]["state"] == "ready"
    assert overview["models"][0]["aliases"] == ["model"]
    assert overview["external_controls"] == []
