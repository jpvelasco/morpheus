"""Unit tests: pinned Perplexica research deployment wiring (RSCH-001)."""

from __future__ import annotations

import pytest

from morpheus.core.research_deployment import (
    ResearchDeployment,
    render_perplexica_config,
    validated_research_deployment,
)

PINNED = "docker.io/example/perplexica:latest@sha256:" + "a" * 64


def test_validated_deployment_accepts_safe_wiring() -> None:
    deployment = validated_research_deployment(
        image_ref=PINNED,
        searxng_base_url="http://search:8080",
        llm_base_url="http://coder-model:8000/v1",
        model_id="coder-model-27b",
        host_port=7412,
    )
    assert isinstance(deployment, ResearchDeployment)
    assert deployment.model_id == "coder-model-27b"
    assert deployment.host_port == 7412


def test_validated_deployment_rejects_unpinned_image() -> None:
    with pytest.raises(ValueError, match="digest"):
        validated_research_deployment(
            image_ref="docker.io/example/perplexica:latest",
            searxng_base_url="http://search:8080",
            llm_base_url="http://coder-model:8000/v1",
            model_id="coder-model-27b",
        )
    with pytest.raises(ValueError, match="digest"):
        validated_research_deployment(
            image_ref="docker.io/example/perplexica:latest@sha256:short",
            searxng_base_url="http://search:8080",
            llm_base_url="http://coder-model:8000/v1",
            model_id="coder-model-27b",
        )


def test_validated_deployment_rejects_unsafe_endpoints() -> None:
    with pytest.raises(ValueError, match="http or https"):
        validated_research_deployment(
            image_ref=PINNED,
            searxng_base_url="file:///etc/passwd",
            llm_base_url="http://coder-model:8000/v1",
            model_id="m",
        )
    with pytest.raises(ValueError, match="credentials"):
        validated_research_deployment(
            image_ref=PINNED,
            searxng_base_url="http://search:8080",
            llm_base_url="https://user:pass@coder-model:8000/v1",
            model_id="m",
        )
    with pytest.raises(ValueError, match="query or fragment"):
        validated_research_deployment(
            image_ref=PINNED,
            searxng_base_url="http://search:8080",
            llm_base_url="http://coder-model:8000/v1?x=1",
            model_id="m",
        )


def test_validated_deployment_rejects_unbounded_model_id() -> None:
    with pytest.raises(ValueError, match="model id"):
        validated_research_deployment(
            image_ref=PINNED,
            searxng_base_url="http://search:8080",
            llm_base_url="http://coder-model:8000/v1",
            model_id="x" * 200,
        )


def test_validated_deployment_rejects_unsafe_host_port() -> None:
    with pytest.raises(ValueError, match="port"):
        validated_research_deployment(
            image_ref=PINNED,
            searxng_base_url="http://search:8080",
            llm_base_url="http://coder-model:8000/v1",
            model_id="m",
            host_port=0,
        )
    with pytest.raises(ValueError, match="port"):
        validated_research_deployment(
            image_ref=PINNED,
            searxng_base_url="http://search:8080",
            llm_base_url="http://coder-model:8000/v1",
            model_id="m",
            host_port=70_000,
        )


def test_render_perplexica_config_is_deterministic_and_wired() -> None:
    deployment = validated_research_deployment(
        image_ref=PINNED,
        searxng_base_url="http://search:8080",
        llm_base_url="http://coder-model:8000/v1",
        model_id="coder-model-27b",
        host_port=7412,
    )
    rendered = render_perplexica_config(deployment)
    assert "PORT = 3000" in rendered
    assert 'SIMILARITY_MEASURE = "cosine"' in rendered
    assert 'SEARXNG = "http://search:8080"' in rendered
    assert 'OPENAI = "http://coder-model:8000/v1"' in rendered
    assert 'NAME = "coder-model-27b"' in rendered
    assert render_perplexica_config(deployment) == rendered


def test_render_perplexica_config_never_contains_secrets() -> None:
    deployment = validated_research_deployment(
        image_ref=PINNED,
        searxng_base_url="http://search:8080",
        llm_base_url="http://coder-model:8000/v1",
        model_id="m",
    )
    rendered = render_perplexica_config(deployment)
    assert "KEY" not in rendered.upper()
    assert "PASSWORD" not in rendered.upper()
