"""L3 — in-process pub/sub with a bounded asyncio.Queue per subscriber.

Overflow is ``drop-oldest`` or ``reject``. No threads are started here.
"""

from __future__ import annotations

import asyncio
from typing import Any

from lca_core.constants import QUEUE_MAXSIZE

__all__ = ["EventBus"]


def _copy(event: Any) -> Any:
    if isinstance(event, dict):
        return dict(event)
    return event


class EventBus:
    def __init__(self, maxsize: int = QUEUE_MAXSIZE, overflow: str = "drop-oldest"):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if overflow not in ("drop-oldest", "reject"):
            raise ValueError("overflow must be drop-oldest or reject")
        self.maxsize = int(maxsize)
        self.overflow = overflow
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, topic: str) -> asyncio.Queue:
        if not topic:
            raise ValueError("topic is required")
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self._subs.setdefault(topic, []).append(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        subs = self._subs.get(topic)
        if not subs:
            return
        self._subs[topic] = [item for item in subs if item is not queue]

    def publish(self, topic: str, event: Any) -> int:
        """Fan-out to current subscribers. Returns how many queues accepted it.

        Unknown topics accept nothing. Drive this from the event-loop thread.
        """
        accepted = 0
        for queue in list(self._subs.get(topic, ())):
            if self._offer(queue, event):
                accepted += 1
        return accepted

    async def publish_async(self, topic: str, event: Any) -> int:
        return self.publish(topic, event)

    def _offer(self, queue: asyncio.Queue, event: Any) -> bool:
        item = _copy(event)
        if self.overflow == "reject":
            if queue.full():
                return False
            queue.put_nowait(item)
            return True
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(item)
        return True
