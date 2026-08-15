"""Bounded compatibility layer (GATE-001)."""

from morpheus.gateway.app import compat_router
from morpheus.gateway.compat import (
    COMPAT_SCHEMA_VERSION,
    MODES,
    CompatError,
    CompatForwarder,
    CompatRoute,
    CompatUpstreamError,
    UpstreamStream,
    authenticate,
    build_forward_url,
    resolve_model,
)

__all__ = [
    "COMPAT_SCHEMA_VERSION",
    "MODES",
    "CompatError",
    "CompatForwarder",
    "CompatRoute",
    "CompatUpstreamError",
    "UpstreamStream",
    "authenticate",
    "build_forward_url",
    "compat_router",
    "resolve_model",
]
