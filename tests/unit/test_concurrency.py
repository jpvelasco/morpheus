from __future__ import annotations

import pytest

from morpheus.core.concurrency import ConcurrencyLimiter, FixedWindowRateLimiter


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
