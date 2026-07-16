from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime


class SessionValidationError(ValueError):
    """A browser session is missing, malformed, expired, or unauthenticated."""


@dataclass(frozen=True, slots=True)
class BrowserSession:
    expires_at: int
    csrf_token: str


class SessionCodec:
    def __init__(self, *, secret: bytes, ttl_seconds: int) -> None:
        if len(secret) < 16:
            raise ValueError("session secret must contain at least 16 bytes")
        self._secret = secret
        self._ttl_seconds = ttl_seconds

    def issue(self, *, now: datetime) -> tuple[str, BrowserSession]:
        expires_at = int(now.timestamp()) + self._ttl_seconds
        session = BrowserSession(expires_at=expires_at, csrf_token=secrets.token_urlsafe(24))
        payload = json.dumps(
            {
                "v": 1,
                "exp": session.expires_at,
                "csrf": session.csrf_token,
                "nonce": secrets.token_urlsafe(16),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        encoded = _encode(payload)
        signature = _encode(hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest())
        return f"{encoded}.{signature}", session

    def verify(self, token: str, *, now: datetime) -> BrowserSession:
        encoded, separator, supplied_signature = token.partition(".")
        if not separator or not encoded or "." in supplied_signature:
            raise SessionValidationError("session token is malformed")
        expected_signature = _encode(
            hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise SessionValidationError("session signature is invalid")
        try:
            payload = json.loads(_decode(encoded))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise SessionValidationError("session payload is invalid") from error
        if not isinstance(payload, dict) or set(payload) != {"v", "exp", "csrf", "nonce"}:
            raise SessionValidationError("session payload is invalid")
        expires_at = payload["exp"]
        csrf_token = payload["csrf"]
        if (
            payload["v"] != 1
            or not isinstance(expires_at, int)
            or not isinstance(csrf_token, str)
            or len(csrf_token) < 16
            or not isinstance(payload["nonce"], str)
            or int(now.timestamp()) >= expires_at
        ):
            raise SessionValidationError("session is expired or invalid")
        return BrowserSession(expires_at=expires_at, csrf_token=csrf_token)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
