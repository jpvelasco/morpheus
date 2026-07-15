from __future__ import annotations

from datetime import UTC, datetime, timedelta

from morpheus.core.gpu import GpuObservation, GpuPolicy, GpuProcess, GpuTransition, TransitionState

NOW = datetime(2026, 7, 15, tzinfo=UTC)


def observation(
    *,
    free_mib: int = 20_000,
    temperature_c: int = 40,
    processes: tuple[GpuProcess, ...] = (),
    observed_at: datetime = NOW,
) -> GpuObservation:
    return GpuObservation(
        total_mib=32_607,
        used_mib=32_607 - free_mib,
        temperature_c=temperature_c,
        processes=processes,
        observed_at=observed_at,
    )


def test_IMG_002_allows_only_fresh_headroom_without_foreign_processes() -> None:
    decision = GpuPolicy(min_free_mib=16_000, max_temperature_c=75).evaluate(observation(), now=NOW)
    assert decision.allowed is True
    assert decision.blockers == ()


def test_IMG_002_rejects_current_inference_coexistence() -> None:
    process = GpuProcess(pid=123, name="VLLM::EngineCore", owner="external")
    decision = GpuPolicy(min_free_mib=16_000, max_temperature_c=75).evaluate(
        observation(free_mib=831, processes=(process,)), now=NOW
    )
    assert decision.allowed is False
    assert "insufficient_free_memory" in decision.blockers
    assert "external_gpu_process" in decision.blockers


def test_IMG_002_rejects_hot_or_stale_observation() -> None:
    policy = GpuPolicy(min_free_mib=16_000, max_temperature_c=75)
    decision = policy.evaluate(
        observation(temperature_c=80, observed_at=NOW - timedelta(seconds=31)), now=NOW
    )
    assert decision.blockers == ("gpu_observation_stale", "gpu_temperature_high")


def test_IMG_003_transition_requires_exact_confirmation_and_valid_edges() -> None:
    transition = GpuTransition.new(baseline_id="baseline-123")
    rejected = transition.confirm("wrong")
    assert rejected.state is TransitionState.AWAITING_CONFIRMATION
    assert rejected.error_code == "confirmation_mismatch"

    confirmed = transition.confirm(transition.confirmation_phrase)
    assert confirmed.state is TransitionState.PREFLIGHT
    image_ready = confirmed.advance(TransitionState.INFERENCE_STOPPED).advance(
        TransitionState.IMAGE_READY
    )
    restored = image_ready.advance(TransitionState.RESTORING).advance(TransitionState.COMPLETE)
    assert restored.state is TransitionState.COMPLETE


def test_IMG_004_failure_stops_with_recovery_state_and_baseline() -> None:
    transition = GpuTransition.new(baseline_id="baseline-123")
    failed = transition.confirm(transition.confirmation_phrase).fail("comfy_start_failed")
    assert failed.state is TransitionState.RECOVERY_REQUIRED
    assert failed.baseline_id == "baseline-123"
    assert failed.error_code == "comfy_start_failed"
