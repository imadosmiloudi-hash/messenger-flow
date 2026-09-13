"""In-process SSE event bus for realtime UI updates."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[int, asyncio.Queue] = {}
        self._next_id = 0
        self._lock = asyncio.Lock()

    async def subscribe(self) -> tuple[int, asyncio.Queue]:
        async with self._lock:
            sid = self._next_id
            self._next_id += 1
            q: asyncio.Queue = asyncio.Queue(maxsize=100)
            self._subscribers[sid] = q
            return sid, q

    async def unsubscribe(self, sid: int) -> None:
        async with self._lock:
            self._subscribers.pop(sid, None)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        payload = {"type": event_type, "data": data}
        async with self._lock:
            dead = []
            for sid, q in self._subscribers.items():
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(sid)
            for sid in dead:
                self._subscribers.pop(sid, None)

    def publish_sync(self, event_type: str, data: dict[str, Any]) -> None:
        """Best-effort sync publish from worker threads via Redis pubsub fallback note.
        For RQ workers we also push to Redis channel; API SSE listens if configured.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.publish(event_type, data))
            else:
                loop.run_until_complete(self.publish(event_type, data))
        except RuntimeError:
            # No loop in this thread — use Redis
            try:
                import redis
                from app.config import get_settings

                r = redis.from_url(get_settings().redis_url)
                r.publish(
                    "messenger_events",
                    json.dumps({"type": event_type, "data": data}),
                )
            except Exception:
                pass


event_bus = EventBus()
