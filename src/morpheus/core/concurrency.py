from __future__ import annotations

import asyncio
import time


class ConcurrencyLimiter:
    """A small non-queueing admission controller for bounded request work."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("concurrency limit must be positive")
        self._limit = limit
        self._in_flight = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._in_flight >= self._limit:
                return False
            self._in_flight += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._in_flight <= 0:
                raise RuntimeError("cannot release a concurrency slot that was not acquired")
            self._in_flight -= 1


class FixedWindowRateLimiter:
    """A bounded in-memory rate limiter for one local service process."""

    def __init__(self, limit: int, *, window_seconds: float = 60) -> None:
        if limit < 1:
            raise ValueError("rate limit must be positive")
        if window_seconds <= 0:
            raise ValueError("rate limit window must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._entries: dict[str, tuple[float, int]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str, *, now: float | None = None) -> bool:
        observed_at = time.monotonic() if now is None else now
        async with self._lock:
            started_at, used = self._entries.get(key, (observed_at, 0))
            if observed_at - started_at >= self._window_seconds:
                started_at, used = observed_at, 0
            if used >= self._limit:
                self._entries[key] = (started_at, used)
                return False
            self._entries[key] = (started_at, used + 1)
            return True
