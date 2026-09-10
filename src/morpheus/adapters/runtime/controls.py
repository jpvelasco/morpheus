"""Fixture-owned control actions confined to ``{data_dir}/runtime/controls``.

These markers never start a real sidecar. They persist a confirmed,
plan-bound action so UI-003 can exercise the same ownership, confirmation,
and audit boundary as OUI-006 workflows.
"""

from __future__ import annotations

from pathlib import Path

from morpheus.core.capabilities import DEFERRED_OPTIONAL_FEATURES
from morpheus.core.durable import write_json_atomic
from morpheus.core.paths import OwnedPathResolver

OWNED_CONTROL_ACTIONS = frozenset({"restart"})
OWNED_MUTABLE_CONTROLS = frozenset({"core", "telemetry", "workflows"})


class OwnedControlError(ValueError):
    """A control action is unknown, deferred, or otherwise not mutable."""


class FixtureControlActions:
    """Write plan-bound control markers under the owned runtime root."""

    def __init__(self, data_dir: Path) -> None:
        self._resolver = OwnedPathResolver(Path(data_dir) / "runtime")

    def apply(self, *, control: str, action: str, plan_id: str) -> Path:
        if control in DEFERRED_OPTIONAL_FEATURES:
            raise OwnedControlError(f"control {control!r} is read-only")
        if control not in OWNED_MUTABLE_CONTROLS:
            raise OwnedControlError(f"unknown control {control!r}")
        if action not in OWNED_CONTROL_ACTIONS:
            raise OwnedControlError(f"unknown control action {action!r}")
        directory = self._resolver.resolve_relative("controls")
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / f"{control}.json"
        write_json_atomic(
            marker,
            {"control": control, "action": action, "plan_id": plan_id},
        )
        return marker
