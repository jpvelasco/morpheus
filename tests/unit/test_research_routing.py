"""Unit tests: research request routing contract (RSCH-002)."""

from __future__ import annotations

import pytest

from morpheus.core.research_routing import (
    ResearchRequest,
    build_research_request,
    verify_research_request,
)

CONFIGURED_MODEL = "coder-model-27b"


def test_build_research_request_pins_configured_model_id() -> None:
    request = build_research_request("who manages gpu memory", configured_model_id=CONFIGURED_MODEL)
    assert isinstance(request, ResearchRequest)
    assert request.model_id == CONFIGURED_MODEL
    assert request.query == "who manages gpu memory"


def test_build_research_request_preserves_no_thinking_by_default() -> None:
    request = build_research_request("who manages gpu memory", configured_model_id=CONFIGURED_MODEL)
    assert request.no_thinking is True


def test_build_research_request_never_accepts_client_model_id() -> None:
    with pytest.raises(TypeError):
        build_research_request(
            "who manages gpu memory",
            configured_model_id=CONFIGURED_MODEL,
            client_model_id="attacker-chosen-model",  # type: ignore[call-arg]
        )
    request = build_research_request("who manages gpu memory", configured_model_id=CONFIGURED_MODEL)
    assert request.model_id != "attacker-chosen-model"


def test_build_research_request_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query"):
        build_research_request("", configured_model_id=CONFIGURED_MODEL)


def test_build_research_request_rejects_unbounded_query() -> None:
    with pytest.raises(ValueError, match="query"):
        build_research_request("x" * 40_000, configured_model_id=CONFIGURED_MODEL)


def test_build_research_request_rejects_unbounded_model_id() -> None:
    with pytest.raises(ValueError, match="model id"):
        build_research_request("who manages gpu memory", configured_model_id="x" * 200)


def test_verify_research_request_accepts_pinned_request() -> None:
    request = build_research_request("who manages gpu memory", configured_model_id=CONFIGURED_MODEL)
    outcome = verify_research_request(request, configured_model_id=CONFIGURED_MODEL)
    assert outcome.accepted is True
    assert outcome.reasons == ()


def test_verify_research_request_rejects_wrong_model_or_thinking() -> None:
    request = build_research_request("who manages gpu memory", configured_model_id=CONFIGURED_MODEL)
    wrong_model = ResearchRequest(
        query=request.query,
        model_id="another-model",
        no_thinking=request.no_thinking,
    )
    outcome = verify_research_request(wrong_model, configured_model_id=CONFIGURED_MODEL)
    assert outcome.accepted is False
    assert any("model id" in reason for reason in outcome.reasons)
    thinking_request = ResearchRequest(
        query=request.query,
        model_id=request.model_id,
        no_thinking=False,
    )
    thinking_outcome = verify_research_request(
        thinking_request, configured_model_id=CONFIGURED_MODEL
    )
    assert thinking_outcome.accepted is False
    assert any("no-thinking" in reason for reason in thinking_outcome.reasons)
