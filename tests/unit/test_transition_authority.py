"""Unit tests: explicit transition authorization policy (IMG-003)."""

from __future__ import annotations

import pytest

from morpheus.core.transition_authority import (
    EXTERNAL_INFERENCE_NOTE,
    TransitionSession,
    authorize_transition,
)


def test_authorize_transition_rejects_without_operator_confirmation() -> None:
    outcome = authorize_transition(
        operator_confirmed=False, separate_session=True, purpose="restart"
    )
    assert outcome.authorized is False
    assert any(EXTERNAL_INFERENCE_NOTE in reason for reason in outcome.reasons)
    assert outcome.session is None


def test_authorize_transition_rejects_without_separate_session() -> None:
    outcome = authorize_transition(
        operator_confirmed=True, separate_session=False, purpose="restart"
    )
    assert outcome.authorized is False
    assert outcome.session is None


def test_authorize_transition_accepts_operator_run_separately_authorized_session() -> None:
    outcome = authorize_transition(
        operator_confirmed=True, separate_session=True, purpose="restart"
    )
    assert outcome.authorized is True
    assert outcome.reasons == ()
    session = outcome.session
    assert isinstance(session, TransitionSession)
    assert session.purpose == "restart"
    assert session.active is True


def test_authorize_transition_rejects_unknown_purpose() -> None:
    with pytest.raises(ValueError, match="purpose"):
        authorize_transition(operator_confirmed=True, separate_session=True, purpose="")  # type: ignore[arg-type]


def test_transition_session_ends_after_use() -> None:
    outcome = authorize_transition(
        operator_confirmed=True, separate_session=True, purpose="restart"
    )
    assert outcome.session is not None
    ended = outcome.session.end()
    assert ended.active is False
    assert ended.completed is True
    assert ended.session_id == outcome.session.session_id


def test_transition_session_completed_is_immutable() -> None:
    outcome = authorize_transition(
        operator_confirmed=True, separate_session=True, purpose="restart"
    )
    assert outcome.session is not None
    with pytest.raises(AttributeError):
        outcome.session.active = False  # type: ignore[misc]


def test_normal_operations_can_never_stop_external_inference() -> None:
    denial = authorize_transition(
        operator_confirmed=False, separate_session=False, purpose="restart"
    )
    assert denial.authorized is False
    assert denial.blockers == denial.reasons
