"""In-memory topic broker for WebSocket fan-out.

Single-process pub/sub keyed by `topic_key` (Meet meeting code). One instance
is created per server process and shared across all routes + the BotManager.

Trade-offs (Phase 1): no persistence, no horizontal scaling. If we ever need
multiple bot_server replicas behind a load balancer, swap this for Redis
pub/sub — the API surface (subscribe / unsubscribe / publish) is deliberately
narrow to make that migration cheap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("bot_server.broker")


InternalSubscriber = Callable[[dict[str, Any]], Awaitable[None]]
"""In-process async callback that gets every published message for a topic.

Used by :class:`bot_server.viewer.pipeline.ViewerPipeline` so the viewer can
react to transcripts without round-tripping through a websocket.
"""


class Broker:
    def __init__(self) -> None:
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._internal: dict[str, set[InternalSubscriber]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subs[topic].add(ws)
            count = len(self._subs[topic])
        logger.info("subscribe topic=%s subs=%d", topic, count)

    async def unsubscribe(self, topic: str, ws: WebSocket) -> None:
        async with self._lock:
            bucket = self._subs.get(topic)
            if bucket is None:
                return
            bucket.discard(ws)
            if not bucket:
                # Free the bucket so `topics()` doesn't report ghost rooms.
                del self._subs[topic]
                remaining = 0
            else:
                remaining = len(bucket)
        logger.info("unsubscribe topic=%s subs=%d", topic, remaining)

    async def publish(self, topic: str, message: dict[str, Any]) -> int:
        """Send `message` (JSON-encoded) to every subscriber of `topic`.

        Both external WebSocket subscribers and in-process internal callbacks
        are notified. Returns the number of WebSocket subscribers the message
        was successfully delivered to. Dead WSs are evicted; internal callback
        exceptions are logged but don't propagate.
        """
        text = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            ws_subs = list(self._subs.get(topic, set()))
            internal_subs = list(self._internal.get(topic, set()))

        # External WS subscribers (the public surface).
        dead: list[WebSocket] = []
        delivered = 0
        for ws in ws_subs:
            try:
                await ws.send_text(text)
                delivered += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("publish: dropping dead ws on topic=%s: %s", topic, exc)
                dead.append(ws)
        if dead:
            async with self._lock:
                bucket = self._subs.get(topic)
                if bucket is not None:
                    for ws in dead:
                        bucket.discard(ws)
                    if not bucket:
                        del self._subs[topic]

        # Internal in-process subscribers (e.g. viewer pipeline). These don't
        # block the public WS path; we run them sequentially since they're
        # expected to be cheap (enqueue into a per-pipeline asyncio.Queue).
        for cb in internal_subs:
            try:
                await cb(message)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "publish: internal subscriber for topic=%s raised", topic
                )

        return delivered

    async def subscribe_internal(self, topic: str, callback: InternalSubscriber) -> None:
        async with self._lock:
            self._internal[topic].add(callback)
            count = len(self._internal[topic])
        logger.info("subscribe_internal topic=%s subs=%d", topic, count)

    async def unsubscribe_internal(
        self, topic: str, callback: InternalSubscriber
    ) -> None:
        async with self._lock:
            bucket = self._internal.get(topic)
            if bucket is None:
                return
            bucket.discard(callback)
            if not bucket:
                del self._internal[topic]

    def subscriber_count(self, topic: str) -> int:
        return len(self._subs.get(topic, set()))

    def internal_subscriber_count(self, topic: str) -> int:
        return len(self._internal.get(topic, set()))

    def topics(self) -> list[str]:
        return list(self._subs.keys())
