"""Package trust policy core (DESK-002, ADR-0009).

Pure, dependency-free evaluation of the trust a package may carry: its
qualification level (developer/source vs signed distribution), whether its
per-file digests were verified, and what actions the active policy permits.
Developer/source-qualified packages can never enable unattended update or
background auto-update; every use requires explicit confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass

QUALIFICATION_DEVELOPER = "developer-source"
QUALIFICATION_SIGNED = "signed-distribution"
_QUALIFICATIONS = frozenset({QUALIFICATION_DEVELOPER, QUALIFICATION_SIGNED})


class TrustError(ValueError):
    """A trust input is malformed or a qualification is unknown."""


@dataclass(frozen=True, slots=True)
class PackageTrustPolicy:
    """Operator policy governing signed-distribution packages.

    The developer/source qualification ignores this policy: unsigned
    packages always require confirmation and never allow unattended
    update, regardless of policy values.
    """

    allow_unattended_update: bool = False
    require_confirmation: bool = True


DEFAULT_TRUST_POLICY = PackageTrustPolicy()


@dataclass(frozen=True, slots=True)
class TrustVerdict:
    """What a package is permitted to do under the active policy."""

    qualification: str
    digests_verified: bool
    confirmation_required: bool
    unattended_update_allowed: bool
    reason: str

    @property
    def usable(self) -> bool:
        return self.digests_verified


def evaluate_trust(
    *,
    qualification: str,
    digests_verified: bool,
    policy: PackageTrustPolicy = DEFAULT_TRUST_POLICY,
) -> TrustVerdict:
    """Evaluate the trust of a candidate package under ``policy``.

    A package whose digests failed verification is never usable. An
    unsigned developer/source package always requires confirmation and
    can never be applied unattended, even under a permissive policy.
    """
    if qualification not in _QUALIFICATIONS:
        raise TrustError(f"unknown package qualification: {qualification!r}")
    if not digests_verified:
        return TrustVerdict(
            qualification=qualification,
            digests_verified=False,
            confirmation_required=True,
            unattended_update_allowed=False,
            reason="digest verification failed",
        )
    if qualification == QUALIFICATION_DEVELOPER:
        return TrustVerdict(
            qualification=qualification,
            digests_verified=True,
            confirmation_required=True,
            unattended_update_allowed=False,
            reason=(
                f"{qualification} package: checksum-verified; confirmation required, "
                "unattended update disabled"
            ),
        )
    return TrustVerdict(
        qualification=qualification,
        digests_verified=True,
        confirmation_required=policy.require_confirmation,
        unattended_update_allowed=policy.allow_unattended_update,
        reason=f"{qualification} package: checksum-verified under the active policy",
    )
