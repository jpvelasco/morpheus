from __future__ import annotations

import pytest

from morpheus.adapters.runtime.controls import FixtureControlActions, OwnedControlError


def test_owned_restart_writes_plan_bound_marker(tmp_path) -> None:
    actions = FixtureControlActions(tmp_path)
    marker = actions.apply(control="telemetry", action="restart", plan_id="plan-r3-owned")
    assert marker.is_relative_to(tmp_path / "runtime")
    assert "plan-r3-owned" in marker.read_text(encoding="utf-8")


def test_deferred_and_unknown_controls_are_refused(tmp_path) -> None:
    actions = FixtureControlActions(tmp_path)
    with pytest.raises(OwnedControlError, match="read-only"):
        actions.apply(control="search", action="restart", plan_id="plan-r3-owned")
    with pytest.raises(OwnedControlError, match="unknown control"):
        actions.apply(control="not-a-control", action="restart", plan_id="plan-r3-owned")
    with pytest.raises(OwnedControlError, match="unknown control action"):
        actions.apply(control="telemetry", action="wipe", plan_id="plan-r3-owned")
    assert not (tmp_path / "runtime" / "controls").exists()
