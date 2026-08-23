"""Unit tests: TLS network access profile (ACCESS-002).

The network profile is the only profile that may bind beyond loopback,
and it demands TLS, explicit origin controls, strong credentials, and
cookie hardening before that is allowed.
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


def network_settings(**overrides: object) -> MorpheusSettings:
    defaults: dict[str, object] = {
        "bind_address": "192.168.1.10",
        "allow_lan": True,
        "access_profile": "network",
        "tls_cert_path": "C:/certs/server.crt",
        "tls_key_path": "C:/certs/server.key",
        "allowed_origins": "https://inference.example",
        "session_cookie_secure": True,
        "api_key": "network-test-key",
    }
    defaults.update(overrides)
    return MorpheusSettings.model_validate(defaults)


def test_network_profile_requires_tls_and_origins() -> None:
    policy = derive_access_policy(network_settings())
    assert policy.profile is AccessProfile.NETWORK
    assert policy.tls_enabled is True
    assert policy.allowed_origins == ("https://inference.example",)
    assert policy.proxy_headers_trusted is False


def test_network_profile_allows_lan_bind() -> None:
    policy = derive_access_policy(network_settings())
    assert policy.bind_address == "192.168.1.10"
    assert policy.loopback_only is False


def test_network_profile_rejects_loopback_only_settings() -> None:
    with pytest.raises(ValueError):
        network_settings(allow_lan=False)


def test_network_profile_rejects_missing_tls_certificate() -> None:
    with pytest.raises(ValueError):
        network_settings(tls_cert_path=None)


def test_network_profile_rejects_missing_tls_key() -> None:
    with pytest.raises(ValueError):
        network_settings(tls_key_path=None)


@pytest.mark.parametrize(
    ("cert", "key"),
    [
        ("/etc/morpheus/certs/server.crt", "/etc/morpheus/certs/server.key"),
        ("C:/certs/server.crt", "C:/certs/server.key"),
        ("C:\\certs\\server.crt", "C:\\certs\\server.key"),
    ],
)
def test_network_profile_accepts_absolute_tls_paths_from_any_host_convention(
    cert: str, key: str
) -> None:
    policy = derive_access_policy(network_settings(tls_cert_path=cert, tls_key_path=key))
    assert policy.tls_enabled is True


def test_network_profile_rejects_relative_tls_paths() -> None:
    with pytest.raises(ValueError):
        network_settings(tls_cert_path="certs/server.crt", tls_key_path="/etc/certs/server.key")
    with pytest.raises(ValueError):
        network_settings(tls_cert_path="/etc/certs/server.crt", tls_key_path="certs/server.key")
    with pytest.raises(ValueError):
        network_settings(tls_cert_path=123, tls_key_path="/etc/certs/server.key")


def test_network_profile_rejects_insecure_cookie_mode() -> None:
    with pytest.raises(ValueError):
        network_settings(session_cookie_secure=False)


def test_network_profile_rejects_empty_origin_controls() -> None:
    with pytest.raises(ValueError):
        network_settings(allowed_origins="")


def test_network_profile_rejects_non_https_origins() -> None:
    with pytest.raises(ValueError):
        network_settings(allowed_origins="http://inference.example")


def test_network_profile_rejects_origins_with_paths_or_credentials() -> None:
    with pytest.raises(ValueError):
        network_settings(allowed_origins="https://user:pass@inference.example/api")


def test_network_capabilities_report_tls_and_origin_posture() -> None:
    capabilities = access_capabilities(network_settings())
    assert capabilities["profile"] == "network"
    assert capabilities["tls_enabled"] is True
    assert capabilities["allowed_origins"] == ["https://inference.example"]
    assert capabilities["proxy_headers_trusted"] is False
    assert capabilities["rate_limit_per_minute"] == 120


def test_network_policy_guard_rejects_missing_tls() -> None:
    raw = MorpheusSettings.model_construct(  # bypass validation to reach the policy guard
        bind_address="192.168.1.10",
        allow_lan=True,
        access_profile="network",
        allowed_origins=("https://inference.example",),
    )
    with pytest.raises(AccessPolicyError):
        derive_access_policy(raw)


def test_loopback_profiles_still_reject_network_only_features() -> None:
    policy = derive_access_policy(MorpheusSettings.model_validate({}))
    assert policy.profile is AccessProfile.LOOPBACK
    assert policy.tls_enabled is False
    assert policy.allowed_origins == ()
