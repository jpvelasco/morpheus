from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
_NORMALIZE = re.compile(r"[^a-z0-9]")
_EXACT_SENSITIVE = {
    "apikey",
    "authorization",
    "cookie",
    "password",
    "prompt",
    "response",
    "secret",
    "sessionsecret",
    "token",
    "upstreamapikey",
}
_SENSITIVE_SUFFIXES = ("apikey", "authorization", "password", "secret", "token")
_SENSITIVE_CONTENT_PREFIXES = ("audio", "document", "image", "prompt", "response")
_SAFE_SUFFIXES = ("count", "duration", "latency", "reason", "status", "time", "tokens", "type")


def _is_sensitive_key(key: object) -> bool:
    normalized = _NORMALIZE.sub("", str(key).lower())
    if normalized in _EXACT_SENSITIVE:
        return True
    if normalized.endswith(_SENSITIVE_SUFFIXES):
        return True
    return normalized.startswith(_SENSITIVE_CONTENT_PREFIXES) and not normalized.endswith(
        _SAFE_SUFFIXES
    )


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else redact(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
