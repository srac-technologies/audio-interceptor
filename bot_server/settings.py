"""Runtime configuration loaded from environment.

We keep this dependency-free (no pydantic-settings) so the bot_server can be
trimmed for a small container image. Validation lives in :func:`load_settings`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    host: str
    port: int
    public_ws_base: str
    max_concurrent_meetings: int
    idle_eviction_seconds: float
    log_level: str

    # Phase 1 fallback: dummy publisher (no real Meet bot).
    dummy_publisher_enabled: bool
    dummy_publisher_interval_seconds: float

    # Phase 2: real worker subprocess settings.
    worker_python: str
    worker_module: str
    worker_profile_dir_template: str | None
    worker_headless: bool
    worker_shutdown_timeout_seconds: float
    chrome_channel: str
    admission_timeout_seconds: float
    whisper_model: str
    whisper_language: str
    chunk_seconds: float

    # Phase 2.5: viewer (graphic-recording web view) — optional.
    viewer_enabled: bool
    viewer_token: str
    viewer_idle_evict_seconds: float


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN env var is required. Set it to a long random string "
            "(e.g. `openssl rand -hex 32`)."
        )
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    public_ws_base = os.environ.get("PUBLIC_WS_BASE", f"ws://{host}:{port}")
    return Settings(
        bot_token=bot_token,
        host=host,
        port=port,
        public_ws_base=public_ws_base.rstrip("/"),
        max_concurrent_meetings=int(os.environ.get("MAX_CONCURRENT_MEETINGS", "3")),
        idle_eviction_seconds=float(os.environ.get("IDLE_EVICTION_SECONDS", "300")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        # DUMMY_PUBLISHER defaults OFF in Phase 2 — the real worker is the
        # primary path. Set DUMMY_PUBLISHER=1 to keep the broker smoke-test
        # path working without launching Playwright + Whisper.
        dummy_publisher_enabled=_env_bool("DUMMY_PUBLISHER", False),
        dummy_publisher_interval_seconds=float(os.environ.get("DUMMY_INTERVAL", "5")),
        worker_python=os.environ.get("WORKER_PYTHON", sys.executable),
        # Override for tests: WORKER_MODULE=bot_server._fake_worker swaps
        # in the no-Playwright fake worker.
        worker_module=os.environ.get("WORKER_MODULE", "bot_server.worker"),
        # Optional template like '/var/lib/bot_server/profiles/{topic_key}'.
        # When None, the worker creates an ephemeral tmpdir per session — fine
        # for one-off testing but a fresh Chrome profile every time means the
        # bot is logged out (and Meet may treat it as a guest, which often
        # fails admission). Set this for production.
        worker_profile_dir_template=os.environ.get("WORKER_PROFILE_DIR_TEMPLATE") or None,
        worker_headless=_env_bool("WORKER_HEADLESS", False),
        worker_shutdown_timeout_seconds=float(
            os.environ.get("WORKER_SHUTDOWN_TIMEOUT", "30")
        ),
        chrome_channel=os.environ.get("CHROME_CHANNEL", "chrome"),
        admission_timeout_seconds=float(
            os.environ.get("ADMISSION_TIMEOUT", "180")
        ),
        whisper_model=os.environ.get("WHISPER_MODEL", "small"),
        whisper_language=os.environ.get("WHISPER_LANGUAGE", "ja"),
        chunk_seconds=float(os.environ.get("CHUNK_SECONDS", "10")),
        viewer_enabled=_env_bool("VIEWER_ENABLED", False),
        viewer_token=os.environ.get("VIEWER_TOKEN", "").strip(),
        viewer_idle_evict_seconds=float(
            os.environ.get("VIEWER_IDLE_EVICT_SECONDS", "120")
        ),
    )
