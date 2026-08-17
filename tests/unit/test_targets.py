"""Unit tests: frozen target/support matrix (HOST-003, PLAT-004).

The frozen matrix declares the exact supported targets and their
qualification claims; every declared claim maps to an exact artifact,
machine, lane, and rollback path, and nothing outside the registry is
ever advertised.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from morpheus.core.support_matrix import SupportDimension
from morpheus.core.targets import (
    FROZEN_TARGETS,
    ArtifactKind,
    Lane,
    declared_target,
)

_DIMENSIONS = set(SupportDimension)
_ROLLBACK_PATHS = frozenset(
    {
        "package_rollback",
        "lifecycle_rollback",
        "settings_rollback",
        "bootstrap_rollback",
        "benchmark_rerun",
    }
)


def test_frozen_matrix_declares_the_four_targets() -> None:
    assert {target.target for target in FROZEN_TARGETS} == {
        "ubuntu-1",
        "ubuntu-2",
        "windows-x64",
        "macos-arm64",
    }


def test_every_target_declares_every_dimension() -> None:
    for target in FROZEN_TARGETS:
        assert len(target.claims) == len(_DIMENSIONS)
        assert {claim.dimension for claim in target.claims} == _DIMENSIONS


def test_every_claim_maps_to_artifact_machine_lane_and_rollback() -> None:
    for target in FROZEN_TARGETS:
        for claim in target.claims:
            assert claim.artifact in ArtifactKind
            assert claim.machine == target.target
            assert claim.lane in Lane
            assert claim.rollback_path in _ROLLBACK_PATHS


def test_frozen_values_match_the_supported_engine_tiers() -> None:
    ubuntu_one = declared_target("ubuntu-1")
    assert ubuntu_one.platform == "linux"
    assert ubuntu_one.architecture == "x86_64"
    assert ubuntu_one.engine_tier == "vllm"
    windows = declared_target("windows-x64")
    assert windows.platform == "windows"
    assert windows.engine_tier == "llama.cpp"
    macos = declared_target("macos-arm64")
    assert macos.platform == "macos"
    assert macos.architecture == "arm64"
    assert macos.engine_tier == "llama.cpp"


def test_unknown_target_is_rejected() -> None:
    with pytest.raises(ValueError):
        declared_target("intel-mac")


def test_linux_targets_declare_cuda_accelerator_and_managed_lifecycle() -> None:
    for name in ("ubuntu-1", "ubuntu-2"):
        target = declared_target(name)
        accelerator = next(c for c in target.claims if c.dimension is SupportDimension.ACCELERATOR)
        engine = next(c for c in target.claims if c.dimension is SupportDimension.ENGINE)
        assert accelerator.value == "cuda"
        assert engine.value == "vllm"
        assert engine.artifact is ArtifactKind.BENCHMARK_RUN


def test_declared_claims_are_immutable_frozen_values() -> None:
    target = declared_target("ubuntu-1")
    with pytest.raises((AttributeError, FrozenInstanceError)):
        target.claims[0].value = "changed"  # type: ignore[misc]


def test_matrix_contains_no_other_platforms() -> None:
    for target in FROZEN_TARGETS:
        assert target.platform in {"linux", "windows", "macos"}
