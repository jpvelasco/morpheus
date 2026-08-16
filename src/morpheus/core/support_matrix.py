"""Evidence-bounded support matrix (ACCESS-003).

A target is advertised as supported only for the exact operating system,
architecture, accelerator, engine, install, benchmark, lifecycle, access,
and recovery combinations covered by retained evidence. The derivation is
pure and deterministic: it consumes parsed evidence run references and
benchmark run references, and it can never invent a claim that no retained
evidence supports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SupportDimension(StrEnum):
    OS = "os"
    ARCHITECTURE = "architecture"
    ACCELERATOR = "accelerator"
    ENGINE = "engine"
    INSTALL = "install"
    LIFECYCLE = "lifecycle"
    ACCESS = "access"
    RECOVERY = "recovery"
    BENCHMARK = "benchmark"


class ClaimState(StrEnum):
    PROVEN = "proven"
    UNPROVEN = "unproven"


_MACHINE_PROFILE_FIELDS: dict[SupportDimension, str] = {
    SupportDimension.OS: "platform",
    SupportDimension.ARCHITECTURE: "architecture",
    SupportDimension.ACCELERATOR: "accelerator",
}
_DEPLOYMENT_FIELDS: dict[SupportDimension, str] = {
    SupportDimension.ENGINE: "engine_id",
    SupportDimension.INSTALL: "install_method",
    SupportDimension.LIFECYCLE: "lifecycle_state",
    SupportDimension.ACCESS: "access_profile",
}
_LIFECYCLE_STATES = frozenset({"installed", "active", "complete"})
_ACCESS_PROFILES = frozenset({"loopback", "ssh_tunnel", "network"})
_RECOVERY_PROVEN = "true"
_PHYSICAL_ENVIRONMENTS = frozenset({"HOST-RO", "HOST-MAINT"})


@dataclass(frozen=True, slots=True)
class EvidenceRunRef:
    run_id: str
    digest: str
    status: str
    environment: str
    machine_profile: Mapping[str, Any]
    deployment: Mapping[str, Any]
    regressions: tuple[str, ...] = ()
    runbooks: tuple[str, ...] = ()

    @property
    def reference(self) -> str:
        return f"{self.run_id}:{self.digest}"


@dataclass(frozen=True, slots=True)
class BenchmarkRunRef:
    run_id: str
    status: str
    machine_id: str
    engine_id: str

    @property
    def reference(self) -> str:
        return f"{self.run_id}:{self.status}"


@dataclass(frozen=True, slots=True)
class SupportClaim:
    dimension: SupportDimension
    value: str
    state: ClaimState
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetClaim:
    target: str
    platform: str
    state: ClaimState
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SupportProfile:
    machine_claims: tuple[SupportClaim, ...]
    targets: tuple[TargetClaim, ...]

    def advertised(self) -> tuple[str, ...]:
        return tuple(
            f"{claim.dimension}={claim.value}"
            for claim in self.machine_claims
            if claim.state is ClaimState.PROVEN
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "dimensions": [
                {
                    "dimension": claim.dimension.value,
                    "value": claim.value,
                    "state": claim.state.value,
                    "evidence_refs": list(claim.evidence_refs),
                }
                for claim in self.machine_claims
            ],
            "targets": [
                {
                    "target": target.target,
                    "platform": target.platform,
                    "state": target.state.value,
                    "evidence_refs": list(target.evidence_refs),
                }
                for target in self.targets
            ],
            "advertised": list(self.advertised()),
        }


def _passing_evidence(
    evidence_runs: tuple[EvidenceRunRef, ...],
) -> tuple[EvidenceRunRef, ...]:
    return tuple(run for run in evidence_runs if run.status.lower() == "pass")


def _string_field(section: Mapping[str, Any], field: str) -> str | None:
    value = section.get(field)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _dimension_claim(
    dimension: SupportDimension,
    value: str,
    refs: tuple[str, ...],
) -> SupportClaim:
    return SupportClaim(dimension, value, ClaimState.PROVEN, refs)


def _machine_claim(
    dimension: SupportDimension,
    passes: tuple[EvidenceRunRef, ...],
) -> SupportClaim:
    fields = {
        **_MACHINE_PROFILE_FIELDS,
        **_DEPLOYMENT_FIELDS,
    }
    field = fields[dimension]
    values: dict[str, list[str]] = {}
    for evidence in passes:
        value = _string_field(evidence.machine_profile, field)
        if value is None:
            value = _string_field(evidence.deployment, field)
        if value is None:
            continue
        if dimension is SupportDimension.LIFECYCLE and value not in _LIFECYCLE_STATES:
            continue
        if dimension is SupportDimension.ACCESS and value not in _ACCESS_PROFILES:
            continue
        values.setdefault(value, []).append(evidence.reference)
    if not values:
        return SupportClaim(dimension, "", ClaimState.UNPROVEN)
    value = sorted(values)[0]
    refs = tuple(sorted(values[value]))
    return _dimension_claim(dimension, value, refs)


def _recovery_claim(passes: tuple[EvidenceRunRef, ...]) -> SupportClaim:
    refs = tuple(
        evidence.reference for evidence in passes if evidence.deployment.get("recovery") is True
    )
    if not refs:
        return SupportClaim(SupportDimension.RECOVERY, "", ClaimState.UNPROVEN)
    return _dimension_claim(SupportDimension.RECOVERY, _RECOVERY_PROVEN, refs)


def _benchmark_claim(
    passes: tuple[EvidenceRunRef, ...],
    benchmarks: tuple[BenchmarkRunRef, ...],
) -> SupportClaim:
    del passes
    completed = tuple(run for run in benchmarks if run.status == "completed")
    if not completed:
        return SupportClaim(SupportDimension.BENCHMARK, "", ClaimState.UNPROVEN)
    refs: list[str] = []
    for run in sorted(completed, key=lambda item: item.run_id):
        refs.append(run.reference)
    values = sorted({f"{run.engine_id}@{run.machine_id}" for run in completed})
    return _dimension_claim(SupportDimension.BENCHMARK, values[0], tuple(refs))


def derive_support_profile(
    *,
    evidence_runs: tuple[EvidenceRunRef, ...],
    benchmark_runs: tuple[BenchmarkRunRef, ...],
    named_targets: Mapping[str, str],
) -> SupportProfile:
    """Derive the support posture strictly from retained evidence."""
    passes = _passing_evidence(evidence_runs)
    claims: list[SupportClaim] = [
        _machine_claim(dimension, passes)
        for dimension in (
            SupportDimension.OS,
            SupportDimension.ARCHITECTURE,
            SupportDimension.ACCELERATOR,
            SupportDimension.ENGINE,
            SupportDimension.INSTALL,
            SupportDimension.LIFECYCLE,
            SupportDimension.ACCESS,
        )
    ]
    claims.append(_recovery_claim(passes))
    claims.append(_benchmark_claim(passes, benchmark_runs))

    targets: list[TargetClaim] = []
    for target in sorted(named_targets):
        platform = named_targets[target]
        refs = tuple(
            evidence.reference
            for evidence in passes
            if evidence.environment.upper() in _PHYSICAL_ENVIRONMENTS
            and _string_field(evidence.machine_profile, "machine_id") == target
            and _string_field(evidence.machine_profile, "platform") == platform
        )
        state = ClaimState.PROVEN if refs else ClaimState.UNPROVEN
        targets.append(TargetClaim(target, platform, state, refs))
    return SupportProfile(tuple(claims), tuple(targets))
