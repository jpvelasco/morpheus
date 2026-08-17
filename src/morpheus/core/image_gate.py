"""Image start GPU safety interlock (IMG-002).

Starting image generation is blocked when configured free-memory,
temperature, process, or ownership checks fail. The interlock is pure:
the GPU policy decision (VOICE-004's GpuHeadroomPolicy), the ownership
decision (IMG-001's owned paths), and a process-ownership observation
are combined into a single typed start decision with every blocker
reported.
"""

from __future__ import annotations

from dataclasses import dataclass

from morpheus.core.gpu_policy import GpuDecision
from morpheus.core.image_paths import ImagePathsDecision


@dataclass(frozen=True, slots=True)
class ImageStartDecision:
    allowed: bool
    blockers: tuple[str, ...]

    @property
    def denied(self) -> bool:
        return not self.allowed


def evaluate_image_start(
    *,
    gpu_decision: GpuDecision,
    process_owned: bool,
    ownership_decision: ImagePathsDecision,
) -> ImageStartDecision:
    """Decide whether image generation may start under every interlock check."""
    blockers: list[str] = []
    if not gpu_decision.allowed:
        blockers.extend(gpu_decision.reasons)
    if not process_owned:
        blockers.append("image generation process ownership check failed")
    if not ownership_decision.accepted:
        blockers.extend(ownership_decision.reasons)
    return ImageStartDecision(allowed=not blockers, blockers=tuple(blockers))
