from __future__ import annotations

import pytest

from morpheus.core.concurrency import (
    ConcurrencyLimiter,
    FixedWindowRateLimiter,
    RetryDeadlineExceeded,
    RetryPolicy,
)


@pytest.mark.asyncio
async def test_SEC_003_concurrency_limiter_rejects_work_instead_of_queueing() -> None:
    limiter = ConcurrencyLimiter(1)

    assert await limiter.try_acquire() is True
    assert await limiter.try_acquire() is False
    await limiter.release()
    assert await limiter.try_acquire() is True


@pytest.mark.asyncio
async def test_SEC_003_concurrency_limiter_rejects_unmatched_release() -> None:
    with pytest.raises(RuntimeError, match="not acquired"):
        await ConcurrencyLimiter(1).release()


def test_SEC_003_concurrency_limiter_rejects_nonpositive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        ConcurrencyLimiter(0)


@pytest.mark.asyncio
async def test_SEC_003_rate_limiter_rejects_excess_work_and_resets_its_window() -> None:
    limiter = FixedWindowRateLimiter(2, window_seconds=60)

    assert await limiter.allow("client", now=100) is True
    assert await limiter.allow("client", now=101) is True
    assert await limiter.allow("client", now=102) is False
    assert await limiter.allow("other-client", now=102) is True
    assert await limiter.allow("client", now=160) is True


@pytest.mark.parametrize("limit", [0, -1])
def test_SEC_003_rate_limiter_rejects_nonpositive_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        FixedWindowRateLimiter(limit)


@pytest.mark.asyncio
async def test_REL_002_retry_policy_uses_bounded_exponential_backoff_with_jitter() -> None:
    now = [0.0]
    delays: list[float] = []
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("transient")
        return "ready"

    async def sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    policy = RetryPolicy(
        max_attempts=3,
        initial_delay_seconds=1,
        max_delay_seconds=4,
        deadline_seconds=10,
        jitter_ratio=0.5,
    )

    assert (
        await policy.run(
            operation,
            retryable=lambda error: isinstance(error, ConnectionError),
            monotonic=lambda: now[0],
            sleep=sleep,
            random_fraction=lambda: 1.0,
        )
        == "ready"
    )
    assert calls == 3
    assert delays == [1.5, 3.0]


@pytest.mark.asyncio
async def test_REL_002_retry_policy_stops_before_its_monotonic_deadline() -> None:
    now = [0.0]
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("transient")

    async def sleep(delay: float) -> None:
        now[0] += delay

    policy = RetryPolicy(
        max_attempts=5,
        initial_delay_seconds=1,
        max_delay_seconds=4,
        deadline_seconds=1.5,
        jitter_ratio=0,
    )

    with pytest.raises(RetryDeadlineExceeded, match="deadline"):
        await policy.run(
            operation,
            retryable=lambda error: isinstance(error, ConnectionError),
            monotonic=lambda: now[0],
            sleep=sleep,
        )
    assert calls == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"initial_delay_seconds": 2, "max_delay_seconds": 1},
        {"deadline_seconds": 0},
        {"jitter_ratio": 1.1},
    ],
)
def test_REL_002_retry_policy_rejects_unbounded_or_invalid_configuration(
    kwargs: dict[str, float | int],
) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


@pytest.mark.asyncio
async def test_REL_002_retry_policy_does_not_start_work_after_its_deadline() -> None:
    observations = iter([0.0, 2.0])
    started = False

    async def operation() -> None:
        nonlocal started
        started = True

    with pytest.raises(RetryDeadlineExceeded, match="before an attempt"):
        await RetryPolicy(deadline_seconds=1).run(
            operation,
            retryable=lambda error: isinstance(error, ConnectionError),
            monotonic=lambda: next(observations),
        )
    assert started is False
