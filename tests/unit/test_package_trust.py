"""Package trust policy unit tests (DESK-002, ADR-0009)."""

from __future__ import annotations

import pytest

from morpheus.core.package_trust import (
    QUALIFICATION_DEVELOPER,
    QUALIFICATION_SIGNED,
    PackageTrustPolicy,
    TrustError,
    evaluate_trust,
)


def test_unsigned_verified_package_requires_confirmation_and_blocks_unattended() -> None:
    verdict = evaluate_trust(
        qualification=QUALIFICATION_DEVELOPER,
        digests_verified=True,
    )
    assert verdict.usable
    assert verdict.confirmation_required
    assert not verdict.unattended_update_allowed
    assert QUALIFICATION_DEVELOPER in verdict.reason


def test_unsigned_package_is_unusable_when_digests_fail() -> None:
    verdict = evaluate_trust(
        qualification=QUALIFICATION_DEVELOPER,
        digests_verified=False,
    )
    assert not verdict.usable
    assert verdict.confirmation_required
    assert not verdict.unattended_update_allowed


def test_unsigned_policy_cannot_enable_unattended_update() -> None:
    permissive = PackageTrustPolicy(allow_unattended_update=True, require_confirmation=False)
    verdict = evaluate_trust(
        qualification=QUALIFICATION_DEVELOPER,
        digests_verified=True,
        policy=permissive,
    )
    assert verdict.confirmation_required
    assert not verdict.unattended_update_allowed
    assert "unattended" in verdict.reason


def test_signed_verified_package_is_unattended_when_policy_allows() -> None:
    permissive = PackageTrustPolicy(allow_unattended_update=True, require_confirmation=False)
    verdict = evaluate_trust(
        qualification=QUALIFICATION_SIGNED,
        digests_verified=True,
        policy=permissive,
    )
    assert verdict.usable
    assert not verdict.confirmation_required
    assert verdict.unattended_update_allowed


def test_signed_verified_package_respects_conservative_policy() -> None:
    verdict = evaluate_trust(
        qualification=QUALIFICATION_SIGNED,
        digests_verified=True,
        policy=PackageTrustPolicy(allow_unattended_update=False, require_confirmation=True),
    )
    assert verdict.usable
    assert verdict.confirmation_required
    assert not verdict.unattended_update_allowed


def test_signed_package_is_unusable_when_digests_fail() -> None:
    verdict = evaluate_trust(
        qualification=QUALIFICATION_SIGNED,
        digests_verified=False,
    )
    assert not verdict.usable


def test_unknown_qualification_is_rejected() -> None:
    with pytest.raises(TrustError):
        evaluate_trust(qualification="self-signed-will-not-happen", digests_verified=True)
