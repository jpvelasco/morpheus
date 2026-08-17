"""Unit tests: RAG explicit-need policy (RAG-001)."""

from __future__ import annotations

import pytest

from morpheus.core.rag_policy import (
    RAG_DEFAULT_OFF_NOTE,
    RagEnablementDecision,
    evaluate_rag_enablement,
)


def test_evaluate_rag_enablement_is_off_by_default() -> None:
    decision = evaluate_rag_enablement(enabled=False)
    assert decision.enabled is False
    assert decision.explicit_need_confirmed is False
    assert decision.accepted is True
    assert decision.reasons == ()


def test_evaluate_rag_enablement_requires_explicit_need() -> None:
    decision = evaluate_rag_enablement(enabled=True, explicit_need_confirmed=False)
    assert decision.accepted is False
    assert any(RAG_DEFAULT_OFF_NOTE in reason for reason in decision.reasons)


def test_evaluate_rag_enablement_accepts_explicitly_confirmed_need() -> None:
    decision = evaluate_rag_enablement(enabled=True, explicit_need_confirmed=True)
    assert decision.enabled is True
    assert decision.explicit_need_confirmed is True
    assert decision.accepted is True
    assert decision.reasons == ()


def test_evaluate_rag_enablement_ignores_confirmation_when_off() -> None:
    decision = evaluate_rag_enablement(enabled=False, explicit_need_confirmed=True)
    assert decision.enabled is False
    assert decision.accepted is True


def test_rag_enablement_decision_is_typed_and_immutable() -> None:
    decision = evaluate_rag_enablement(enabled=False)
    assert isinstance(decision, RagEnablementDecision)
    assert isinstance(decision.reasons, tuple)
    with pytest.raises(AttributeError):
        decision.enabled = True  # type: ignore[misc]


def test_rag_enablement_denial_carries_blocker_state() -> None:
    decision = evaluate_rag_enablement(enabled=True)
    assert decision.blockers == decision.reasons
    assert decision.blockers
    assert "Open WebUI" in decision.blockers[0]
