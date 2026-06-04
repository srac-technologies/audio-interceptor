"""HTTP + WebSocket routes for the graphic-recording viewer.

Mounted under ``/v`` when ``settings.viewer_enabled`` is True. The browser
gets:

  - ``GET  /v/{slug}``        — static HTML shell (the JS connects below)
  - ``GET  /v/{slug}/static/<path>``  — viewer.js etc.
  - ``WSS  /v/{slug}/ws``     — receive transcripts + snapshots, send controls
  - ``GET  /v/sessions``      — debug: list active viewer pipelines

The WS doesn't expose BOT_TOKEN — the viewer holds the broker subscription
on the browser's behalf. ``VIEWER_TOKEN`` (optional, separate from
``BOT_TOKEN``) can be required if set in env.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse

from ..broker import Broker
from .canvas.views import VIEW_MODES
from .manager import ViewerManager

logger = logging.getLogger("bot_server.viewer.router")

# Same shape rule as bot_manager — alphanumerics + - / _, 3-64 chars.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")

_STATIC_DIR = Path(__file__).resolve().parent / "static"


router = APIRouter(prefix="/v", tags=["viewer"])


def _check_token(request_token: str | None, viewer_token: str) -> bool:
    """Viewer auth — separate from BOT_TOKEN.

    Empty ``viewer_token`` means no-auth (capability-as-URL: knowing the slug
    is enough). When set, request must match it exactly.
    """
    if not viewer_token:
        return True
    return bool(request_token) and request_token == viewer_token


@router.get("/sessions")
async def sessions(request: Request) -> dict:
    mgr: ViewerManager = request.app.state.viewer_manager
    return {"sessions": mgr.list_slugs()}


@router.get("/{slug}/static/{filename:path}")
async def viewer_static(slug: str, filename: str):
    # No slug validation needed for static assets — these are constant files.
    target = (_STATIC_DIR / filename).resolve()
    try:
        target.relative_to(_STATIC_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(target)


@router.get("/{slug}", response_class=HTMLResponse)
async def viewer_page(slug: str) -> HTMLResponse:
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid slug",
        )
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # Inject the slug as a data attribute so viewer.js doesn't have to parse
    # the URL itself (which trips on iframe / SPA wrappers).
    html = html.replace("__SLUG__", slug)
    return HTMLResponse(content=html)


@router.websocket("/{slug}/ws")
async def viewer_ws(
    websocket: WebSocket,
    slug: str,
    token: str | None = Query(default=None),
) -> None:
    settings = websocket.app.state.settings
    if not _SLUG_RE.match(slug):
        await websocket.close(code=4400, reason="invalid slug")
        return
    if not _check_token(token, settings.viewer_token):
        await websocket.close(code=4401, reason="invalid viewer token")
        return

    await websocket.accept()
    broker: Broker = websocket.app.state.broker
    mgr: ViewerManager = websocket.app.state.viewer_manager

    pipeline = await mgr.acquire(slug)
    await broker.subscribe(slug, websocket)
    # Send the current snapshot immediately so a freshly opened browser
    # sees what's already there without waiting for the next transcript.
    await pipeline.publish_current_snapshot()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_control(msg, pipeline)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("viewer ws slug=%s loop raised: %s", slug, exc)
    finally:
        await broker.unsubscribe(slug, websocket)
        await mgr.release(slug)


async def _handle_control(msg: dict, pipeline) -> None:
    """Client → server control messages.

    Supported shapes:
      {"type":"set_view","mode":"mindmap|tree|kanban|mermaid|transcript"}
      {"type":"set_enabled","enabled":true|false}
    """
    if not isinstance(msg, dict):
        return
    mtype = msg.get("type")
    if mtype == "set_view":
        mode = msg.get("mode")
        if isinstance(mode, str) and mode in VIEW_MODES:
            pipeline.set_view_mode(mode)
            await pipeline.publish_current_snapshot()
    elif mtype == "set_enabled":
        enabled = msg.get("enabled")
        if isinstance(enabled, bool):
            pipeline.set_enabled(enabled)
            await pipeline.publish_current_snapshot()
