"""只读 Runtime 事件订阅与缓冲转发。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from queue import Empty, Full, Queue

from pydantic import BaseModel, ConfigDict

from runtime.taskboard import CollaborationEvent, EventVisibility


class HookSubscription(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    handler: Callable[[CollaborationEvent], None]
    min_visibility: EventVisibility


_VISIBILITY_RANK = {
    EventVisibility.DEVELOPER: 0,
    EventVisibility.ADMIN: 1,
    EventVisibility.USER: 2,
}


def _meets_visibility(
    event_visibility: EventVisibility,
    min_visibility: EventVisibility,
) -> bool:
    return _VISIBILITY_RANK[event_visibility] >= _VISIBILITY_RANK[min_visibility]


class HookDispatcher:
    """异常隔离的 Observer；订阅者只收到事件的深拷贝。"""

    def __init__(self) -> None:
        self._subscriptions: list[HookSubscription] = []

    def subscribe(
        self,
        handler: Callable[[CollaborationEvent], None],
        *,
        min_visibility: EventVisibility = EventVisibility.USER,
    ) -> None:
        self._subscriptions.append(HookSubscription(
            handler=handler,
            min_visibility=min_visibility,
        ))

    def dispatch(self, event: CollaborationEvent) -> None:
        for subscription in tuple(self._subscriptions):
            if not _meets_visibility(event.visibility, subscription.min_visibility):
                continue
            try:
                subscription.handler(event.model_copy(deep=True))
            except Exception:
                continue


class BufferedEventForwarder:
    """Runtime 路径只入队；外部 I/O 由独立异步消费者执行。"""

    def __init__(self, *, max_queue_size: int = 1_000) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self._queue: Queue[CollaborationEvent] = Queue(maxsize=max_queue_size)
        self.dropped_count = 0

    def enqueue(self, event: CollaborationEvent) -> None:
        try:
            self._queue.put_nowait(event.model_copy(deep=True))
        except Full:
            self.dropped_count += 1

    async def forward_one(
        self,
        sender: Callable[[CollaborationEvent], Awaitable[None]],
        *,
        timeout: float | None = None,
    ) -> bool:
        try:
            event = await asyncio.to_thread(self._queue.get, True, timeout)
        except Empty:
            return False
        try:
            await sender(event)
        finally:
            self._queue.task_done()
        return True


__all__ = ["BufferedEventForwarder", "HookDispatcher", "HookSubscription"]
