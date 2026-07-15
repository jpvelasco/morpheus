from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta


class AgentAuthenticationError(ValueError):
    """Agent request authentication failed without exposing credential detail."""


def sign_request(key: bytes, *, timestamp: str, nonce: str, body: bytes) -> str:
    message = timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body
    return hmac.new(key, message, hashlib.sha256).hexdigest()


class AgentAuthenticator:
    def __init__(self, key: bytes, *, max_skew: timedelta = timedelta(seconds=30)) -> None:
        if len(key) < 16:
            raise ValueError("agent key must contain at least 16 bytes")
        self._key = key
        self._max_skew = max_skew
        self._nonces: dict[str, datetime] = {}

    def verify(
        self,
        *,
        timestamp: str,
        nonce: str,
        signature: str,
        body: bytes,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(UTC)
        try:
            supplied_time = datetime.fromtimestamp(int(timestamp), tz=UTC)
        except (ValueError, OverflowError) as error:
            raise AgentAuthenticationError("invalid request timestamp") from error
        if abs(current - supplied_time) > self._max_skew:
            raise AgentAuthenticationError("request timestamp is outside the allowed window")

        cutoff = current - self._max_skew
        self._nonces = {
            value: observed for value, observed in self._nonces.items() if observed >= cutoff
        }
        if not nonce or nonce in self._nonces:
            raise AgentAuthenticationError("request nonce was replayed")
        expected = sign_request(self._key, timestamp=timestamp, nonce=nonce, body=body)
        if not hmac.compare_digest(signature, expected):
            raise AgentAuthenticationError("invalid request signature")
        self._nonces[nonce] = current
