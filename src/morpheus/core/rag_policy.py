"""RAG explicit-need policy (RAG-001).

Qdrant or a separate embedding server is never enabled by default because
Open WebUI already maintains local vector state. Enabling Morpheus RAG
requires an explicit operator-confirmed need; without it the enablement is
denied with a typed blocker.
"""

from __future__ import annotations

from dataclasses import dataclass

RAG_DEFAULT_OFF_NOTE = (
    "Open WebUI already maintains local vector state; enabling Morpheus RAG "
    "requires an explicit, operator-confirmed need"
)


@dataclass(frozen=True, slots=True)
class RagEnablementDecision:
    enabled: bool
    explicit_need_confirmed: bool
    accepted: bool
    reasons: tuple[str, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.reasons if not self.accepted else ()


def evaluate_rag_enablement(
    *, enabled: bool, explicit_need_confirmed: bool = False
) -> RagEnablementDecision:
    """Evaluate the explicit-need policy for a requested RAG enablement."""
    if not enabled:
        return RagEnablementDecision(
            enabled=False,
            explicit_need_confirmed=explicit_need_confirmed,
            accepted=True,
            reasons=(),
        )
    if not explicit_need_confirmed:
        return RagEnablementDecision(
            enabled=True,
            explicit_need_confirmed=False,
            accepted=False,
            reasons=(RAG_DEFAULT_OFF_NOTE,),
        )
    return RagEnablementDecision(
        enabled=True,
        explicit_need_confirmed=True,
        accepted=True,
        reasons=(),
    )
