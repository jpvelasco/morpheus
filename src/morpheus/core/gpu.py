from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class GpuProcess:
    pid: int
    name: str
    owner: str


@dataclass(frozen=True, slots=True)
class GpuObservation:
    total_mib: int
    used_mib: int
    temperature_c: int
    processes: tuple[GpuProcess, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("GPU observation timestamp must be timezone-aware")
        if self.total_mib <= 0 or not 0 <= self.used_mib <= self.total_mib:
            raise ValueError("GPU memory observation is invalid")

    @property
    def free_mib(self) -> int:
        return self.total_mib - self.used_mib


@dataclass(frozen=True, slots=True)
class GpuDecision:
    allowed: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GpuPolicy:
    min_free_mib: int
    max_temperature_c: int
    max_observation_age: timedelta = timedelta(seconds=30)

    def evaluate(self, observation: GpuObservation, *, now: datetime) -> GpuDecision:
        if now.tzinfo is None:
            raise ValueError("policy evaluation time must be timezone-aware")
        blockers: list[str] = []
        if now - observation.observed_at > self.max_observation_age:
            blockers.append("gpu_observation_stale")
        if observation.free_mib < self.min_free_mib:
            blockers.append("insufficient_free_memory")
        if observation.temperature_c > self.max_temperature_c:
            blockers.append("gpu_temperature_high")
        if any(process.owner != "morpheus" for process in observation.processes):
            blockers.append("external_gpu_process")
        return GpuDecision(allowed=not blockers, blockers=tuple(blockers))


class TransitionState(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PREFLIGHT = "preflight"
    INFERENCE_STOPPED = "inference_stopped"
    IMAGE_READY = "image_ready"
    RESTORING = "restoring"
    COMPLETE = "complete"
    RECOVERY_REQUIRED = "recovery_required"


_TRANSITIONS = {
    TransitionState.PREFLIGHT: TransitionState.INFERENCE_STOPPED,
    TransitionState.INFERENCE_STOPPED: TransitionState.IMAGE_READY,
    TransitionState.IMAGE_READY: TransitionState.RESTORING,
    TransitionState.RESTORING: TransitionState.COMPLETE,
}


@dataclass(frozen=True, slots=True)
class GpuTransition:
    baseline_id: str
    state: TransitionState
    confirmation_phrase: str
    error_code: str | None = None

    @classmethod
    def new(cls, *, baseline_id: str) -> GpuTransition:
        if not baseline_id:
            raise ValueError("a captured inference baseline is required")
        return cls(
            baseline_id=baseline_id,
            state=TransitionState.AWAITING_CONFIRMATION,
            confirmation_phrase=f"STOP INFERENCE FOR IMAGE {baseline_id}",
        )

    def confirm(self, supplied_phrase: str) -> GpuTransition:
        if self.state is not TransitionState.AWAITING_CONFIRMATION:
            raise ValueError("transition is not awaiting confirmation")
        if supplied_phrase != self.confirmation_phrase:
            return replace(self, error_code="confirmation_mismatch")
        return replace(self, state=TransitionState.PREFLIGHT, error_code=None)

    def advance(self, target: TransitionState) -> GpuTransition:
        if _TRANSITIONS.get(self.state) is not target:
            raise ValueError(f"invalid GPU transition from {self.state} to {target}")
        return replace(self, state=target, error_code=None)

    def fail(self, error_code: str) -> GpuTransition:
        if self.state in {TransitionState.COMPLETE, TransitionState.RECOVERY_REQUIRED}:
            raise ValueError("terminal transition cannot fail again")
        return replace(self, state=TransitionState.RECOVERY_REQUIRED, error_code=error_code)
