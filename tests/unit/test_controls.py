"""Unit tests: Morpheus-owned feature control ladder (UI-003)."""

from __future__ import annotations

from morpheus.core.controls import (
    ComponentHealth,
    Control,
    ControlState,
    ControlStatus,
    evaluate_controls,
)


def configured(**values: bool) -> dict[Control, bool]:
    return {
        Control.CORE: values.get("core", True),
        Control.SEARCH: values.get("search", False),
        Control.VOICE: values.get("voice", False),
        Control.TELEMETRY: values.get("telemetry", False),
    }


def healthy_core() -> dict[Control, tuple[ComponentHealth, ...]]:
    return {Control.CORE: (ComponentHealth.HEALTHY,)}


def test_core_control_reaches_usable_when_everything_healthy() -> None:
    report = evaluate_controls(
        configured=configured(),
        core_ready=True,
        component_state=healthy_core(),
    )
    status = report[Control.CORE]
    assert status.state is ControlState.USABLE
    assert (status.configured, status.running, status.healthy, status.usable) == (
        True,
        True,
        True,
        True,
    )


def test_core_control_is_healthy_but_not_usable_while_core_gate_open() -> None:
    report = evaluate_controls(
        configured=configured(),
        core_ready=False,
        component_state=healthy_core(),
    )
    status = report[Control.CORE]
    assert status.state is ControlState.HEALTHY
    assert (status.configured, status.running, status.healthy, status.usable) == (
        True,
        True,
        True,
        False,
    )


def test_ladder_never_jumps_a_state() -> None:
    cases = [
        ((), ControlState.CONFIGURED),
        ((ComponentHealth.STARTING,), ControlState.CONFIGURED),
        ((ComponentHealth.UNHEALTHY,), ControlState.RUNNING),
        ((ComponentHealth.HEALTHY,), ControlState.USABLE),
    ]
    for states, expected in cases:
        status = evaluate_controls(
            configured=configured(),
            core_ready=True,
            component_state={Control.CORE: states},
        )[Control.CORE]
        assert status.state is expected, (states, status.state)


def test_disabled_control_is_never_running_or_usable() -> None:
    report = evaluate_controls(
        configured=configured(),
        core_ready=True,
        component_state={Control.SEARCH: (ComponentHealth.HEALTHY,)},
    )
    status = report[Control.SEARCH]
    assert status.state is ControlState.CONFIGURED
    assert (status.configured, status.running, status.healthy, status.usable) == (
        False,
        False,
        False,
        False,
    )


def test_enabled_control_with_missing_component_stays_configured() -> None:
    report = evaluate_controls(
        configured=configured(voice=True),
        core_ready=True,
        component_state=healthy_core(),
    )
    status = report[Control.VOICE]
    assert status.state is ControlState.CONFIGURED
    assert status.running is False
    assert status.blockers == ()


def test_partially_observed_components_are_not_healthy() -> None:
    report = evaluate_controls(
        configured=configured(voice=True),
        core_ready=True,
        component_state={Control.VOICE: (ComponentHealth.HEALTHY, ComponentHealth.STARTING)},
    )
    status = report[Control.VOICE]
    assert status.state is ControlState.RUNNING
    assert status.healthy is False


def test_blockers_are_preserved_verbatim() -> None:
    report = evaluate_controls(
        configured=configured(voice=True),
        core_ready=True,
        component_state={Control.VOICE: (ComponentHealth.UNHEALTHY,)},
        blockers={Control.VOICE: ("component_unhealthy:voice",)},
    )
    assert report[Control.VOICE].blockers == ("component_unhealthy:voice",)


def test_result_is_an_exact_mapping_of_configured_inputs() -> None:
    report = evaluate_controls(
        configured=configured(),
        core_ready=True,
        component_state=healthy_core(),
    )
    assert set(report) == set(configured())
    assert all(isinstance(status, ControlStatus) for status in report.values())
