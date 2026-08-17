"""Research request routing contract (RSCH-002).

Research requests must use the configured model ID and preserve the
server's no-thinking behavior. Client-supplied model choices never reach
the research request: the builder pins the configured model id, and the
verifier rejects any request that deviates from the configured model or
requests thinking.
"""

from __future__ import annotations

from dataclasses import dataclass

from morpheus.core.benchmark import bounded_identifier

_QUERY_LIMIT = 10_000


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    query: str
    model_id: str
    no_thinking: bool = True


@dataclass(frozen=True, slots=True)
class ResearchRoutingDecision:
    accepted: bool
    reasons: tuple[str, ...]


def build_research_request(query: str, *, configured_model_id: str) -> ResearchRequest:
    """Build a research request pinned to the configured model id."""
    bounded_identifier(configured_model_id, "model id")
    normalized = query.strip()
    if not normalized:
        raise ValueError("research query must not be empty")
    if len(normalized) > _QUERY_LIMIT:
        raise ValueError(f"research query must not exceed {_QUERY_LIMIT} characters")
    return ResearchRequest(query=normalized, model_id=configured_model_id, no_thinking=True)


def verify_research_request(
    request: ResearchRequest, *, configured_model_id: str
) -> ResearchRoutingDecision:
    """Verify a research request stays on the configured model with no-thinking."""
    reasons: list[str] = []
    if request.model_id != configured_model_id:
        reasons.append("research request model id differs from the configured model id")
    if not request.no_thinking:
        reasons.append("research request must preserve no-thinking behavior")
    return ResearchRoutingDecision(accepted=not reasons, reasons=tuple(reasons))
