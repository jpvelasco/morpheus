from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from morpheus.core.health import Evidence, HealthState, aggregate_health

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def evidence(state: HealthState, *, age_seconds: int = 0, ttl_seconds: int = 30) -> Evidence:
    observed_at = NOW - timedelta(seconds=age_seconds)
    return Evidence(
        state=state,
        reason_code=f"test_{state.value}",
        summary="deterministic fixture",
        observed_at=observed_at,
        duration=timedelta(milliseconds=5),
        source="fixture",
        expires_at=observed_at + timedelta(seconds=ttl_seconds),
    )


def test_RUN_002_ready_requires_current_ready_evidence() -> None:
    report = aggregate_health([evidence(HealthState.READY)], now=NOW)
    assert report.state is HealthState.READY
    assert report.stale is False


def test_RUN_002_stale_ready_evidence_becomes_unknown() -> None:
    report = aggregate_health([evidence(HealthState.READY, age_seconds=31)], now=NOW)
    assert report.state is HealthState.UNKNOWN
    assert report.stale is True
    assert report.reason_code == "stale_evidence"


@given(st.lists(st.sampled_from(list(HealthState)), min_size=1, max_size=10))
def test_RUN_002_aggregation_never_reports_ready_with_nonready_child(
    states: list[HealthState],
) -> None:
    report = aggregate_health([evidence(state) for state in states], now=NOW)
    if any(state is not HealthState.READY for state in states):
        assert report.state is not HealthState.READY


def test_RUN_002_partial_dependency_failure_is_degraded() -> None:
    report = aggregate_health(
        [evidence(HealthState.READY), evidence(HealthState.UNREACHABLE)],
        now=NOW,
    )
    assert report.state is HealthState.DEGRADED
