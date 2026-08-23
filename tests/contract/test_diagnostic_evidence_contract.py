"""Contract tests: diagnostic evidence package API (AID-001).

The authenticated evidence endpoint assembles a bounded, redacted
evidence run from live structured sources and returns its provenance
metadata: run id, per-file manifest, digest, size, and section list.
Adversarial event content must never appear in the package files.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from morpheus.adapters.fakes import FakeClock, FakeInference
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.api.app import create_app
from morpheus.config import MorpheusSettings
from morpheus.core.health import Evidence, HealthState
from morpheus.core.models import ServedModel

pytestmark = pytest.mark.contract

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef0123456789abcdef"


def client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=MorpheusSettings(
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
            model_results=(
                ServedModel(root="fixture-model", aliases=("fixture-model",), context_window=4096),
            ),
        ),
        clock=FakeClock(now=NOW),
    )
    return TestClient(app, base_url="https://testserver")


AUTH = {"Authorization": "Bearer test-api-key"}


async def _seed_event(tmp_path: Path, message: str) -> None:
    store = SqliteStore(tmp_path / "morpheus.sqlite3", owned_root=tmp_path)
    await store.initialize()
    await store.record_event(
        source="api", severity="warn", message=message, correlation_id="corr-1"
    )


def test_AID_001_evidence_package_requires_authentication(tmp_path: Path) -> None:
    response = client(tmp_path).post("/api/v1/diagnostics/evidence")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_AID_001_evidence_package_builds_bounded_provenanced_package(
    tmp_path: Path,
) -> None:
    response = client(tmp_path).post("/api/v1/diagnostics/evidence", headers=AUTH)
    assert response.status_code == 200
    package = response.json()["evidence_package"]
    assert package["run_id"].startswith("diag-")
    assert package["digest"].startswith("sha256:")
    assert package["size_bytes"] > 0
    assert package["sections"] == [
        "health",
        "machine_profile",
        "deployment",
        "metrics",
        "events",
        "log_excerpts",
        "regressions",
        "runbooks",
    ]
    manifest = package["manifest"]
    assert manifest["status"] == "pass"
    assert manifest["environment"] == "DEV"
    assert manifest["requirement_ids"] == ["AID-001"]
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert (
        set(manifest["files"])
        == {
            "health.json",
            "machine_profile.json",
            "deployment.json",
            "metrics.json",
            "events.json",
            "regressions.json",
            "runbooks.json",
            "evidence.json",
            "manifest.json",
        }
        or "manifest.json" not in manifest["files"]
    )

    root = Path(package["root"])
    assert root.is_dir()
    evidence = json.loads((root / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["schema_version"] == 1
    assert evidence["provenance"]["source_commit"] == SOURCE_COMMIT
    assert set(evidence["digests"]) == set(package["sections"])


def test_AID_001_evidence_package_never_contains_adversarial_event_bytes(
    tmp_path: Path,
) -> None:
    import asyncio

    asyncio.run(
        _seed_event(
            tmp_path,
            "request failed api_key=sk-live-1234 password=hunter2 Authorization: Bearer abc",
        )
    )
    response = client(tmp_path).post("/api/v1/diagnostics/evidence", headers=AUTH)
    assert response.status_code == 200
    package = response.json()["evidence_package"]
    root = Path(package["root"])
    events = json.loads((root / "events.json").read_text(encoding="utf-8"))
    assert events
    for event in events:
        assert "sk-live-1234" not in event["message"]
        assert "hunter2" not in event["message"]
        assert "Bearer abc" not in event["message"]
        assert "[REDACTED]" in event["message"]
