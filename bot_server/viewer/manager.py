"""Per-slug pipeline pool with reference-counted lifecycle + idle GC.

Browsers acquire/release a pipeline as they connect/disconnect. The pipeline
sticks around for ``idle_evict_seconds`` after the last release so a quick
reload doesn't burn an LLM cold-start.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ..broker import Broker
from .llm import LLMConfig
from .pipeline import ViewerPipeline

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    pipeline: ViewerPipeline
    refcount: int = 0
    last_released_at: float = field(default_factory=time.time)


class ViewerManager:
    def __init__(
        self,
        *,
        broker: Broker,
        llm_config: LLMConfig,
        idle_evict_seconds: float = 120.0,
        sweep_interval_seconds: float = 30.0,
    ) -> None:
        self._broker = broker
        self._llm_config = llm_config
        self._idle_evict_seconds = idle_evict_seconds
        self._sweep_interval_seconds = sweep_interval_seconds
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._sweeper: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        self._sweeper = asyncio.create_task(self._sweep(), name="viewer-sweeper")

    async def stop(self) -> None:
        self._shutdown.set()
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for e in entries:
            try:
                await e.pipeline.stop()
            except Exception:  # noqa: BLE001
                logger.exception("stop pipeline raised")

    async def acquire(self, slug: str) -> ViewerPipeline:
        async with self._lock:
            entry = self._entries.get(slug)
            if entry is None:
                pipeline = ViewerPipeline(
                    slug=slug, broker=self._broker, llm_config=self._llm_config,
                )
                entry = _Entry(pipeline=pipeline, refcount=0)
                self._entries[slug] = entry
                created = True
            else:
                created = False
            entry.refcount += 1
        if created:
            await entry.pipeline.start()
        return entry.pipeline

    async def release(self, slug: str) -> None:
        async with self._lock:
            entry = self._entries.get(slug)
            if entry is None:
                return
            entry.refcount = max(0, entry.refcount - 1)
            entry.last_released_at = time.time()

    def get(self, slug: str) -> ViewerPipeline | None:
        entry = self._entries.get(slug)
        return entry.pipeline if entry else None

    def list_slugs(self) -> list[dict]:
        return [
            {
                "slug": slug,
                "refcount": e.refcount,
                "view_mode": e.pipeline.view_mode,
                "enabled": e.pipeline.enabled,
                "idle_seconds": round(time.time() - e.last_released_at, 1) if e.refcount == 0 else 0.0,
            }
            for slug, e in self._entries.items()
        ]

    async def _sweep(self) -> None:
        try:
            while not self._shutdown.is_set():
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(), timeout=self._sweep_interval_seconds,
                    )
                    return  # shutdown signalled
                except asyncio.TimeoutError:
                    pass
                await self._evict_idle()
        except asyncio.CancelledError:
            raise

    async def _evict_idle(self) -> None:
        now = time.time()
        async with self._lock:
            victims = [
                slug
                for slug, e in self._entries.items()
                if e.refcount == 0
                and (now - e.last_released_at) >= self._idle_evict_seconds
            ]
            entries = [self._entries.pop(slug) for slug in victims]
        for slug, e in zip(victims, entries):
            logger.info("evicting idle viewer pipeline slug=%s", slug)
            try:
                await e.pipeline.stop()
            except Exception:  # noqa: BLE001
                logger.exception("idle eviction stop raised slug=%s", slug)
