"""Explicit transition authorization policy (IMG-003).

Any action that would stop or restart external inference is outside normal
Morpheus ownership. It requires an operator-run, separately authorized
transition workflow: a transition session exists only after the operator
confirms the action in a separate session, and normal operations can never
obtain that authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

EXTERNAL_INFERENCE_NOTE = (
    "stopping or restarting external inference is outside normal Morpheus "
    "ownership and requires an operator-run, separately authorized transition"
)


@dataclass(frozen=True, slots=True)
class TransitionSession:
    session_id: str
    purpose: str
    active: bool = True

    @property
    def completed(self) -> bool:
        return not self.active

    def end(self) -> TransitionSession:
        return replace(self, active=False)


@dataclass(frozen=True, slots=True)
class TransitionAuthorization:
    authorized: bool
    reasons: tuple[str, ...]
    session: TransitionSession | None = None

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reasons if not self.authorized else ()


def authorize_transition(
    *,
    operator_confirmed: bool,
    separate_session: bool,
    purpose: str,
) -> TransitionAuthorization:
    """Authorize a transition only with operator confirmation in a separate session."""
    if not purpose.strip():
        raise ValueError("transition purpose must not be empty")
    if not operator_confirmed or not separate_session:
        return TransitionAuthorization(
            authorized=False,
            reasons=(EXTERNAL_INFERENCE_NOTE,),
        )
    return TransitionAuthorization(
        authorized=True,
        reasons=(),
        session=TransitionSession(session_id=uuid4().hex, purpose=purpose.strip()),
    )
