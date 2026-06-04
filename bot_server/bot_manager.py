"""Session lifecycle: spawn / track / leave per-meeting bot workers.

Phase 1 ships only a *dummy* publisher — no real Meet bot yet. The shape of
:class:`BotSession` is intentionally aligned with the eventual Phase 2 worker
(start + stop + a per-session async task) so swapping in the real subprocess
becomes a one-class change.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .broker import Broker
from .settings import Settings

# Meet meeting codes are conventionally lowercase ASCII letters in three
# hyphen-separated groups (xxx-yyyy-zzz). We accept a slightly wider charset
# to be forward-compatible with whatever Google ships next, but reject
# anything with whitespace / path separators / URL artifacts so an
# accidental free-text paste doesn't become a routable topic.
_TOPIC_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")

logger = logging.getLogger("bot_server.bot_manager")


_DUMMY_PHRASES = [
    "テスト発話: bot_server スケルトン経由のダミー文字起こしです。",
    "Topic broker と WebSocket fan-out の疎通確認中。",
    "次の Phase 2 で実際の Meet 入場と faster-whisper を接続します。",
    "/bot/leave/<topic> を叩くとこのセッションは止まります。",
    "Auth は Authorization: Bearer <BOT_TOKEN> です。",
]


class BotSession:
    """One per active meeting topic. Owns its publisher task and status."""

    def __init__(
        self,
        topic_key: str,
        meet_url: str,
        display_name: str | None,
        broker: Broker,
        settings: Settings,
    ) -> None:
        self.topic_key = topic_key
        self.meet_url = meet_url
        self.display_name = display_name
        self.started_at = datetime.now(timezone.utc)
        self._broker = broker
        self._settings = settings
        self._publisher_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._broker.publish(
            self.topic_key,
            {
                "type": "status",
                "state": "joining",
                "topic_key": self.topic_key,
                "meet_url": self.meet_url,
                "ts": _now_iso(),
            },
        )
        # Phase 1: dummy publisher only. Phase 2 will replace this with a
        # subprocess launch of the actual Meet worker.
        if self._settings.dummy_publisher_enabled:
            self._publisher_task = asyncio.create_task(self._dummy_loop())
        await self._broker.publish(
            self.topic_key,
            {
                "type": "status",
                "state": "joined",
                "topic_key": self.topic_key,
                "ts": _now_iso(),
            },
        )

    async def stop(self) -> None:
        if self._publisher_task is not None:
            self._publisher_task.cancel()
            try:
                await self._publisher_task
            except asyncio.CancelledError:
                pass
            self._publisher_task = None
        await self._broker.publish(
            self.topic_key,
            {
                "type": "status",
                "state": "left",
                "topic_key": self.topic_key,
                "ts": _now_iso(),
            },
        )

    async def _dummy_loop(self) -> None:
        i = 0
        try:
            while True:
                await asyncio.sleep(self._settings.dummy_publisher_interval_seconds)
                text = _DUMMY_PHRASES[i % len(_DUMMY_PHRASES)]
                i += 1
                await self._broker.publish(
                    self.topic_key,
                    {
                        "type": "transcript",
                        "source": "meet",
                        "speaker": self.display_name or "DummyBot",
                        "text": text,
                        "ts": _now_iso(),
                    },
                )
        except asyncio.CancelledError:
            raise


class BotManager:
    """Tracks active sessions, enforces concurrency caps, extracts topic keys."""

    def __init__(self, broker: Broker, settings: Settings) -> None:
        self._broker = broker
        self._settings = settings
        self._sessions: dict[str, BotSession] = {}
        self._lock = asyncio.Lock()

    async def join(
        self, meet_url: str, display_name: str | None = None
    ) -> tuple[str, BotSession]:
        topic_key = self._extract_topic_key(meet_url)
        async with self._lock:
            existing = self._sessions.get(topic_key)
            if existing is not None:
                return topic_key, existing
            if len(self._sessions) >= self._settings.max_concurrent_meetings:
                raise CapacityError(
                    f"at capacity ({self._settings.max_concurrent_meetings} meetings)"
                )
            session = BotSession(
                topic_key=topic_key,
                meet_url=meet_url,
                display_name=display_name,
                broker=self._broker,
                settings=self._settings,
            )
            self._sessions[topic_key] = session
        await session.start()
        logger.info("joined topic=%s meet_url=%s", topic_key, meet_url)
        return topic_key, session

    async def leave(self, topic_key: str) -> bool:
        async with self._lock:
            session = self._sessions.pop(topic_key, None)
        if session is None:
            return False
        await session.stop()
        logger.info("left topic=%s", topic_key)
        return True

    async def leave_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            try:
                await s.stop()
            except Exception:  # noqa: BLE001
                logger.exception("leave_all: stop raised for %s", s.topic_key)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "topic_key": s.topic_key,
                "meet_url": s.meet_url,
                "display_name": s.display_name,
                "started_at": s.started_at.isoformat(),
                "subscribers": self._broker.subscriber_count(s.topic_key),
            }
            for s in self._sessions.values()
        ]

    @staticmethod
    def _extract_topic_key(meet_url: str) -> str:
        # Accept either a full URL (https://meet.google.com/abc-defg-hij) or
        # a bare meeting code (abc-defg-hij). The Chrome extension will pass
        # the full URL of the active tab; CLI users may pass either.
        candidate = meet_url.strip()
        if "://" in candidate:
            parsed = urlparse(candidate)
            if parsed.hostname and "meet.google.com" not in parsed.hostname:
                raise ValueError(
                    f"only meet.google.com URLs are accepted, got host={parsed.hostname!r}"
                )
            path = parsed.path.strip("/")
            if not path:
                raise ValueError(f"no meeting code in URL: {meet_url!r}")
            candidate = path.split("/", 1)[0]
        # Strip query/fragment artifacts a user might paste in by accident.
        candidate = candidate.split("?", 1)[0].split("#", 1)[0]
        if not candidate:
            raise ValueError(f"empty topic key from: {meet_url!r}")
        if not _TOPIC_KEY_RE.match(candidate):
            raise ValueError(
                f"topic key {candidate!r} is not a valid Meet meeting code "
                "(expected pattern: alphanumerics with - or _, 3-64 chars)"
            )
        return candidate


class CapacityError(RuntimeError):
    """Raised when MAX_CONCURRENT_MEETINGS would be exceeded."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
