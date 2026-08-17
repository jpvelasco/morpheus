"""GPU opt-in and headroom resource policy (VOICE-004, IMG-002).

GPU acceleration is never assumed: it is opt-in, and any GPU use is
rejected when it would violate the configured headroom policy. The policy is
pure and dependency-free; live memory and temperature observations are
supplied by callers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GpuDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()

    @property
    def denied(self) -> bool:
        return not self.allowed


@dataclass(frozen=True, slots=True)
class GpuHeadroomPolicy:
    enabled: bool
    required_free_mib: int
    max_temperature_c: float | None = None

    def __post_init__(self) -> None:
        if self.required_free_mib < 0:
            raise ValueError("gpu headroom must be non-negative")
        if self.max_temperature_c is not None and self.max_temperature_c <= 0:
            raise ValueError("gpu temperature ceiling must be positive")


def evaluate_gpu_use(
    policy: GpuHeadroomPolicy,
    *,
    requested_mib: int,
    free_mib: int,
    temperature_c: float | None = None,
) -> GpuDecision:
    """Decide whether GPU use is allowed under the headroom policy."""
    if requested_mib <= 0:
        raise ValueError("requested GPU memory must be positive")
    if free_mib < 0:
        raise ValueError("observed free GPU memory must be non-negative")
    if not policy.enabled:
        return GpuDecision(allowed=False, reasons=("gpu acceleration is not opted in",))
    reasons: list[str] = []
    if requested_mib + policy.required_free_mib > free_mib:
        reasons.append("insufficient free GPU memory for the configured headroom")
    if (
        policy.max_temperature_c is not None
        and temperature_c is not None
        and temperature_c > policy.max_temperature_c
    ):
        reasons.append("GPU temperature exceeds the configured ceiling")
    return GpuDecision(allowed=not reasons, reasons=tuple(reasons))
