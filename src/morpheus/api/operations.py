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
    "benchmarks": {"schema": "benchmarks", "version": 1},
    "analytics": {"schema": "analytics", "version": 1},
    "logs_events": {"schema": "events", "version": 1},
    "diagnostics": {"schema": "diagnostics", "version": 1},
    "settings": {"schema": "settings", "version": 1},
    "recovery": {"schema": "recovery", "version": 1},
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
    data_states: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the versioned workspace navigation manifest.

    ``discovered`` is None when model discovery failed, an empty list when it
    succeeded with no models, and a list of models otherwise; each maps to an
    unavailable, partial, or ready models workspace.  ``data_states`` reports
    whether the history-backed workspaces (benchmarks, analytics, logs and
    events) hold recorded evidence.
    """
    host_available = host.get("status") in {"available", "degraded"}
    models_state = "unavailable" if discovered is None else "ready" if discovered else "partial"
    data_states = data_states or {}
    workspaces = [
        {
            "id": workspace_id,
            "label": label,
            "state": _workspace_state(
                workspace_id,
                host_available=host_available,
                models_state=models_state,
                data_state=data_states.get(workspace_id, "empty"),
            ),
            "query_model": QUERY_MODELS.get(workspace_id),
        }
        for workspace_id, label in WORKSPACES
    ]
    return {"schema_version": 1, "observed_at": observed_at, "workspaces": workspaces}


def _workspace_state(
    workspace_id: str,
    *,
    host_available: bool,
    models_state: str,
    data_state: str = "empty",
) -> str:
    if workspace_id in {"overview", "diagnostics"}:
        return "ready"
    if workspace_id in {"hardware", "runtime"}:
        return "partial" if host_available else "unavailable"
    if workspace_id == "models":
        return models_state
    if workspace_id in {"benchmarks", "analytics", "logs_events"}:
        return data_state
    if workspace_id in {"settings", "recovery"}:
        return data_state
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


def metrics_payload(
    *,
    observed_at: str,
    signal: str,
    unit: str,
    freshness: dict[str, Any],
    sources: Sequence[tuple[str, str, str | None]],
    buckets: Sequence[Any],
    gaps: Sequence[tuple[str, str]],
    sample_count: int,
) -> dict[str, Any]:
    """Versioned metrics trend payload with explicit units, freshness, and gaps."""
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "signal": signal,
        "unit": unit,
        "freshness": freshness,
        "sources": [
            {"source": name, "state": state, "reason": reason} for name, state, reason in sources
        ],
        "buckets": [
            {
                "start": bucket.start,
                "end": bucket.end,
                "count": bucket.count,
                "min": bucket.min,
                "max": bucket.max,
                "mean": bucket.mean,
                "p50": bucket.p50,
                "p95": bucket.p95,
            }
            for bucket in buckets
        ],
        "gaps": [{"start": start, "end": end} for start, end in gaps],
        "sample_count": sample_count,
    }


def events_payload(
    *,
    observed_at: str,
    events: Sequence[Any],
) -> dict[str, Any]:
    """Versioned events payload; messages are redacted before persistence."""
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "count": len(events),
        "events": [
            {
                "recorded_at": event.recorded_at,
                "source": event.source,
                "severity": event.severity,
                "message": event.message,
                "correlation_id": event.correlation_id,
                "deployment_id": event.deployment_id,
                "campaign_id": event.campaign_id,
            }
            for event in events
        ],
    }


def benchmarks_payload(
    *,
    observed_at: str,
    runs: Sequence[Any],
) -> dict[str, Any]:
    """Versioned benchmark history payload (most recent first)."""
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "count": len(runs),
        "runs": [run.to_dict() for run in runs],
    }


def analytics_payload(
    *,
    observed_at: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Versioned analytics payload with usage, scorecards, comparisons, regressions."""
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "usage": report["usage"],
        "scorecards": report["scorecards"],
        "comparisons": report["comparisons"],
        "regressions": report["regressions"],
    }


def settings_payload(
    *,
    observed_at: str,
    entries: Sequence[dict[str, Any]],
    journal: dict[str, Any] | None,
) -> dict[str, Any]:
    """Versioned settings catalog with journal state; secrets stay redacted."""
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "settings": list(entries),
        "restart_required": True,
        "journal": journal or {"applied_at": None, "applied": [], "rollback_available": False},
    }


def workflows_payload(
    *,
    observed_at: str,
    definitions: Sequence[Any],
    sessions: Sequence[dict[str, Any]],
    audit_events: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Versioned workflows payload: definitions, recorded operations, audit trail."""
    return {
        "schema_version": 1,
        "observed_at": observed_at,
        "workflows": [
            {
                "workflow_id": definition.workflow_id.value,
                "label": definition.label,
                "description": definition.description,
                "steps": [
                    {
                        "id": step.id,
                        "label": step.label,
                        "description": step.description,
                        "preflight": step.preflight,
                        "recovery": step.recovery,
                        "confirm_required": step.confirm_required,
                    }
                    for step in definition.steps
                ],
            }
            for definition in definitions
        ],
        "sessions": list(sessions),
        "audit_events": list(audit_events),
    }
