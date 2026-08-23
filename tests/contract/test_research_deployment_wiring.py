"""Contract tests: pinned Perplexica wiring matches the documented shape (RSCH-001)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from morpheus.core.research_deployment import (
    render_perplexica_config,
    validated_research_deployment,
)

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]


def _shipped_config() -> dict[str, object]:
    path = ROOT / "deploy" / "config" / "perplexica" / "config.toml"
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_RSCH_001_shipped_config_matches_the_documented_wiring() -> None:
    shipped = _shipped_config()
    general = shipped["GENERAL"]
    endpoints = shipped["API_ENDPOINTS"]
    model = shipped["MODEL"]
    assert general["PORT"] == 3000
    assert general["SIMILARITY_MEASURE"] == "cosine"
    assert endpoints["SEARXNG"] == "http://search:8080"
    assert endpoints["OPENAI"] == "http://coder-model:8000/v1"
    assert isinstance(model["NAME"], str) and model["NAME"]


def test_RSCH_001_shipped_config_is_deterministically_rendered() -> None:
    shipped = _shipped_config()
    endpoints = shipped["API_ENDPOINTS"]
    model = shipped["MODEL"]
    deployment = validated_research_deployment(
        image_ref="docker.io/example/perplexica:latest@sha256:" + "a" * 64,
        searxng_base_url=str(endpoints["SEARXNG"]),
        llm_base_url=str(endpoints["OPENAI"]),
        model_id=str(model["NAME"]),
        host_port=7412,
    )
    rendered = render_perplexica_config(deployment)
    assert "PORT = 3000" in rendered
    assert f'SEARXNG = "{endpoints["SEARXNG"]}"' in rendered
    assert f'OPENAI = "{endpoints["OPENAI"]}"' in rendered
    assert f'NAME = "{model["NAME"]}"' in rendered


def test_RSCH_001_compose_overlay_is_pinned_profile_gated_and_loopback() -> None:
    overlay = yaml.safe_load(
        (ROOT / "deploy" / "compose.research.yaml").read_text(encoding="utf-8")
    )
    service = overlay["services"]["research"]
    lock = json.loads((ROOT / "deploy" / "images.lock.json").read_text(encoding="utf-8"))
    locked = {item["digest"] for item in lock["images"]}
    assert "@sha256:" in service["image"]
    assert service["image"].rsplit("@", 1)[1] in locked
    assert service.get("profiles"), "research must be opt-in"
    assert str(service["ports"][0]).startswith("127.0.0.1:${MORPHEUS_RESEARCH_PORT")
    assert service["labels"]["io.morpheus.project"] == "${MORPHEUS_PROJECT_ID:-morpheus}"
    volumes = {str(volume).split(":")[0] for volume in service["volumes"]}
    assert "research_data" in volumes
