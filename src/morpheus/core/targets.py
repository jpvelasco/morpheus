"""Frozen target/support matrix (HOST-003, PLAT-004).

The matrix is a frozen, immutable declaration: the exact targets Morpheus
qualifies and the claim per target for every support dimension. Every
declared claim maps to an exact evidence artifact kind, machine, lane,
and rollback path, so a support report can never advertise anything
outside this registry, and every claim can be traced to its qualification
evidence and its recovery path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from morpheus.core.support_matrix import SupportDimension


class ArtifactKind(StrEnum):
    EVIDENCE_RUN = "evidence_run"
    BENCHMARK_RUN = "benchmark_run"


class Lane(StrEnum):
    HOST_RO = "HOST-RO"
    HOST_MAINT = "HOST-MAINT"


@dataclass(frozen=True, slots=True)
class DeclaredClaim:
    dimension: SupportDimension
    value: str
    artifact: ArtifactKind
    machine: str
    lane: Lane
    rollback_path: str


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    target: str
    platform: str
    architecture: str
    engine_tier: str
    claims: tuple[DeclaredClaim, ...]


def _claim(
    dimension: SupportDimension,
    value: str,
    artifact: ArtifactKind,
    machine: str,
    lane: Lane,
    rollback_path: str,
) -> DeclaredClaim:
    return DeclaredClaim(
        dimension=dimension,
        value=value,
        artifact=artifact,
        machine=machine,
        lane=lane,
        rollback_path=rollback_path,
    )


def _target(
    target: str,
    platform: str,
    architecture: str,
    engine_tier: str,
    *,
    accelerator: str,
    engine: str,
    engine_artifact: ArtifactKind,
) -> TargetDefinition:
    machine = target
    evidence_lane = Lane.HOST_RO
    benchmark_lane = Lane.HOST_MAINT
    return TargetDefinition(
        target=target,
        platform=platform,
        architecture=architecture,
        engine_tier=engine_tier,
        claims=(
            _claim(
                SupportDimension.OS,
                platform,
                ArtifactKind.EVIDENCE_RUN,
                machine,
                evidence_lane,
                "package_rollback",
            ),
            _claim(
                SupportDimension.ARCHITECTURE,
                architecture,
                ArtifactKind.EVIDENCE_RUN,
                machine,
                evidence_lane,
                "package_rollback",
            ),
            _claim(
                SupportDimension.ACCELERATOR,
                accelerator,
                ArtifactKind.EVIDENCE_RUN,
                machine,
                evidence_lane,
                "lifecycle_rollback",
            ),
            _claim(
                SupportDimension.ENGINE,
                engine,
                engine_artifact,
                machine,
                benchmark_lane if engine_artifact is ArtifactKind.BENCHMARK_RUN else evidence_lane,
                "lifecycle_rollback",
            ),
            _claim(
                SupportDimension.INSTALL,
                "mrpkg",
                ArtifactKind.EVIDENCE_RUN,
                machine,
                evidence_lane,
                "package_rollback",
            ),
            _claim(
                SupportDimension.LIFECYCLE,
                "managed",
                ArtifactKind.EVIDENCE_RUN,
                machine,
                Lane.HOST_MAINT,
                "lifecycle_rollback",
            ),
            _claim(
                SupportDimension.ACCESS,
                "loopback",
                ArtifactKind.EVIDENCE_RUN,
                machine,
                evidence_lane,
                "settings_rollback",
            ),
            _claim(
                SupportDimension.RECOVERY,
                "true",
                ArtifactKind.EVIDENCE_RUN,
                machine,
                Lane.HOST_MAINT,
                "bootstrap_rollback",
            ),
            _claim(
                SupportDimension.BENCHMARK,
                engine,
                ArtifactKind.BENCHMARK_RUN,
                machine,
                benchmark_lane,
                "benchmark_rerun",
            ),
        ),
    )


FROZEN_TARGETS = (
    _target(
        "ubuntu-1",
        "linux",
        "x86_64",
        "vllm",
        accelerator="cuda",
        engine="vllm",
        engine_artifact=ArtifactKind.BENCHMARK_RUN,
    ),
    _target(
        "ubuntu-2",
        "linux",
        "x86_64",
        "vllm",
        accelerator="cuda",
        engine="vllm",
        engine_artifact=ArtifactKind.BENCHMARK_RUN,
    ),
    _target(
        "windows-x64",
        "windows",
        "x86_64",
        "llama.cpp",
        accelerator="cuda",
        engine="llama.cpp",
        engine_artifact=ArtifactKind.BENCHMARK_RUN,
    ),
    _target(
        "macos-arm64",
        "macos",
        "arm64",
        "llama.cpp",
        accelerator="metal",
        engine="llama.cpp",
        engine_artifact=ArtifactKind.BENCHMARK_RUN,
    ),
)


def declared_target(identifier: str) -> TargetDefinition:
    for target in FROZEN_TARGETS:
        if target.target == identifier:
            return target
    raise ValueError(f"unknown declared target: {identifier!r}")
