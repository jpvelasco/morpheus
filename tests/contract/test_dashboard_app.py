from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from morpheus.dashboard.app import create_dashboard_app

pytestmark = pytest.mark.contract


def test_UI_001_dashboard_serves_spa_assets_with_security_headers(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<main>Morpheus</main>", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("export {}", encoding="utf-8")
    client = TestClient(create_dashboard_app(tmp_path))

    health = client.get("/healthz")
    route = client.get("/systems/inference")
    asset = client.get("/assets/app.js")

    assert health.json() == {"status": "ok"}
    assert route.text == "<main>Morpheus</main>"
    assert asset.text == "export {}"
    assert route.headers["x-frame-options"] == "DENY"
    assert route.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in route.headers["content-security-policy"]


def test_UI_001_dashboard_rejects_missing_build(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="index.html"):
        create_dashboard_app(tmp_path)


def test_UI_001_dashboard_assets_are_optional(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("ready", encoding="utf-8")
    response = TestClient(create_dashboard_app(tmp_path)).get("/missing")
    assert response.text == "ready"
