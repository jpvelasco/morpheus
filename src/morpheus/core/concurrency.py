from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class RetryDeadlineExceeded(TimeoutError):
    """A retry operation exhausted its monotonic deadline."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retries for explicitly idempotent operations only."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    deadline_seconds: float = 15.0
    jitter_ratio: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry max_attempts must be positive")
        if self.initial_delay_seconds <= 0 or self.max_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        if self.initial_delay_seconds > self.max_delay_seconds:
            raise ValueError("retry initial delay cannot exceed maximum delay")
        if self.deadline_seconds <= 0:
            raise ValueError("retry deadline must be positive")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("retry jitter ratio must be between zero and one")

    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        retryable: Callable[[Exception], bool],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fraction: Callable[[], float] = random.random,
    ) -> T:
        deadline = monotonic() + self.deadline_seconds
        for attempt in range(1, self.max_attempts + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RetryDeadlineExceeded("retry deadline elapsed before an attempt could start")
            try:
                async with asyncio.timeout(remaining):
                    return await operation()
            except Exception as error:
                if attempt == self.max_attempts or not retryable(error):
                    raise
                delay = self._delay(attempt=attempt, random_fraction=random_fraction)
                if delay >= deadline - monotonic():
                    raise RetryDeadlineExceeded(
                        "retry deadline elapsed before the next attempt"
                    ) from error
                await sleep(delay)
        raise AssertionError("retry attempts must either return or raise")

    def _delay(self, *, attempt: int, random_fraction: Callable[[], float]) -> float:
        base = min(self.max_delay_seconds, self.initial_delay_seconds * (2 ** (attempt - 1)))
        random_value = min(1.0, max(0.0, random_fraction()))
        multiplier = 1 - self.jitter_ratio + (2 * self.jitter_ratio * random_value)
        return float(base * multiplier)


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
