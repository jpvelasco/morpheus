"""Contract tests: package-trust-aware install/repair/update/rollback (DESK-002).

End-to-end evidence that a candidate package flows from digest
verification through trust evaluation and planning into a bounded
operation sequence, and that an unsigned package can never be applied
unattended or without explicit confirmation.
"""

from __future__ import annotations

import pytest

from morpheus.adapters.install.adapter import DevInstallExecutor, InstallError
from morpheus.core.bootstrap import (
    BootstrapState,
    CandidatePackage,
    plan_bootstrap,
)
from morpheus.core.package_trust import (
    QUALIFICATION_DEVELOPER,
    QUALIFICATION_SIGNED,
    PackageTrustPolicy,
    evaluate_trust,
)


def _candidate(
    *, version: str = "0.1.0", qualification: str = QUALIFICATION_DEVELOPER
) -> CandidatePackage:
    return CandidatePackage(
        package_name="morpheus-backend",
        version=version,
        platform="linux-x86_64",
        qualification=qualification,
        digests_verified=True,
    )


def _trust(qualification: str, *, permissive: bool = False) -> object:
    return evaluate_trust(
        qualification=qualification,
        digests_verified=True,
        policy=PackageTrustPolicy(
            allow_unattended_update=permissive,
            require_confirmation=not permissive,
        ),
    )


@pytest.mark.asyncio
async def test_install_flow_executes_bounded_operations_with_confirmation() -> None:
    candidate = _candidate()
    plan = plan_bootstrap(
        state=BootstrapState(backend_present=False, backend_running=False),
        candidate=candidate,
        trust=_trust(QUALIFICATION_DEVELOPER),
    )
    executor = DevInstallExecutor()
    outcome = await executor.execute(plan=plan, explicit_confirmation=True)
    assert outcome.ok
    assert outcome.plan_kind == "install"
    assert outcome.operations == (
        "verify-checksums",
        "stage",
        "register-service",
        "health-wait",
        "smoke",
    )
    assert executor.operations == list(outcome.operations)


@pytest.mark.asyncio
async def test_unsigned_install_without_confirmation_is_rejected() -> None:
    candidate = _candidate()
    plan = plan_bootstrap(
        state=BootstrapState(backend_present=False, backend_running=False),
        candidate=candidate,
        trust=_trust(QUALIFICATION_DEVELOPER),
    )
    with pytest.raises(InstallError):
        await DevInstallExecutor().execute(plan=plan, explicit_confirmation=False)


@pytest.mark.asyncio
async def test_update_flow_never_silently_replaces_running_backend() -> None:
    candidate = _candidate(version="0.1.0")
    trust = _trust(QUALIFICATION_SIGNED, permissive=True)
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=True,
            backend_version="0.0.9",
        ),
        candidate=candidate,
        trust=trust,
    )
    assert plan.kind == "update"
    assert plan.confirmation_required
    assert not plan.unattended_allowed
    with pytest.raises(InstallError):
        await DevInstallExecutor().execute(plan=plan, explicit_confirmation=False)
    outcome = await DevInstallExecutor().execute(plan=plan, explicit_confirmation=True)
    assert outcome.ok
    assert "backup" in outcome.operations
    assert "stop-service" in outcome.operations


@pytest.mark.asyncio
async def test_repair_flow_recovers_unhealthy_backend_with_confirmation() -> None:
    candidate = _candidate()
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=False,
            backend_version="0.1.0",
        ),
        candidate=candidate,
        trust=_trust(QUALIFICATION_DEVELOPER),
    )
    assert plan.kind == "repair"
    outcome = await DevInstallExecutor().execute(plan=plan, explicit_confirmation=True)
    assert outcome.ok
    assert outcome.operations[0] == "verify-checksums"
    assert outcome.operations[-1] == "smoke"


@pytest.mark.asyncio
async def test_rollback_flow_restores_backup_before_start() -> None:
    candidate = _candidate(version="0.1.0")
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=True,
            backend_version="0.1.1",
        ),
        candidate=candidate,
        trust=_trust(QUALIFICATION_DEVELOPER),
    )
    assert plan.kind == "rollback"
    outcome = await DevInstallExecutor().execute(plan=plan, explicit_confirmation=True)
    assert outcome.ok
    assert "restore-backup" in outcome.operations


@pytest.mark.asyncio
async def test_noop_flow_is_side_effect_free() -> None:
    candidate = _candidate()
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=True,
            backend_version="0.1.0",
        ),
        candidate=candidate,
        trust=_trust(QUALIFICATION_DEVELOPER),
    )
    assert plan.kind == "noop"
    outcome = await DevInstallExecutor().execute(plan=plan, explicit_confirmation=False)
    assert outcome.ok
    assert outcome.operations == ()


@pytest.mark.asyncio
async def test_unattended_unsigned_update_is_impossible_end_to_end() -> None:
    candidate = _candidate()
    trust = _trust(QUALIFICATION_DEVELOPER)
    state = BootstrapState(
        backend_present=True,
        backend_running=False,
        backend_healthy=True,
        backend_version="0.0.9",
    )
    plan = plan_bootstrap(state=state, candidate=candidate, trust=trust)
    assert plan.kind == "update"
    assert not plan.unattended_allowed
    with pytest.raises(InstallError):
        await DevInstallExecutor().execute(plan=plan, explicit_confirmation=False)
    outcome = await DevInstallExecutor().execute(plan=plan, explicit_confirmation=True)
    assert outcome.ok
    assert outcome.plan_kind == "update"
