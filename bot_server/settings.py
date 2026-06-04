"""Runtime configuration loaded from environment.

We keep this dependency-free (no pydantic-settings) so the bot_server can be
trimmed for a small container image. Validation lives in :func:`load_settings`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    host: str
    port: int
    public_ws_base: str
    max_concurrent_meetings: int
    idle_eviction_seconds: float
    dummy_publisher_enabled: bool
    dummy_publisher_interval_seconds: float
    log_level: str


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
    # Publicly advertised WS base — useful when behind a reverse proxy / TLS.
    public_ws_base = os.environ.get("PUBLIC_WS_BASE", f"ws://{host}:{port}")
    return Settings(
        bot_token=bot_token,
        host=host,
        port=port,
        public_ws_base=public_ws_base.rstrip("/"),
        max_concurrent_meetings=int(os.environ.get("MAX_CONCURRENT_MEETINGS", "3")),
        idle_eviction_seconds=float(os.environ.get("IDLE_EVICTION_SECONDS", "300")),
        # Phase 1: dummy publisher is on by default so the smoke test
        # (wscat) works without a real bot. Turn it off when Phase 2's
        # real worker lands.
        dummy_publisher_enabled=_env_bool("DUMMY_PUBLISHER", True),
        dummy_publisher_interval_seconds=float(os.environ.get("DUMMY_INTERVAL", "5")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
