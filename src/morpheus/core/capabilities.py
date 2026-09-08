from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    CORE = "core"
    SEARCH = "search"
    VOICE = "voice"
    TELEMETRY = "telemetry"
    WORKFLOWS = "workflows"
    RESEARCH = "research"
    RAG = "rag"
    IMAGE_GENERATION = "image_generation"


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    UNHEALTHY = "unhealthy"
    BLOCKED = "blocked"


# Optional v0.2 services restored to deferred (R8). Public surfaces may
# observe them, but must never advertise them as available/usable.
DEFERRED_OPTIONAL_FEATURES: frozenset[str] = frozenset(
    {
        Capability.SEARCH.value,
        Capability.VOICE.value,
        Capability.RESEARCH.value,
        Capability.RAG.value,
        Capability.IMAGE_GENERATION.value,
    }
)
DEFERRED_SCOPE_BLOCKER = "deferred_optional_scope"


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    capability: Capability
    state: CapabilityState
    blockers: tuple[str, ...] = ()


def evaluate_capabilities(
    *,
    configured: dict[Capability, bool],
    dependency_health: dict[Capability, bool],
    blockers: dict[Capability, tuple[str, ...]],
) -> dict[Capability, CapabilityStatus]:
    result: dict[Capability, CapabilityStatus] = {}
    for capability, enabled in configured.items():
        capability_blockers = blockers.get(capability, ())
        if not enabled:
            state = CapabilityState.DISABLED
        elif capability not in dependency_health:
            state = CapabilityState.BLOCKED
        elif dependency_health[capability]:
            state = CapabilityState.AVAILABLE
        else:
            state = CapabilityState.UNHEALTHY
        result[capability] = CapabilityStatus(capability, state, capability_blockers)
    return result


def withhold_deferred_capability(status: CapabilityStatus) -> CapabilityStatus:
    """Keep deferred optional services off the public available/usable surface."""
    if status.capability.value not in DEFERRED_OPTIONAL_FEATURES:
        return status
    if status.state is CapabilityState.DISABLED:
        return status
    blockers = status.blockers
    if DEFERRED_SCOPE_BLOCKER not in blockers:
        blockers = (DEFERRED_SCOPE_BLOCKER, *blockers)
    state = CapabilityState.BLOCKED if status.state is CapabilityState.AVAILABLE else status.state
    return CapabilityStatus(status.capability, state, blockers)
