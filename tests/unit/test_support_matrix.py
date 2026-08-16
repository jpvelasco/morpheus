"""Unit tests: evidence-bounded support matrix (ACCESS-003).

A target is advertised as supported only for the exact operating system,
architecture, accelerator, engine, install, lifecycle, access, benchmark,
and recovery combinations covered by retained evidence. Absent evidence
must never become a claim.
"""

from __future__ import annotations

from typing import Any

from morpheus.core.support_matrix import (
    BenchmarkRunRef,
    ClaimState,
    EvidenceRunRef,
    SupportDimension,
    derive_support_profile,
)

A_DIGEST = "a" * 64
B_DIGEST = "b" * 64
C_DIGEST = "c" * 64


def run(
    *,
    run_id: str,
    digest: str = A_DIGEST,
    status: str = "pass",
    environment: str = "DEV",
    machine_profile: dict[str, Any] | None = None,
    deployment: dict[str, Any] | None = None,
    regressions: tuple[str, ...] = (),
    runbooks: tuple[str, ...] = (),
) -> EvidenceRunRef:
    return EvidenceRunRef(
        run_id=run_id,
        digest=digest,
        status=status,
        environment=environment,
        machine_profile=machine_profile or {},
        deployment=deployment or {},
        regressions=regressions,
        runbooks=runbooks,
    )


def benchmark(
    *, run_id: str, status: str = "completed", machine_id: str = "batwing", engine_id: str = "vllm"
) -> BenchmarkRunRef:
    return BenchmarkRunRef(run_id=run_id, status=status, machine_id=machine_id, engine_id=engine_id)


def test_empty_evidence_proves_nothing() -> None:
    profile = derive_support_profile(evidence_runs=(), benchmark_runs=(), named_targets={})
    assert profile.advertised() == ()
    for claim in profile.machine_claims:
        assert claim.state is ClaimState.UNPROVEN
        assert claim.evidence_refs == ()
        assert claim.value == ""


def test_pass_run_proves_machine_dimensions() -> None:
    evidence = (
        run(
            run_id="diag-1",
            machine_profile={
                "platform": "linux",
                "architecture": "x86_64",
                "accelerator": "cuda",
            },
        ),
    )
    profile = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    claimed = {c.dimension: c.value for c in profile.machine_claims if c.state is ClaimState.PROVEN}
    assert claimed == {
        SupportDimension.OS: "linux",
        SupportDimension.ARCHITECTURE: "x86_64",
        SupportDimension.ACCELERATOR: "cuda",
    }


def test_proven_claims_carry_exact_evidence_references() -> None:
    evidence = (
        run(run_id="diag-1", digest=B_DIGEST, machine_profile={"platform": "linux"}),
        run(run_id="diag-2", digest=C_DIGEST, machine_profile={"platform": "linux"}),
    )
    profile = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    claim = next(c for c in profile.machine_claims if c.dimension is SupportDimension.OS)
    assert claim.state is ClaimState.PROVEN
    assert claim.evidence_refs == (f"diag-1:{B_DIGEST}", f"diag-2:{C_DIGEST}")


def test_failed_evidence_runs_never_prove_claims() -> None:
    evidence = (
        run(run_id="failed-run", status="fail", machine_profile={"platform": "linux"}),
        run(run_id="unknown-run", status="pending", machine_profile={"platform": "darwin"}),
    )
    profile = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    assert profile.advertised() == ()


def test_deployment_dimensions_only_from_retained_evidence() -> None:
    evidence = (
        run(
            run_id="diag-1",
            deployment={
                "engine_id": "llama.cpp",
                "install_method": "mrpkg",
                "lifecycle_state": "active",
                "access_profile": "ssh_tunnel",
                "recovery": True,
            },
        ),
    )
    profile = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    claimed = {c.dimension: c.value for c in profile.machine_claims if c.state is ClaimState.PROVEN}
    assert claimed == {
        SupportDimension.ENGINE: "llama.cpp",
        SupportDimension.INSTALL: "mrpkg",
        SupportDimension.LIFECYCLE: "active",
        SupportDimension.ACCESS: "ssh_tunnel",
        SupportDimension.RECOVERY: "true",
    }


