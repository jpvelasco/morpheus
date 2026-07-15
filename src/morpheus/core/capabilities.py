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
