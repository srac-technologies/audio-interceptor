"""Per-slug graphic-recording pipeline.

One :class:`ViewerPipeline` per Meet topic. Internal subscriber on the broker
receives transcript messages, accumulates them through the canvas chunker,
calls the LLM on each completed chunk, mutates an :class:`IRState`, and
publishes a snapshot back onto the same topic (type=``snapshot``) so the
viewer's browser WS gets it through the standard fan-out.

Re-renders happen on every IR mutation. Each snapshot carries the active view
mode; clients can request a different one via the viewer router which calls
:meth:`set_view_mode` here.

Graphic-recording can be toggled off at runtime via :meth:`set_enabled`.
When disabled the pipeline still records transcripts (so reconnecting clients
can see the backlog) but skips LLM calls and snapshot publishes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any

from ..broker import Broker
from .canvas.chunker import StreamingChunker
from .canvas.ir import IRState, apply_llm_result
from .canvas.views import DEFAULT_VIEW, VIEW_MODES, render_view
from .llm import LLMConfig, LLMError, call_llm

logger = logging.getLogger(__name__)


_MAX_TRANSCRIPT_LOG = 200


class ViewerPipeline:
    """Lifecycle: ``start()`` registers with the broker, ``stop()`` unregisters.

    Re-entrant safe: multiple browser WS clients can share one pipeline; the
    broker fan-out delivers each snapshot to all of them.
    """

    def __init__(
        self,
        *,
        slug: str,
        broker: Broker,
        llm_config: LLMConfig,
        chunk_min_chars: int = 60,
        chunk_flush_chars: int = 140,
    ) -> None:
        self.slug = slug
        self._broker = broker
        self._llm_config = llm_config
        self._chunker = StreamingChunker(
            min_chars=chunk_min_chars, flush_chars=chunk_flush_chars
        )
        self._ir = IRState()
        self._view_mode = DEFAULT_VIEW
        self._enabled = True
        self._transcripts: list[dict[str, Any]] = []  # for render_transcript
        # Queue + worker so the broker callback returns quickly. LLM calls
        # are slow (seconds) and we don't want to back-pressure the broker.
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=64)
        self._worker_task: asyncio.Task | None = None
        self._llm_lock = asyncio.Lock()

    async def start(self) -> None:
        await self._broker.subscribe_internal(self.slug, self._on_broker_message)
        self._worker_task = asyncio.create_task(self._consume(), name=f"viewer-{self.slug}")
        logger.info("viewer pipeline started slug=%s", self.slug)

    async def stop(self) -> None:
        await self._broker.unsubscribe_internal(self.slug, self._on_broker_message)
        await self._queue.put(None)
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
        logger.info("viewer pipeline stopped slug=%s", self.slug)

    # ------------------------------------------------------------------ Public

    def set_view_mode(self, mode: str) -> None:
        if mode not in VIEW_MODES:
            raise ValueError(f"unknown view mode {mode!r}")
        self._view_mode = mode

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    @property
    def view_mode(self) -> str:
        return self._view_mode

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def publish_current_snapshot(self) -> None:
        """Force a re-render of the current IR and broadcast it.

        Used by the viewer router when a fresh client connects so it gets
        the latest snapshot without waiting for the next transcript.
        """
        await self._publish_snapshot(stats=None, chunk=None, latency=None)

    # ----- Broker callback -------------------------------------------------

    async def _on_broker_message(self, msg: dict[str, Any]) -> None:
        # Avoid snapshot → snapshot recursion: skip anything we generated.
        if msg.get("type") != "transcript":
            return
        text = msg.get("text") or ""
        if not isinstance(text, str) or not text.strip():
            return
        speaker = msg.get("speaker")
        ts = msg.get("ts") or _now_iso()
        self._transcripts.append({"text": text, "speaker": speaker, "ts": ts})
        if len(self._transcripts) > _MAX_TRANSCRIPT_LOG:
            del self._transcripts[: len(self._transcripts) - _MAX_TRANSCRIPT_LOG]
        if not self._enabled:
            return
        # Non-blocking put: if the queue is full the LLM is far behind and
        # we'd rather drop a chunk than back-pressure the broker.
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            logger.warning("viewer queue full for slug=%s, dropping chunk", self.slug)

    # ----- Worker loop -----------------------------------------------------

    async def _consume(self) -> None:
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    return
                if not self._enabled:
                    continue
                for chunk in self._chunker.feed(item + "\n"):
                    await self._process_chunk(chunk)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("viewer pipeline worker died slug=%s", self.slug)

    async def _process_chunk(self, chunk: str) -> None:
        # Serialize LLM calls per slug so we don't fan out N concurrent LLM
        # requests if the broker drops a flurry of transcripts. The chunker
        # is also stateful, so per-pipeline serial is the correct semantics.
        async with self._llm_lock:
            t0 = time.time()
            try:
                summary = self._ir.summary()
                result = await call_llm(self._llm_config, chunk, summary)
            except LLMError as exc:
                logger.warning("LLM call failed for slug=%s: %s", self.slug, exc)
                await self._broker.publish(
                    self.slug,
                    {
                        "type": "viewer_error",
                        "detail": str(exc),
                        "ts": _now_iso(),
                    },
                )
                return
            stats = apply_llm_result(self._ir, result)
            latency = time.time() - t0
        await self._publish_snapshot(
            stats=stats, chunk=chunk, latency=latency,
        )

    async def _publish_snapshot(
        self,
        *,
        stats: dict[str, int] | None,
        chunk: str | None,
        latency: float | None,
    ) -> None:
        try:
            view = render_view(self._ir, self._transcripts, self._view_mode)
        except Exception:  # noqa: BLE001
            logger.exception("render_view failed for slug=%s mode=%s", self.slug, self._view_mode)
            return
        msg: dict[str, Any] = {
            "type": "snapshot",
            "view_mode": self._view_mode,
            "view_type": view["view_type"],
            "content": view["content"],
            "node_count": len(self._ir.visible_nodes()),
            "edge_count": len(self._ir.visible_edges()),
            "enabled": self._enabled,
            "ts": _now_iso(),
        }
        if stats is not None:
            msg["stats"] = stats
        if chunk is not None:
            msg["chunk"] = chunk
        if latency is not None:
            msg["latency"] = round(latency, 2)
        await self._broker.publish(self.slug, msg)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
