"""Session lifecycle: spawn / track / leave per-meeting bot workers.

Phase 2 wires up the actual Meet bot subprocess. The dummy publisher path
from Phase 1 is preserved (toggle via ``DUMMY_PUBLISHER=1``) so smoke tests
keep working without launching Playwright.

Real worker protocol (mirrors :mod:`bot_server.worker`):

  * stdout — one JSON object per line, ``{"type": "status"|"transcript", ...}``.
    Forwarded verbatim into :class:`Broker`.
  * stderr — free-form log lines. Re-emitted into the parent logger so it
    shows up alongside the bot_server's own logs.
  * SIGTERM — the worker shuts down gracefully (leaves the Meet, prints a
    final ``status:left``). We wait up to ``shutdown_timeout`` for the
    process to exit, then SIGKILL.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from .broker import Broker
from .settings import Settings

_TOPIC_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")

logger = logging.getLogger("bot_server.bot_manager")


_DUMMY_PHRASES = [
    "ダミー文字起こし: bot_server fan-out テスト用です。",
    "Meet bot の本体が起動していない時の代用。",
    "DUMMY_PUBLISHER=0 で停止できます。",
]


class BotSession:
    """One per active meeting topic. Owns either a worker subprocess (real)
    or an async task that emits dummy transcripts (Phase 1 fallback).
    """

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

        self._use_real_worker = not settings.dummy_publisher_enabled
        self._dummy_task: asyncio.Task[None] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._exit_task: asyncio.Task[None] | None = None
        # Track whether the worker already published a `status:left` over
        # stdout, so we don't follow it up with a duplicate on stop().
        self._left_emitted = False

    # ------------------------------------------------------------------ Public

    async def start(self) -> None:
        await self._publish(
            "status", state="joining", topic_key=self.topic_key, meet_url=self.meet_url,
        )
        if self._use_real_worker:
            await self._start_worker_subprocess()
        else:
            self._dummy_task = asyncio.create_task(self._dummy_loop())
            await self._publish(
                "status", state="joined", topic_key=self.topic_key,
                detail="dummy publisher",
            )

    async def stop(self) -> None:
        # Dummy first (Phase 1 fallback).
        if self._dummy_task is not None:
            self._dummy_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dummy_task
            self._dummy_task = None
            await self._publish(
                "status", state="left", topic_key=self.topic_key,
            )
            return

        # Real worker: SIGTERM → wait → SIGKILL.
        if self._proc is not None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(
                    self._proc.wait(),
                    timeout=self._settings.worker_shutdown_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "worker for topic=%s did not exit in %.0fs, killing",
                    self.topic_key,
                    self._settings.worker_shutdown_timeout_seconds,
                )
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
                with contextlib.suppress(Exception):
                    await self._proc.wait()
        for t in (self._stdout_task, self._stderr_task, self._exit_task):
            if t is None:
                continue
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        # Only publish our own `left` if the worker didn't already (clean
        # shutdown path emits it via stdout). Crash / SIGKILL paths don't,
        # in which case clients still see the closure here.
        if not self._left_emitted:
            await self._publish("status", state="left", topic_key=self.topic_key)

    # ----------------------------------------------------- Real worker path

    async def _start_worker_subprocess(self) -> None:
        cmd = [
            self._settings.worker_python,
            "-m",
            self._settings.worker_module,
            "--meet-url",
            self.meet_url,
            "--whisper-model",
            self._settings.whisper_model,
            "--whisper-language",
            self._settings.whisper_language,
            "--chunk-seconds",
            str(self._settings.chunk_seconds),
            "--admission-timeout",
            str(self._settings.admission_timeout_seconds),
            "--log-level",
            self._settings.log_level,
        ]
        if self.display_name:
            cmd.extend(["--display-name", self.display_name])
        if self._settings.worker_profile_dir_template:
            profile_dir = self._settings.worker_profile_dir_template.format(
                topic_key=self.topic_key,
            )
            cmd.extend(["--profile-dir", profile_dir])
        if self._settings.chrome_channel:
            cmd.extend(["--chrome-channel", self._settings.chrome_channel])
        if self._settings.worker_headless:
            cmd.append("--headless")

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        # The worker module lives in bot_server/; make sure the repo root is
        # on PYTHONPATH so `python -m bot_server.worker` resolves wherever
        # the parent was started.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

        logger.info("spawning worker: topic=%s cmd=%s", self.topic_key, cmd)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            await self._publish(
                "status", state="error", detail=f"worker_spawn_failed: {exc}",
                topic_key=self.topic_key,
            )
            raise

        self._stdout_task = asyncio.create_task(
            self._read_stdout(self._proc), name=f"stdout-{self.topic_key}"
        )
        self._stderr_task = asyncio.create_task(
            self._read_stderr(self._proc), name=f"stderr-{self.topic_key}"
        )
        self._exit_task = asyncio.create_task(
            self._watch_exit(self._proc), name=f"exit-{self.topic_key}"
        )

    async def _read_stdout(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            try:
                obj = json.loads(line.decode("utf-8").rstrip())
            except (UnicodeDecodeError, json.JSONDecodeError):
                logger.warning(
                    "worker[%s]: non-JSON on stdout: %r", self.topic_key, line
                )
                continue
            if not isinstance(obj, dict) or "type" not in obj:
                logger.debug("worker[%s]: dropping malformed: %r", self.topic_key, obj)
                continue
            # Tag every event with the topic_key + a server-stamped ts if
            # the worker didn't include one.
            obj.setdefault("topic_key", self.topic_key)
            obj.setdefault("ts", _now_iso())
            if obj.get("type") == "status" and obj.get("state") == "left":
                self._left_emitted = True
            await self._broker.publish(self.topic_key, obj)

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            try:
                text = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue
            logger.info("worker[%s]: %s", self.topic_key, text)

    async def _watch_exit(self, proc: asyncio.subprocess.Process) -> None:
        rc = await proc.wait()
        logger.info("worker[%s] exited rc=%d", self.topic_key, rc)
        if rc != 0:
            await self._publish(
                "status", state="error",
                detail=f"worker exited rc={rc}",
                topic_key=self.topic_key,
            )

    # ------------------------------------------------------ Dummy fallback

    async def _dummy_loop(self) -> None:
        i = 0
        try:
            while True:
                await asyncio.sleep(self._settings.dummy_publisher_interval_seconds)
                text = _DUMMY_PHRASES[i % len(_DUMMY_PHRASES)]
                i += 1
                await self._publish(
                    "transcript",
                    source="meet",
                    speaker=self.display_name or "DummyBot",
                    text=text,
                )
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------- Helpers

    async def _publish(self, type_: str, **fields) -> None:
        msg = {"type": type_, "ts": _now_iso(), **fields}
        await self._broker.publish(self.topic_key, msg)


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
        try:
            await session.start()
        except Exception:
            # Roll back the dict entry so a failed start doesn't poison the
            # capacity counter or leave a half-constructed session around.
            async with self._lock:
                self._sessions.pop(topic_key, None)
            raise
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
