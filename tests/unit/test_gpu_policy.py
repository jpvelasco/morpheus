"""Unit tests: GPU opt-in and headroom resource policy (VOICE-004)."""

from __future__ import annotations

import pytest

from morpheus.core.gpu_policy import (
    GpuHeadroomPolicy,
    evaluate_gpu_use,
)

ENABLED = GpuHeadroomPolicy(
    enabled=True,
    required_free_mib=4096,
    max_temperature_c=80,
)


def test_gpu_use_is_denied_when_acceleration_is_not_opted_in() -> None:
    policy = GpuHeadroomPolicy(enabled=False, required_free_mib=4096)
    decision = evaluate_gpu_use(
        policy,
        requested_mib=1024,
        free_mib=100_000,
        temperature_c=50,
    )
    assert decision.allowed is False
    assert any("opt" in reason for reason in decision.reasons)


def test_gpu_use_allowed_within_headroom() -> None:
    decision = evaluate_gpu_use(
        ENABLED,
        requested_mib=4096,
        free_mib=32_768,
        temperature_c=60,
    )
    assert decision.allowed is True
    assert decision.reasons == ()


def test_gpu_use_denied_when_headroom_would_be_violated() -> None:
    decision = evaluate_gpu_use(
        ENABLED,
        requested_mib=30_000,
        free_mib=32_768,
        temperature_c=60,
    )
    assert decision.allowed is False
    assert any("memory" in reason for reason in decision.reasons)


def test_gpu_use_denied_when_temperature_exceeds_ceiling() -> None:
    decision = evaluate_gpu_use(
        ENABLED,
        requested_mib=1024,
        free_mib=100_000,
        temperature_c=81,
    )
    assert decision.allowed is False
    assert any("temperature" in reason for reason in decision.reasons)


def test_gpu_use_allows_unknown_temperature() -> None:
    decision = evaluate_gpu_use(
        ENABLED,
        requested_mib=1024,
        free_mib=100_000,
        temperature_c=None,
    )
    assert decision.allowed is True


def test_gpu_use_denies_zero_or_negative_request() -> None:
    with pytest.raises(ValueError, match="requested"):
        evaluate_gpu_use(ENABLED, requested_mib=0, free_mib=100_000)
    with pytest.raises(ValueError, match="requested"):
        evaluate_gpu_use(ENABLED, requested_mib=-1, free_mib=100_000)


def test_gpu_use_denies_negative_free_memory_observation() -> None:
    with pytest.raises(ValueError, match="free"):
        evaluate_gpu_use(ENABLED, requested_mib=1024, free_mib=-1)


def test_headroom_policy_rejects_negative_headroom() -> None:
    with pytest.raises(ValueError, match="headroom"):
        GpuHeadroomPolicy(enabled=True, required_free_mib=-1)


def test_headroom_policy_rejects_non_positive_temperature_ceiling() -> None:
    with pytest.raises(ValueError, match="temperature"):
        GpuHeadroomPolicy(enabled=True, required_free_mib=4096, max_temperature_c=0)
