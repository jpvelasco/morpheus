from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class HealthState(StrEnum):
    UNKNOWN = "unknown"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class Evidence:
    state: HealthState
    reason_code: str
    summary: str
    observed_at: datetime
    duration: timedelta
    source: str
    expires_at: datetime
    next_action: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        if self.duration < timedelta(0):
            raise ValueError("probe duration cannot be negative")
        if self.expires_at < self.observed_at:
            raise ValueError("evidence expiry cannot precede observation")

    def is_stale(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise ValueError("current time must be timezone-aware")
        return now > self.expires_at


@dataclass(frozen=True, slots=True)
class HealthReport:
    state: HealthState
    reason_code: str
    summary: str
    evidence: tuple[Evidence, ...]
    stale: bool


def _aggregate_current(states: set[HealthState]) -> HealthState:
    if states == {HealthState.READY}:
        return HealthState.READY
    if states == {HealthState.UNREACHABLE}:
        return HealthState.UNREACHABLE
    if states == {HealthState.STARTING}:
        return HealthState.STARTING
    if states == {HealthState.INCOMPATIBLE}:
        return HealthState.INCOMPATIBLE
    if states == {HealthState.UNKNOWN}:
        return HealthState.UNKNOWN
    return HealthState.DEGRADED


def aggregate_health(evidence: list[Evidence], *, now: datetime) -> HealthReport:
    current = tuple(item for item in evidence if not item.is_stale(now))
    stale = len(current) != len(evidence)
    if not current:
        return HealthReport(
            state=HealthState.UNKNOWN,
            reason_code="stale_evidence" if evidence else "no_evidence",
            summary="Health evidence is stale" if evidence else "No health evidence is available",
            evidence=tuple(evidence),
            stale=stale,
        )

    state = _aggregate_current({item.state for item in current})
    if stale and state is HealthState.READY:
        state = HealthState.DEGRADED
    return HealthReport(
        state=state,
        reason_code="partial_stale_evidence" if stale else f"aggregate_{state.value}",
        summary="One or more health checks require attention"
        if state is not HealthState.READY
        else "All health checks are ready",
        evidence=tuple(evidence),
        stale=stale,
    )