def test_benchmark_claims_require_completed_runs() -> None:
    profile = derive_support_profile(
        evidence_runs=(
            run(run_id="diag-1", machine_profile={"platform": "linux", "accelerator": "cuda"}),
        ),
        benchmark_runs=(benchmark(run_id="bench-1"), benchmark(run_id="bench-2", status="failed")),
        named_targets={},
    )
    claims = {c.value for c in profile.machine_claims if c.state is ClaimState.PROVEN}
    assert "vllm@batwing" in claims
    benchmark_claims = [
        c for c in profile.machine_claims if c.dimension is SupportDimension.BENCHMARK
    ]
    assert len(benchmark_claims) == 1
    assert benchmark_claims[0].evidence_refs == ("bench-1:completed",)


def test_named_targets_require_matching_physical_evidence() -> None:
    profile = derive_support_profile(
        evidence_runs=(
            run(
                run_id="diag-1",
                environment="HOST-RO",
                machine_profile={"machine_id": "batwing", "platform": "linux"},
            ),
        ),
        benchmark_runs=(),
        named_targets={"batwing": "linux", "batmobile": "linux"},
    )
    targets = {t.target: t.state for t in profile.targets}
    assert targets == {"batwing": ClaimState.PROVEN, "batmobile": ClaimState.UNPROVEN}
    batwing = next(t for t in profile.targets if t.target == "batwing")
    assert batwing.evidence_refs == (f"diag-1:{A_DIGEST}",)


def test_named_target_wrong_platform_is_not_proven() -> None:
    profile = derive_support_profile(
        evidence_runs=(
            run(
                run_id="diag-1",
                environment="HOST-RO",
                machine_profile={"machine_id": "batwing", "platform": "windows"},
            ),
        ),
        benchmark_runs=(),
        named_targets={"batwing": "linux"},
    )
    assert profile.targets[0].state is ClaimState.UNPROVEN


def test_named_target_requires_physical_environment() -> None:
    profile = derive_support_profile(
        evidence_runs=(
            run(
                run_id="diag-1",
                environment="DEV",
                machine_profile={"machine_id": "batwing", "platform": "linux"},
            ),
        ),
        benchmark_runs=(),
        named_targets={"batwing": "linux"},
    )
    assert profile.targets[0].state is ClaimState.UNPROVEN


def test_profile_is_deterministic_and_sorted() -> None:
    evidence = (
        run(run_id="z-run", machine_profile={"platform": "linux"}),
        run(run_id="a-run", machine_profile={"platform": "linux"}),
    )
    first = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    second = derive_support_profile(
        evidence_runs=tuple(reversed(evidence)), benchmark_runs=(), named_targets={}
    )
    assert first.to_public_dict() == second.to_public_dict()
    os_claim = next(c for c in first.machine_claims if c.dimension is SupportDimension.OS)
    assert os_claim.evidence_refs == (f"a-run:{A_DIGEST}", f"z-run:{A_DIGEST}")


def test_public_dict_shape_is_bounded() -> None:
    profile = derive_support_profile(evidence_runs=(), benchmark_runs=(), named_targets={})
    payload = profile.to_public_dict()
    assert set(payload) == {"dimensions", "targets", "advertised"}
    assert isinstance(payload["advertised"], list)


def test_unknown_dimension_keys_are_never_invented() -> None:
    evidence = (run(run_id="diag-1", machine_profile={"magic": "value"}),)
    profile = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    assert profile.advertised() == ()


def test_recovery_claim_requires_explicit_true() -> None:
    evidence = (
        run(run_id="diag-1", deployment={"recovery": False}),
        run(run_id="diag-2", deployment={"recovery": "planned"}),
    )
    profile = derive_support_profile(evidence_runs=evidence, benchmark_runs=(), named_targets={})
    recovery = next(c for c in profile.machine_claims if c.dimension is SupportDimension.RECOVERY)
    assert recovery.state is ClaimState.UNPROVEN
