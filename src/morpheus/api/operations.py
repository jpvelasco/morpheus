"""Operations workspace and control contracts (OUI-001, UI-003).

The navigation manifest lists the operator workspaces and the versioned
query model each exposes.  The controls payload applies the four-state
control ladder to Morpheus-owned services only; external inference is
evidence for the core control, never a control itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from morpheus.config import MorpheusSettings
from morpheus.core.controls import ComponentHealth, Control, evaluate_controls
from morpheus.core.health import Evidence, HealthState

WORKSPACES: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("hardware", "Hardware"),
    ("models", "Models"),
    ("engines", "Engines"),
    ("runtime", "Runtime"),
    ("benchmarks", "Benchmarks"),
    ("analytics", "Analytics"),
    ("logs_events", "Logs & Events"),
    ("diagnostics", "Diagnostics"),
    ("settings", "Settings"),
    ("recovery", "Recovery"),
)

QUERY_MODELS: dict[str, dict[str, str | int]] = {
    "overview": {"schema": "overview", "version": 1},
    "hardware": {"schema": "host", "version": 1},
    "models": {"schema": "models", "version": 1},
    "runtime": {"schema": "runtime", "version": 1},
    "diagnostics": {"schema": "diagnostics", "version": 1},
}

#: Owned container components backing each optional feature control.
COMPONENT_MAPPING: dict[str, tuple[str, ...]] = {
    "search": ("search",),
    # The gateway is the voice control's public contract; an operator must
    # configure a Docker health check before it can be reported running.
    "voice": ("voice-gateway",),
    "telemetry": ("telemetry",),
    "workflows": ("workflows",),
    "research": ("research",),
    "image_generation": ("image",),
}


def observed_component_health(
    *,
    components: tuple[str, ...],
    service_evidence: dict[str, Any],
) -> tuple[tuple[ComponentHealth, ...], tuple[str, ...]]:
    """Map owned-container evidence to per-component health observations.

    A component with no matching container is observed as UNAVAILABLE and a
    pending or unknown health check as STARTING, so callers can distinguish
    verified health from unverified evidence without stringly checks.
    """
    if service_evidence.get("status") != "available":
        reason = str(service_evidence.get("reason", "runtime_agent_service_evidence_unavailable"))
        return (), (reason,)
    services = service_evidence.get("services")
    if not isinstance(services, list):
        return (), ("runtime_agent_service_evidence_invalid",)
    by_component: dict[str, list[dict[str, Any]]] = {}
    for service in services:
        if isinstance(service, dict) and isinstance(service.get("component"), str):
            by_component.setdefault(service["component"], []).append(service)
    observed: list[ComponentHealth] = []
    blockers: list[str] = []
    for component in components:
        matching = by_component.get(component, [])
        if not matching:
            observed.append(ComponentHealth.UNAVAILABLE)
            blockers.append(f"component_not_running:{component}")
            continue
        for service in matching:
            health = service.get("health")
            if health == "healthy":
                observed.append(ComponentHealth.HEALTHY)
            elif health == "unhealthy":
                observed.append(ComponentHealth.UNHEALTHY)
                blockers.append(f"component_unhealthy:{component}")
            elif health == "starting":
                observed.append(ComponentHealth.STARTING)
                blockers.append(f"component_health_pending:{component}")
            else:
                observed.append(ComponentHealth.STARTING)
                blockers.append(f"component_health_unavailable:{component}")
    return tuple(observed), tuple(dict.fromkeys(blockers))


def navigation_payload(
    *,
    discovered: Sequence[Any] | None,
    host: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Build the versioned workspace navigation manifest.

    ``discovered`` is None when model discovery failed, an empty list when it
    succeeded with no models, and a list of models otherwise; each maps to an
    unavailable, partial, or ready models workspace.
    """
    host_available = host.get("status") in {"available", "degraded"}
    models_state = "unavailable" if discovered is None else "ready" if discovered else "partial"
    workspaces = [
        {
            "id": workspace_id,
            "label": label,
            "state": _workspace_state(
                workspace_id,
                host_available=host_available,
                models_state=models_state,
            ),
            "query_model": QUERY_MODELS.get(workspace_id),
        }
        for workspace_id, label in WORKSPACES
    ]
    return {"schema_version": 1, "observed_at": observed_at, "workspaces": workspaces}


def _workspace_state(workspace_id: str, *, host_available: bool, models_state: str) -> str:
    if workspace_id in {"overview", "diagnostics"}:
        return "ready"
    if workspace_id in {"hardware", "runtime"}:
        return "partial" if host_available else "unavailable"
    if workspace_id == "models":
        return models_state
    return "empty"


def controls_payload(
    *,
    settings: MorpheusSettings,
    evidence: Evidence,
    service_evidence: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Apply the control ladder to the configured Morpheus-owned services."""
    configured: dict[Control, bool] = {
        Control.CORE: True,
        **{Control(name): enabled for name, enabled in settings.features().items()},
    }
    core_ready = evidence.state is HealthState.READY
    component_state: dict[Control, tuple[ComponentHealth, ...]] = {}
    blockers: dict[Control, tuple[str, ...]] = {}
    if evidence.state is HealthState.READY:
        component_state[Control.CORE] = (ComponentHealth.HEALTHY,)
    elif evidence.state is HealthState.DEGRADED:
        component_state[Control.CORE] = (ComponentHealth.UNHEALTHY,)
        blockers[Control.CORE] = (evidence.reason_code,)
    else:
        component_state[Control.CORE] = (ComponentHealth.UNAVAILABLE,)
        blockers[Control.CORE] = (evidence.reason_code,)
    for control, enabled in configured.items():
        if control is Control.CORE or not enabled:
            continue
        components = COMPONENT_MAPPING.get(control.value)
        if not components:
            blockers[control] = ("dependency_mapping_not_configured",)
            continue
        observed, component_blockers = observed_component_health(
            components=components,
            service_evidence=service_evidence,
        )
        if observed:
            component_state[control] = observed
        if component_blockers:
            blockers[control] = component_blockers
    report = evaluate_controls(
        configured=configured,
        core_ready=core_ready,
        component_state=component_state,
        blockers=blockers,
    )
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "core_ready": core_ready,
        "controls": [
            {
                "control": status.control.value,
                "state": status.state.value,
                "configured": status.configured,
                "running": status.running,
                "healthy": status.healthy,
                "usable": status.usable,
                "blockers": list(status.blockers),
            }
            for status in report.values()
        ],
    }
