"""Unit tests: image start GPU safety interlock (IMG-002)."""

from __future__ import annotations

from morpheus.core.gpu_policy import GpuHeadroomPolicy, evaluate_gpu_use
from morpheus.core.image_gate import evaluate_image_start
from morpheus.core.image_paths import ImagePathsDecision


def _allowed_gpu() -> object:
    return evaluate_gpu_use(
        GpuHeadroomPolicy(enabled=True, required_free_mib=1024),
        requested_mib=4096,
        free_mib=16_384,
    )


def _denied_gpu() -> object:
    return evaluate_gpu_use(
        GpuHeadroomPolicy(enabled=True, required_free_mib=16_384),
        requested_mib=4096,
        free_mib=8192,
    )


def _owned_paths() -> ImagePathsDecision:
    return ImagePathsDecision(accepted=True, reasons=())


def test_evaluate_image_start_allows_when_every_check_passes() -> None:
    decision = evaluate_image_start(
        gpu_decision=_allowed_gpu(),
        process_owned=True,
        ownership_decision=_owned_paths(),
    )
    assert decision.allowed is True
    assert decision.blockers == ()


def test_evaluate_image_start_blocks_on_gpu_denial() -> None:
    decision = evaluate_image_start(
        gpu_decision=_denied_gpu(),
        process_owned=True,
        ownership_decision=_owned_paths(),
    )
    assert decision.allowed is False
    assert any("GPU" in blocker for blocker in decision.blockers)


def test_evaluate_image_start_blocks_on_foreign_process() -> None:
    decision = evaluate_image_start(
        gpu_decision=_allowed_gpu(),
        process_owned=False,
        ownership_decision=_owned_paths(),
    )
    assert decision.allowed is False
    assert any("process" in blocker for blocker in decision.blockers)


def test_evaluate_image_start_blocks_on_unowned_paths() -> None:
    decision = evaluate_image_start(
        gpu_decision=_allowed_gpu(),
        process_owned=True,
        ownership_decision=ImagePathsDecision(
            accepted=False,
            reasons=("ComfyUI models root must be a Morpheus-owned path",),
        ),
    )
    assert decision.allowed is False
    assert any("owned path" in blocker for blocker in decision.blockers)


def test_evaluate_image_start_aggregates_every_failed_check() -> None:
    decision = evaluate_image_start(
        gpu_decision=_denied_gpu(),
        process_owned=False,
        ownership_decision=ImagePathsDecision(
            accepted=False,
            reasons=("ComfyUI models root must be a Morpheus-owned path",),
        ),
    )
    assert decision.allowed is False
    assert len(decision.blockers) >= 3
    kinds = " ".join(decision.blockers).lower()
    assert "gpu" in kinds and "process" in kinds and "owned path" in kinds


def test_evaluate_image_start_temperature_denial_is_aggregated() -> None:
    gpu_decision = evaluate_gpu_use(
        GpuHeadroomPolicy(enabled=True, required_free_mib=1024, max_temperature_c=80.0),
        requested_mib=4096,
        free_mib=16_384,
        temperature_c=95.0,
    )
    decision = evaluate_image_start(
        gpu_decision=gpu_decision,
        process_owned=True,
        ownership_decision=_owned_paths(),
    )
    assert decision.allowed is False
    assert any("temperature" in blocker for blocker in decision.blockers)


def test_evaluate_image_start_allows_denied_decision_is_typed() -> None:
    decision = evaluate_image_start(
        gpu_decision=_denied_gpu(),
        process_owned=True,
        ownership_decision=_owned_paths(),
    )
    assert isinstance(decision.blockers, tuple)
    assert decision.denied is True
