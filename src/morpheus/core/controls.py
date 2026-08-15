"""Morpheus-owned feature controls (UI-003).

Controls exist only for Morpheus-owned services and clearly distinguish the
configured, running, healthy, and usable states. The four states form a
strict ladder derived from evidence: a control is *usable* only when it is
configured, its component(s) are observed running, their health checks pass,
and the core runtime is ready. External services (e.g. upstream inference)
are never controls; this module is fed only Morpheus-owned configuration and
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Control(StrEnum):
    CORE = "core"
    SEARCH = "search"
    VOICE = "voice"
    TELEMETRY = "telemetry"
    WORKFLOWS = "workflows"
    RESEARCH = "research"
    RAG = "rag"
    IMAGE_GENERATION = "image_generation"


class ControlState(StrEnum):
    CONFIGURED = "configured"
    RUNNING = "running"
    HEALTHY = "healthy"
    USABLE = "usable"


class ComponentHealth(StrEnum):
    RUNNING = "running"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ControlStatus:
    control: Control
    state: ControlState
    configured: bool
    running: bool
    healthy: bool
    usable: bool
    blockers: tuple[str, ...] = ()


def evaluate_controls(
    *,
    configured: dict[Control, bool],
    core_ready: bool,
    component_state: dict[Control, tuple[ComponentHealth, ...]],
    blockers: dict[Control, tuple[str, ...]] | None = None,
) -> dict[Control, ControlStatus]:
    """Derive the four-state control ladder from configured flags and evidence.

    ``component_state`` maps each enabled control to the observed health of
    every owned component backing it. ``core_ready`` gates the usable state:
    no Morpheus-owned service is *usable* while the core runtime is not ready.
    """
    blockers = blockers or {}
    result: dict[Control, ControlStatus] = {}
    for control, enabled in configured.items():
        states = component_state.get(control, ())
        running = bool(states) and any(
            state in {ComponentHealth.RUNNING, ComponentHealth.HEALTHY, ComponentHealth.UNHEALTHY}
            for state in states
        )
        healthy = bool(states) and all(state is ComponentHealth.HEALTHY for state in states)
        if not enabled:
            state = ControlState.CONFIGURED
            configured_flag, running_flag, healthy_flag, usable = False, False, False, False
        elif not running:
            state = ControlState.CONFIGURED
            configured_flag, running_flag, healthy_flag, usable = True, False, False, False
        elif not healthy:
            state = ControlState.RUNNING
            configured_flag, running_flag, healthy_flag, usable = True, True, False, False
        elif not core_ready:
            state = ControlState.HEALTHY
            configured_flag, running_flag, healthy_flag, usable = True, True, True, False
        else:
            state = ControlState.USABLE
            configured_flag, running_flag, healthy_flag, usable = True, True, True, True
        result[control] = ControlStatus(
            control=control,
            state=state,
            configured=configured_flag,
            running=running_flag,
            healthy=healthy_flag,
            usable=usable,
            blockers=blockers.get(control, ()),
        )
    return result
