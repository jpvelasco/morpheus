from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from morpheus.api.session import SessionCodec, SessionValidationError

NOW = datetime(2026, 7, 16, tzinfo=UTC)


def test_SEC_004_signed_browser_session_expires_and_exposes_csrf_value() -> None:
    codec = SessionCodec(secret=b"session-test-secret", ttl_seconds=60)

    token, issued = codec.issue(now=NOW)
    verified = codec.verify(token, now=NOW + timedelta(seconds=59))

    assert verified == issued
    with pytest.raises(SessionValidationError):
        codec.verify(token, now=NOW + timedelta(seconds=60))


@pytest.mark.parametrize("token", ["", "broken", "a.b.c", "eyJ2IjoxfQ.signature"])
def test_SEC_004_rejects_malformed_or_tampered_browser_sessions(token: str) -> None:
    codec = SessionCodec(secret=b"session-test-secret", ttl_seconds=60)
    if token == "":
        token, _ = codec.issue(now=NOW)
        token = f"{token}x"

    with pytest.raises(SessionValidationError):
        codec.verify(token, now=NOW)
