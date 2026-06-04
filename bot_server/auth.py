"""Single-token bearer auth for the bot server (Phase 1 MVP).

Phase 1 ships one shared `BOT_TOKEN` env var that gates every HTTP and
WebSocket entry point. Per-room ACL is intentionally out of scope — we'll
revisit if/when multi-tenant requirements appear.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, status

from .settings import Settings


def _constant_time_eq(a: str, b: str) -> bool:
    # Avoid leaking the valid length via early-return comparisons.
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def check_http_token(authorization: str | None, settings: Settings) -> None:
    """Validate an HTTP `Authorization: Bearer <token>` header.

    Raises 401 if missing / malformed, 403 if the token doesn't match.
    Returning None means OK.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not _constant_time_eq(token, settings.bot_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="invalid token"
        )


def check_ws_token(token: str | None, settings: Settings) -> bool:
    """Validate a WebSocket token (passed via ?token= query)."""
    if not token:
        return False
    return _constant_time_eq(token, settings.bot_token)
