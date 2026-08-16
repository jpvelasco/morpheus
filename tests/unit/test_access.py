"""Unit tests: secure access profiles (ACCESS-001).

Loopback and SSH-tunnel profiles enforce loopback-only binding, never
trust proxy headers, and report the exact posture the operator needs to
know before serving or tunneling.
"""

from __future__ import annotations

import pytest

from morpheus.config import MorpheusSettings
from morpheus.core.access import (
    AccessPolicyError,
    AccessProfile,
    access_capabilities,
    derive_access_policy,
)


def settings(**overrides: object) -> MorpheusSettings:
    return MorpheusSettings.model_validate(overrides)


def test_loopback_profile_requires_loopback_bind() -> None:
    policy = derive_access_policy(settings())
    assert policy.profile is AccessProfile.LOOPBACK
    assert policy.bind_address == "127.0.0.1"
    assert policy.proxy_headers_trusted is False
    assert policy.allowed_origins == ()


def test_ssh_tunnel_profile_keeps_loopback_bind() -> None:
    policy = derive_access_policy(settings(access_profile="ssh_tunnel"))
    assert policy.profile is AccessProfile.SSH_TUNNEL
    assert policy.bind_address == "127.0.0.1"
    assert policy.proxy_headers_trusted is False


def test_non_loopback_bind_rejected_by_settings_validation() -> None:
    with pytest.raises(ValueError):
        settings(bind_address="0.0.0.0", allow_lan=True)  # noqa: S104


def test_non_loopback_bind_rejected_by_policy_guard() -> None:
    raw = MorpheusSettings.model_construct(  # bypass validation to reach the policy guard
        bind_address="0.0.0.0",  # noqa: S104
        allow_lan=True,
        access_profile="loopback",
    )
    with pytest.raises(AccessPolicyError):
        derive_access_policy(raw)


def test_ipv6_loopback_bind_allowed() -> None:
    policy = derive_access_policy(settings(bind_address="::1"))
    assert policy.profile is AccessProfile.LOOPBACK


def test_access_capabilities_report_posture_without_secrets() -> None:
    capabilities = access_capabilities(settings())
    assert capabilities["profile"] == "loopback"
    assert capabilities["bind_address"] == "127.0.0.1"
    assert capabilities["loopback_only"] is True
    assert capabilities["proxy_headers_trusted"] is False
    assert capabilities["allowed_origins"] == []
    assert capabilities["cookie_samesite"] == "strict"
    assert capabilities["session_ttl_seconds"] == 900
    assert "api_key" not in capabilities


def test_access_capabilities_report_ssh_tunnel_profile() -> None:
    capabilities = access_capabilities(settings(access_profile="ssh_tunnel"))
    assert capabilities["profile"] == "ssh_tunnel"
    assert capabilities["loopback_only"] is True
    assert capabilities["tunnel_command"].startswith("ssh -L")


def test_unknown_profile_rejected_by_settings() -> None:
    with pytest.raises(ValueError):
        settings(access_profile="network")
