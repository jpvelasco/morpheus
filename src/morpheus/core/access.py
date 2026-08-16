"""Secure access profiles (ACCESS-001/002).

The loopback and SSH-tunnel profiles are the v0.2 default: every surface
binds to a loopback address, proxy headers are never trusted, and the
operator reaches the host only through an operator-established SSH
tunnel. The network profile (ACCESS-002) is the only profile that may
bind beyond loopback, and it requires TLS, explicit origin controls,
strong credentials, and hardened cookies before it can be selected.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum

from morpheus.config import MorpheusSettings

ACCESS_RUNBOOK_ID = "access-operator"


class AccessProfile(str, Enum):
    LOOPBACK = "loopback"
    SSH_TUNNEL = "ssh_tunnel"
    NETWORK = "network"


class AccessPolicyError(ValueError):
    """The configured posture violates the selected access profile."""


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    profile: AccessProfile
    bind_address: str
    cookie_secure: bool
    proxy_headers_trusted: bool
    allowed_origins: tuple[str, ...]
    tls_enabled: bool

    @property
    def loopback_only(self) -> bool:
        return ipaddress.ip_address(self.bind_address).is_loopback


def derive_access_policy(settings: MorpheusSettings) -> AccessPolicy:
    """Derive the effective access posture from the settings."""
    profile = AccessProfile(settings.access_profile)
    address = ipaddress.ip_address(settings.bind_address)
    if profile is not AccessProfile.NETWORK and not address.is_loopback:
        raise AccessPolicyError(
            "the configured access profile serves loopback only; "
            "non-loopback binding requires the network access profile"
        )
    if profile is AccessProfile.NETWORK:
        if not settings.tls_cert_path or not settings.tls_key_path:
            raise AccessPolicyError(
                "the network access profile requires TLS certificate and key paths"
            )
        if not settings.allowed_origins:
            raise AccessPolicyError("the network access profile requires explicit origin controls")
        return AccessPolicy(
            profile=profile,
            bind_address=settings.bind_address,
            cookie_secure=settings.session_cookie_secure,
            proxy_headers_trusted=False,
            allowed_origins=settings.allowed_origins,
            tls_enabled=True,
        )
    return AccessPolicy(
        profile=profile,
        bind_address=settings.bind_address,
        cookie_secure=settings.session_cookie_secure,
        proxy_headers_trusted=False,
        allowed_origins=(),
        tls_enabled=False,
    )


def access_capabilities(settings: MorpheusSettings) -> dict[str, object]:
    """Non-secret posture report shown to the operator before serving."""
    policy = derive_access_policy(settings)
    report: dict[str, object] = {
        "profile": policy.profile.value,
        "bind_address": policy.bind_address,
        "loopback_only": policy.loopback_only,
        "proxy_headers_trusted": policy.proxy_headers_trusted,
        "allowed_origins": list(policy.allowed_origins),
        "cookie_secure": policy.cookie_secure,
        "cookie_samesite": "strict",
        "session_ttl_seconds": settings.session_ttl_seconds,
        "tls_enabled": policy.tls_enabled,
        "rate_limit_per_minute": settings.max_requests_per_minute,
        "access_runbook": ACCESS_RUNBOOK_ID,
    }
    if policy.profile is not AccessProfile.NETWORK:
        report["tunnel_command"] = _tunnel_command(settings)
    return report


def _tunnel_command(settings: MorpheusSettings) -> str:
    ports = " ".join(
        f"-L {port}:127.0.0.1:{port}" for port in {settings.api_port, settings.dashboard_port}
    )
    return f"ssh {ports} operator@<host>"
