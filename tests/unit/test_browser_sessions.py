from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from morpheus.api.session import (
    MIN_SESSION_NONCE_LENGTH,
    SessionCodec,
    SessionValidationError,
    _encode,
)

NOW = datetime(2026, 7, 16, tzinfo=UTC)
SECRET = b"session-test-secret"


def test_SEC_004_signed_browser_session_expires_and_exposes_csrf_value() -> None:
    codec = SessionCodec(secret=SECRET, ttl_seconds=60)

    token, issued = codec.issue(now=NOW)
    verified = codec.verify(token, now=NOW + timedelta(seconds=59))

    assert verified == issued
    with pytest.raises(SessionValidationError):
        codec.verify(token, now=NOW + timedelta(seconds=60))


def test_SEC_004_issued_session_carries_nonce_through_verify() -> None:
    codec = SessionCodec(secret=SECRET, ttl_seconds=60)

    token, issued = codec.issue(now=NOW)
    verified = codec.verify(token, now=NOW)

    assert isinstance(issued.nonce, str)
    assert len(issued.nonce) >= MIN_SESSION_NONCE_LENGTH
    assert verified.nonce == issued.nonce
    assert verified == issued


def test_SEC_004_session_cookie_is_reusable_until_expiry() -> None:
    codec = SessionCodec(secret=SECRET, ttl_seconds=60)
    token, issued = codec.issue(now=NOW)

    assert codec.verify(token, now=NOW) == issued
    assert codec.verify(token, now=NOW + timedelta(seconds=1)) == issued


@pytest.mark.parametrize("nonce", ["", "short-nonce"])
def test_SEC_004_rejects_empty_or_short_session_nonce(nonce: str) -> None:
    codec = SessionCodec(secret=SECRET, ttl_seconds=60)
    token = _signed_payload(
        {
            "csrf": "csrf-token-with-enough-entropy",
            "exp": int(NOW.timestamp()) + 60,
            "nonce": nonce,
            "v": 1,
        }
    )

    with pytest.raises(SessionValidationError):
        codec.verify(token, now=NOW)


@pytest.mark.parametrize("token", ["", "broken", "a.b.c", "eyJ2IjoxfQ.signature"])
def test_SEC_004_rejects_malformed_or_tampered_browser_sessions(token: str) -> None:
    codec = SessionCodec(secret=SECRET, ttl_seconds=60)
    if token == "":
        token, _ = codec.issue(now=NOW)
        token = f"{token}x"

    with pytest.raises(SessionValidationError):
        codec.verify(token, now=NOW)


def _signed_payload(payload: dict[str, object]) -> str:
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _encode(hmac.new(SECRET, encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"
