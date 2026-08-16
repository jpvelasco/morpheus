"""Confirmed package-trust-aware bootstrap planning (DESK-002).

Pure, dependency-free planning of what a local install/repair/update/
rollback must do for a candidate package under the active trust verdict.
A running backend is never replaced silently: any plan that stops or
replaces a running service requires explicit confirmation, and unsigned
candidate packages always require confirmation and can never be applied
unattended (ADR-0009).
"""

from __future__ import annotations

from dataclasses import dataclass

from morpheus.core.package_trust import TrustVerdict

INSTALL_STEPS = ("verify-checksums", "stage", "register-service", "health-wait", "smoke")
UPDATE_STEPS = (
    "backup",
    "verify-checksums",
    "migrate-preflight",
    "stop-service",
    "replace",
    "start-service",
    "health-wait",
    "smoke",
    "commit-marker",
)
REPAIR_STEPS = (
    "verify-checksums",
    "stop-service",
    "replace",
    "start-service",
    "health-wait",
    "smoke",
)
ROLLBACK_STEPS = ("stop-service", "restore-backup", "start-service", "health-wait")


class BootstrapError(ValueError):
    """A bootstrap plan cannot be formed or applied."""


class ConfirmationRequired(BootstrapError):
    """The plan needs explicit confirmation before it may be applied."""


class UnattendedRejected(BootstrapError):
    """An unattended application was attempted for a plan that forbids it."""


@dataclass(frozen=True, slots=True)
class CandidatePackage:
    """A verified candidate package ready to be planned."""

    package_name: str
    version: str
    platform: str
    qualification: str
    digests_verified: bool


@dataclass(frozen=True, slots=True)
class BootstrapState:
    """Observed local runtime state feeding the plan."""

    backend_present: bool
    backend_running: bool
    backend_healthy: bool | None = None
    backend_version: str | None = None


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    """A confirmed, bounded sequence of install/repair/update steps."""

    kind: str
    target: str
    candidate_version: str
    steps: tuple[str, ...]
    confirmation_required: bool
    unattended_allowed: bool
    reason: str


def plan_bootstrap(
    *,
    state: BootstrapState,
    candidate: CandidatePackage,
    trust: TrustVerdict,
    explicit_confirmation: bool = False,
) -> BootstrapPlan:
    """Plan the local bootstrap action for ``candidate`` under ``trust``.

    The plan is only formed when the trust verdict permits use. Plans
    that stop or replace a running backend always require confirmation,
    and a candidate older than the installed backend plans a rollback.
    The returned plan carries its confirmation requirement; application
    is gated by :func:`apply_plan`.
    """
    if not trust.usable:
        raise BootstrapError(f"candidate is not usable: {trust.reason}")
    if not state.backend_present:
        plan = _plan(
            "install",
            candidate=candidate,
            steps=INSTALL_STEPS,
            reason="no local backend",
        )
    elif state.backend_healthy is False:
        plan = _plan(
            "repair",
            candidate=candidate,
            steps=REPAIR_STEPS,
            reason="local backend is unhealthy",
        )
    elif state.backend_version is None or state.backend_version != candidate.version:
        plan = _plan(
            "rollback"
            if state.backend_version and state.backend_version > candidate.version
            else "update",
            candidate=candidate,
            steps=ROLLBACK_STEPS
            if state.backend_version and state.backend_version > candidate.version
            else UPDATE_STEPS,
            reason="backend version differs from the candidate",
        )
    else:
        plan = BootstrapPlan(
            kind="noop",
            target="backend",
            candidate_version=candidate.version,
            steps=(),
            confirmation_required=False,
            unattended_allowed=False,
            reason="local backend already matches the candidate",
        )

    confirmation = (
        plan.confirmation_required or state.backend_running or trust.confirmation_required
    )
    return BootstrapPlan(
        kind=plan.kind,
        target=plan.target,
        candidate_version=plan.candidate_version,
        steps=plan.steps,
        confirmation_required=confirmation,
        unattended_allowed=plan.kind == "noop"
        or (trust.unattended_update_allowed and not confirmation),
        reason=plan.reason,
    )


def apply_plan(plan: BootstrapPlan, *, explicit_confirmation: bool) -> None:
    """Validate that ``plan`` may be applied, raising if it may not."""
    if plan.kind == "noop":
        return
    if plan.confirmation_required and not explicit_confirmation:
        raise ConfirmationRequired(f"{plan.kind} requires explicit confirmation: {plan.reason}")
    if not plan.confirmation_required and not plan.unattended_allowed:
        raise UnattendedRejected(f"{plan.kind} must not be applied unattended: {plan.reason}")


def _plan(
    kind: str, *, candidate: CandidatePackage, steps: tuple[str, ...], reason: str
) -> BootstrapPlan:
    return BootstrapPlan(
        kind=kind,
        target="backend",
        candidate_version=candidate.version,
        steps=steps,
        confirmation_required=False,
        unattended_allowed=False,
        reason=reason,
    )
