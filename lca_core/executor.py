"""Shared ThreadPoolExecutor of 2 workers, plus an optional gc.collect hook.

The pool is created on first use and stays at 2 workers (4C/4T, 8GB RAM).
Nothing starts at import. Call ``shutdown_executor`` from tests and process exit.
"""

from __future__ import annotations

import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from lca_core.constants import POOL_WORKERS

__all__ = ["GcHook", "get_executor", "shutdown_executor", "submit"]

_executor: ThreadPoolExecutor | None = None
_guard = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    global _executor
    with _guard:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=POOL_WORKERS,
                thread_name_prefix="lca-core",
            )
        return _executor


def shutdown_executor(*, wait: bool = True) -> None:
    global _executor
    with _guard:
        current = _executor
        _executor = None
    if current is not None:
        current.shutdown(wait=wait)


def submit(fn, *args):
    return get_executor().submit(fn, *args)


class GcHook:
    """Caller-driven collector. It does not start a thread.

    ``enabled`` defaults to False. ``maybe_collect`` runs at most once per interval.
    """

    def __init__(self, interval_s: float = 60.0, enabled: bool = False, collect=None):
        self.interval_s = float(interval_s)
        self.enabled = bool(enabled)
        self._collect = collect or gc.collect
        self._last: float | None = None
        self.runs = 0

    def maybe_collect(self, now: float | None = None) -> bool:
        if not self.enabled:
            return False
        moment = time.monotonic() if now is None else float(now)
        if self._last is not None and (moment - self._last) < self.interval_s:
            return False
        self._collect()
        self._last = moment
        self.runs += 1
        return True
