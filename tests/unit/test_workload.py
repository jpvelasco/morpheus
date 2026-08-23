"""Unit tests for workload profiles and operator constraints (SEL-003)."""

import pytest

from morpheus.core.workload import (
    SEED_PROFILES,
    WEIGHT_METRICS,
    OperatorConstraints,
    WorkloadError,
    WorkloadPolicy,
    monotonic_budget_holds,
    normalize_weights,
)


class TestNormalizeWeights:
    def test_scales_to_unit_sum(self) -> None:
        normalized = normalize_weights((("tool_use", 2.0), ("stability", 2.0)))
        assert normalized == (("tool_use", 0.5), ("stability", 0.5))

    def test_drops_zero_weight_metrics(self) -> None:
        normalized = normalize_weights((("tool_use", 1.0), ("stability", 0.0)))
        assert normalized == (("tool_use", 1.0),)

    def test_rejects_all_zero(self) -> None:
        with pytest.raises(WorkloadError):
            normalize_weights((("tool_use", 0.0), ("stability", 0.0)))

    def test_rejects_negative_weight(self) -> None:
        with pytest.raises(WorkloadError):
            normalize_weights((("tool_use", -1.0),))


class TestWorkloadProfile:
    def test_seed_profiles_have_known_metrics(self) -> None:
        for profile in SEED_PROFILES:
            assert all(metric in WEIGHT_METRICS for metric, _ in profile.weights)

    def test_round_trip(self) -> None:
        profile = SEED_PROFILES[0]
        assert WorkloadPolicy.from_dict(profile.to_dict()) == profile

    def test_round_trip_rejects_bad_weights(self) -> None:
        payload = SEED_PROFILES[0].to_dict()
        payload["weights"] = [["unknown_metric", 1.0]]
        with pytest.raises(WorkloadError):
            WorkloadPolicy.from_dict(payload)

    def test_rejects_blank_id(self) -> None:
        with pytest.raises(WorkloadError):
            WorkloadPolicy(id="", version="1", name="x", weights=(("tool_use", 1.0),))

    def test_rejects_whitespace_id(self) -> None:
        with pytest.raises(WorkloadError):
            WorkloadPolicy(
                id="dev default",
                version="1",
                name="x",
                weights=(("tool_use", 1.0),),
            )

    def test_rejects_zero_context(self) -> None:
        with pytest.raises(WorkloadError):
            WorkloadPolicy(
                id="dev",
                version="1",
                name="x",
                weights=(("tool_use", 1.0),),
                context_tokens=0,
            )

    def test_weight_lookup_unknown_metric_is_zero(self) -> None:
        assert SEED_PROFILES[0].weight("unknown_metric") == 0.0

    def test_weight_lookup_normalized(self) -> None:
        profile = WorkloadPolicy(
            id="dev",
            version="1",
            name="x",
            weights=(("tool_use", 2.0), ("stability", 2.0)),
        )
        assert profile.weight("tool_use") == pytest.approx(0.5)

    def test_same_inputs_same_profile(self) -> None:
        first = SEED_PROFILES[1].to_dict()
        second = WorkloadPolicy.from_dict(first).to_dict()
        assert first == second


class TestOperatorConstraints:
    def test_rejects_negative_cap(self) -> None:
        with pytest.raises(WorkloadError):
            OperatorConstraints(max_ram_bytes=-1)

    def test_rejects_zero_cap(self) -> None:
        with pytest.raises(WorkloadError):
            OperatorConstraints(max_context=0)

    def test_round_trip(self) -> None:
        constraints = OperatorConstraints(
            max_context=4096,
            allowed_engines=("llama.cpp",),
            max_vram_bytes=8_589_934_592,
        )
        assert OperatorConstraints(**constraints.to_dict()) == constraints

    def test_defaults_are_unrestricted(self) -> None:
        assert OperatorConstraints().to_dict() == {
            "max_context": None,
            "max_concurrency": None,
            "allowed_engines": (),
            "allowed_quantizations": (),
            "max_ram_bytes": None,
            "max_vram_bytes": None,
            "max_storage_bytes": None,
        }


class TestMonotonicBudget:
    def test_larger_covers_smaller(self) -> None:
        assert monotonic_budget_holds(
            (("ram", 8), ("vram", 4)),
            (("ram", 16), ("vram", 8), ("storage", 100)),
        )

    def test_missing_dimension_counts_zero(self) -> None:
        assert not monotonic_budget_holds(
            (("vram", 16),),
            (("ram", 64),),
        )

    def test_not_monotonic(self) -> None:
        assert not monotonic_budget_holds(
            (("ram", 64),),
            (("ram", 32),),
        )
