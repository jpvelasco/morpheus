"""Bootstrap/repair/update/rollback plan unit tests (DESK-002)."""

from __future__ import annotations

import pytest

from morpheus.core.bootstrap import (
    BootstrapPlan,
    BootstrapState,
    CandidatePackage,
    ConfirmationRequired,
    UnattendedRejected,
    apply_plan,
    plan_bootstrap,
)
from morpheus.core.package_trust import (
    QUALIFICATION_DEVELOPER,
    QUALIFICATION_SIGNED,
    PackageTrustPolicy,
    evaluate_trust,
)


def _candidate(qualification: str = QUALIFICATION_DEVELOPER) -> CandidatePackage:
    return CandidatePackage(
        package_name="morpheus-backend",
        version="0.1.0",
        platform="linux-x86_64",
        qualification=qualification,
        digests_verified=True,
    )


def _unsigned() -> tuple[CandidatePackage, object]:
    candidate = _candidate()
    return candidate, evaluate_trust(qualification=candidate.qualification, digests_verified=True)


def test_no_backend_without_confirmation_is_rejected_at_apply() -> None:
    candidate, trust = _unsigned()
    plan = plan_bootstrap(
        state=BootstrapState(backend_present=False, backend_running=False),
        candidate=candidate,
        trust=trust,
    )
    assert plan.kind == "install"
    assert plan.confirmation_required
    with pytest.raises(ConfirmationRequired):
        apply_plan(plan=plan, explicit_confirmation=False)


def test_no_backend_with_confirmation_plans_install() -> None:
    candidate, trust = _unsigned()
    plan = plan_bootstrap(
        state=BootstrapState(backend_present=False, backend_running=False),
        candidate=candidate,
        trust=trust,
    )
    assert plan.kind == "install"
    assert plan.confirmation_required
    assert not plan.unattended_allowed
    assert plan.steps[0] == "verify-checksums"
    apply_plan(plan=plan, explicit_confirmation=True)


def test_compatible_backend_plans_noop() -> None:
    candidate, trust = _unsigned()
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=True,
            backend_version="0.1.0",
        ),
        candidate=candidate,
        trust=trust,
        explicit_confirmation=True,
    )
    assert plan.kind == "noop"


def test_unsupported_backend_version_plans_update() -> None:
    candidate, trust = _unsigned()
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=True,
            backend_version="0.0.9",
        ),
        candidate=candidate,
        trust=trust,
        explicit_confirmation=True,
    )
    assert plan.kind == "update"
    assert plan.confirmation_required
    assert "backup" in plan.steps
    assert "stop-service" in plan.steps


def test_update_of_running_service_always_requires_confirmation() -> None:
    candidate, trust = _unsigned()
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
    with pytest.raises(ConfirmationRequired):
        apply_plan(plan=plan, explicit_confirmation=False)


def test_unhealthy_backend_plans_repair_with_confirmation() -> None:
    candidate, trust = _unsigned()
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=False,
            backend_version="0.1.0",
        ),
        candidate=candidate,
        trust=trust,
        explicit_confirmation=True,
    )
    assert plan.kind == "repair"
    assert plan.confirmation_required
    assert "stop-service" in plan.steps


def test_candidate_older_than_installed_plans_rollback() -> None:
    candidate, trust = _unsigned()
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=True,
            backend_version="0.1.1",
        ),
        candidate=candidate,
        trust=trust,
        explicit_confirmation=True,
    )
    assert plan.kind == "rollback"
    assert "restore-backup" in plan.steps


def test_signed_update_allows_unattended_when_policy_permits() -> None:
    candidate = _candidate(qualification=QUALIFICATION_SIGNED)
    trust = evaluate_trust(
        qualification=candidate.qualification,
        digests_verified=True,
        policy=PackageTrustPolicy(allow_unattended_update=True, require_confirmation=False),
    )
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=False,
            backend_healthy=True,
            backend_version="0.0.9",
        ),
        candidate=candidate,
        trust=trust,
    )
    assert plan.kind == "update"
    assert not plan.confirmation_required
    assert plan.unattended_allowed
    apply_plan(plan=plan, explicit_confirmation=False)


def test_signed_update_never_replaces_running_service_without_confirmation() -> None:
    candidate = _candidate(qualification=QUALIFICATION_SIGNED)
    trust = evaluate_trust(
        qualification=candidate.qualification,
        digests_verified=True,
        policy=PackageTrustPolicy(allow_unattended_update=True, require_confirmation=False),
    )
    plan = plan_bootstrap(
        state=BootstrapState(
            backend_present=True,
            backend_running=True,
            backend_healthy=False,
            backend_version="0.1.0",
        ),
        candidate=candidate,
        trust=trust,
    )
    assert plan.kind == "repair"
    assert plan.confirmation_required
    assert not plan.unattended_allowed


def test_apply_plan_rejects_missing_confirmation() -> None:
    plan = BootstrapPlan(
        kind="install",
        target="backend",
        candidate_version="0.1.0",
        steps=("verify-checksums",),
        confirmation_required=True,
        unattended_allowed=False,
        reason="unsigned developer package",
    )
    with pytest.raises(ConfirmationRequired):
        apply_plan(plan=plan, explicit_confirmation=False)


def test_apply_plan_accepts_confirmation() -> None:
    plan = BootstrapPlan(
        kind="install",
        target="backend",
        candidate_version="0.1.0",
        steps=("verify-checksums",),
        confirmation_required=True,
        unattended_allowed=False,
        reason="unsigned developer package",
    )
    assert apply_plan(plan=plan, explicit_confirmation=True) is None


def test_apply_plan_rejects_unattended_when_plan_forbids() -> None:
    plan = BootstrapPlan(
        kind="update",
        target="backend",
        candidate_version="0.1.0",
        steps=("backup",),
        confirmation_required=False,
        unattended_allowed=False,
        reason="unsigned developer package",
    )
    with pytest.raises(UnattendedRejected):
        apply_plan(plan=plan, explicit_confirmation=False)


def test_apply_noop_plan_is_noop() -> None:
    plan = BootstrapPlan(
        kind="noop",
        target="backend",
        candidate_version="0.1.0",
        steps=(),
        confirmation_required=False,
        unattended_allowed=False,
        reason="already compatible",
    )
    assert apply_plan(plan=plan, explicit_confirmation=False) is None
