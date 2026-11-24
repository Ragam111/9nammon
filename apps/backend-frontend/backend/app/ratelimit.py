"""Sliding-window rate limiter kept in memory (per process). Keys are e.g. 'user:3' or 'ip:1.2.3.4'."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from .errors import AppError

WINDOW_S = 60.0


class RateLimiter:
    """Allow at most `limit` hits per key in any 60-second window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> None:
        """Record a hit, or raise AppError('rate_limit') with retry_after_s when over the limit."""
        now = self._clock()
        with self._lock:
            self._sweep(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= WINDOW_S:
                hits.popleft()
            if len(hits) >= limit:
                wait = max(1, math.ceil(WINDOW_S - (now - hits[0])))
                raise AppError("rate_limit", retry_after_s=wait)
            hits.append(now)

    def _sweep(self, now: float) -> None:
        """Drop keys whose newest hit left the window, so memory does not grow with every IP seen.
        Runs at most once per window; caller holds the lock."""
        if now - getattr(self, "_last_sweep", 0.0) < WINDOW_S:
            return
        self._last_sweep = now
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= WINDOW_S]:
            del self._hits[key]

    def key_count(self) -> int:
        with self._lock:
            return len(self._hits)

    def remaining(self, key: str, limit: int) -> int:
        """How many hits are left in the current window (does not record a hit)."""
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key, deque())
            live = sum(1 for t in hits if now - t < WINDOW_S)
        return max(0, limit - live)
