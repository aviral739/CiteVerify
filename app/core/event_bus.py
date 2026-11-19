"""In-memory asynchronous event bus for broadcasting pipeline events to SSE clients."""

import asyncio
from typing import Any, AsyncGenerator, Dict, Set


class EventBus:
    """Manages document-scoped asyncio queues for real-time Server-Sent Events."""

    def __init__(self):
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, document_id: str, event_data: Dict[str, Any]) -> None:
        """Publish an event to all active subscribers for the document."""
        async with self._lock:
            queues = list(self._subscribers.get(document_id, set()))

        for queue in queues:
            try:
                queue.put_nowait(event_data)
            except (asyncio.QueueFull, Exception):
                pass

    async def subscribe(self, document_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to live events for a document."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            if document_id not in self._subscribers:
                self._subscribers[document_id] = set()
            self._subscribers[document_id].add(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                if document_id in self._subscribers:
                    self._subscribers[document_id].discard(queue)
                    if not self._subscribers[document_id]:
                        del self._subscribers[document_id]


event_bus = EventBus()
