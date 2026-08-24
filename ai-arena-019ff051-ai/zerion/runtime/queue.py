"""
Priority Event Queue with Backpressure and Dead Letter Queue (DLQ)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, List, Optional
from zerion.runtime.events import Event


@dataclass(order=True)
class PrioritizedItem:
    priority: int
    item: Any = field(compare=False)


class PriorityEventQueue:
    def __init__(self, max_capacity: int = 10000, high_watermark: float = 0.85):
        self.max_capacity = max_capacity
        self.high_watermark = int(max_capacity * high_watermark)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_capacity)
        self._dead_letter_queue: List[Event] = []
        self._dropped_count: int = 0
        self._processed_count: int = 0

    @property
    def size(self) -> int:
        return self._queue.qsize()

    @property
    def is_under_backpressure(self) -> bool:
        return self._queue.qsize() >= self.high_watermark

    @property
    def dead_letter_queue(self) -> List[Event]:
        return list(self._dead_letter_queue)

    @property
    def stats(self) -> dict:
        return {
            "size": self.size,
            "max_capacity": self.max_capacity,
            "high_watermark": self.high_watermark,
            "is_backpressure": self.is_under_backpressure,
            "processed_count": self._processed_count,
            "dropped_count": self._dropped_count,
            "dlq_size": len(self._dead_letter_queue),
        }

    async def put(self, event: Event) -> bool:
        """
        Pushes an event into the queue based on inverted priority (lower number = higher priority in asyncio queue).
        If capacity is exceeded and event is low priority (< 80), send to DLQ.
        """
        if self._queue.full():
            if event.priority < 80:
                self._dead_letter_queue.append(event)
                self._dropped_count += 1
                return False
            else:
                # Critical events displace lowest priority in DLQ
                self._dead_letter_queue.append(event)
                return False

        # In asyncio.PriorityQueue, smallest number is retrieved first.
        # So we map priority (0-100) to (100 - priority).
        queue_priority = 100 - event.priority
        try:
            self._queue.put_nowait(PrioritizedItem(priority=queue_priority, item=event))
            return True
        except asyncio.QueueFull:
            self._dead_letter_queue.append(event)
            self._dropped_count += 1
            return False

    async def get(self) -> Event:
        item: PrioritizedItem = await self._queue.get()
        self._processed_count += 1
        return item.item

    def task_done(self):
        self._queue.task_done()

    def route_to_dlq(self, event: Event, reason: str = ""):
        event.payload["_dlq_reason"] = reason
        self._dead_letter_queue.append(event)
