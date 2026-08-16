"""Secure access profiles (ACCESS-001).

The loopback and SSH-tunnel profiles are the only profiles in the v0.2
DEV lane: every surface binds to a loopback address, proxy headers are
never trusted, and the operator reaches the host only through an
operator-established SSH tunnel. A network profile (ACCESS-002) is a
separate, stricter profile that does not exist yet, so any non-loopback
bind is rejected with explicit guidance.
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


class AccessPolicyError(ValueError):
    """The configured posture violates the selected access profile."""


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    profile: AccessProfile
    bind_address: str
    cookie_secure: bool
    proxy_headers_trusted: bool
    allowed_origins: tuple[str, ...]


def derive_access_policy(settings: MorpheusSettings) -> AccessPolicy:
    """Derive the effective access posture from the settings.

    Both v0.2 profiles require a loopback bind; a non-loopback bind would
    expose the surface to peers and requires the network profile that
    arrives with ACCESS-002.
    """
    profile = AccessProfile(settings.access_profile)
    address = ipaddress.ip_address(settings.bind_address)
    if not address.is_loopback:
        raise AccessPolicyError(
            "the configured access profile serves loopback only; "
            "non-loopback binding requires the network access profile"
        )
    return AccessPolicy(
        profile=profile,
        bind_address=settings.bind_address,
        cookie_secure=settings.session_cookie_secure,
        proxy_headers_trusted=False,
        allowed_origins=(),
    )


def access_capabilities(settings: MorpheusSettings) -> dict[str, object]:
    """Non-secret posture report shown to the operator before tunneling."""
    policy = derive_access_policy(settings)
    return {
        "profile": policy.profile.value,
        "bind_address": policy.bind_address,
        "loopback_only": True,
        "proxy_headers_trusted": policy.proxy_headers_trusted,
        "allowed_origins": list(policy.allowed_origins),
        "cookie_secure": policy.cookie_secure,
        "cookie_samesite": "strict",
        "session_ttl_seconds": settings.session_ttl_seconds,
        "tunnel_command": _tunnel_command(settings),
        "access_runbook": ACCESS_RUNBOOK_ID,
    }


def _tunnel_command(settings: MorpheusSettings) -> str:
    ports = " ".join(
        f"-L {port}:127.0.0.1:{port}" for port in {settings.api_port, settings.dashboard_port}
    )
    return f"ssh {ports} operator@<host>"
