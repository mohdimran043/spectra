"""In-process pub/sub for investigation traces.

The API layer adapts :class:`TraceBroker` to SSE.  Queues are bounded and drop
the oldest step rather than blocking, because a stalled browser tab must never
stall an investigation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from spectra_config.logging import get_logger
from spectra_schemas import TraceStep

from .thresholds import TRACE_QUEUE_SIZE

log = get_logger(__name__)

_SENTINEL: object = object()


class TraceBroker:
    """Fan-out of :class:`TraceStep` objects keyed by investigation id."""

    def __init__(self, queue_size: int = TRACE_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._dropped = 0

    @property
    def dropped_steps(self) -> int:
        return self._dropped

    def subscriber_count(self, investigation_id: str) -> int:
        return len(self._subscribers.get(investigation_id, ()))

    async def publish(self, step: TraceStep) -> None:
        for queue in list(self._subscribers.get(step.investigation_id, ())):
            self._offer(queue, step)

    def _offer(self, queue: asyncio.Queue, item: object) -> None:
        try:
            queue.put_nowait(item)
            return
        except asyncio.QueueFull:
            self._dropped += 1
        try:
            queue.get_nowait()  # drop oldest, never block the agent
            queue.put_nowait(item)
        except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - race only
            log.warning("trace.drop_failed", investigation_id=getattr(item, "investigation_id", ""))

    async def subscribe(self, investigation_id: str) -> AsyncIterator[TraceStep]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(investigation_id, set()).add(queue)
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    return
                yield item  # type: ignore[misc]
        finally:
            self._unsubscribe(investigation_id, queue)

    def _unsubscribe(self, investigation_id: str, queue: asyncio.Queue) -> None:
        holders = self._subscribers.get(investigation_id)
        if not holders:
            return
        holders.discard(queue)
        if not holders:
            self._subscribers.pop(investigation_id, None)

    async def close(self, investigation_id: str) -> None:
        """End every stream for one investigation."""
        for queue in list(self._subscribers.get(investigation_id, ())):
            self._offer(queue, _SENTINEL)

    async def close_all(self) -> None:
        for investigation_id in list(self._subscribers):
            await self.close(investigation_id)
