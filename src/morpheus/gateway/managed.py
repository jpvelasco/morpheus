"""Compose a bounded compat route from the active canonical plan (GATE-001)."""

from __future__ import annotations

from morpheus.core.records import DeploymentPlan
from morpheus.gateway.compat import CompatRoute


def route_for_plan(plan: DeploymentPlan) -> CompatRoute:
    """One managed target derived from the plan's first declared port."""
    port = plan.ports[0]
    managed = f"http://127.0.0.1:{port}"
    aliases = tuple((alias, plan.model.model_id) for alias in plan.served_aliases)
    return CompatRoute(
        mode="managed",
        managed_base_url=managed,
        bypass_base_url=None,
        aliases=aliases,
    )
