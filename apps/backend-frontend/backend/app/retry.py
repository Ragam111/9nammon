"""Exponential backoff for calls that may fail transiently. Only retryable errors are retried."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

MAX_DELAY_S = 8.0


def backoff_delay(attempt: int, base_s: float) -> float:
    """Delay before retry number `attempt` (1-based): base, 2*base, 4*base ... capped at MAX_DELAY_S."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    return min(MAX_DELAY_S, base_s * (2 ** (attempt - 1)))


async def with_retry[T](
    call: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    base_delay_s: float,
    is_retryable: Callable[[BaseException], bool],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run `call`; on a retryable error wait and try again, up to `max_retries` extra attempts."""
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            attempt += 1
            if attempt > max_retries or not is_retryable(exc):
                raise
            await sleep(backoff_delay(attempt, base_delay_s))
