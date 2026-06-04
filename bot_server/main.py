"""FastAPI app: HTTP control plane + WebSocket fan-out.

Endpoints:
    POST   /bot/join            join a meeting, returns topic_key + ws_url
    POST   /bot/leave/{key}     stop a session
    GET    /bot/sessions        list active sessions
    GET    /healthz             liveness
    WSS    /ws/topics/{key}     subscribe to transcripts for a topic

All routes require `Authorization: Bearer <BOT_TOKEN>`; the WebSocket route
takes the token via `?token=...` query param.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

from .auth import check_http_token, check_ws_token
from .bot_manager import BotManager, CapacityError
from .broker import Broker
from .settings import Settings, load_settings

logger = logging.getLogger("bot_server.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    broker = Broker()
    manager = BotManager(broker, settings)
    app.state.settings = settings
    app.state.broker = broker
    app.state.manager = manager

    viewer_manager = None
    if settings.viewer_enabled:
        # Defer the import so a `viewer_enabled=False` deploy doesn't need
        # httpx or any of the viewer-only dependencies installed.
        from .viewer.llm import load_llm_config
        from .viewer.manager import ViewerManager
        from .viewer.router import router as viewer_router

        try:
            llm_config = load_llm_config()
        except ValueError as exc:
            logger.error("viewer disabled: %s", exc)
        else:
            viewer_manager = ViewerManager(
                broker=broker,
                llm_config=llm_config,
                idle_evict_seconds=settings.viewer_idle_evict_seconds,
            )
            await viewer_manager.start()
            app.state.viewer_manager = viewer_manager
            app.include_router(viewer_router)
            logger.info(
                "viewer enabled at /v/{slug} (llm=%s/%s)",
                llm_config.backend,
                llm_config.model,
            )

    logger.info(
        "bot_server ready host=%s port=%d dummy=%s cap=%d viewer=%s",
        settings.host,
        settings.port,
        settings.dummy_publisher_enabled,
        settings.max_concurrent_meetings,
        bool(viewer_manager),
    )
    try:
        yield
    finally:
        await manager.leave_all()
        if viewer_manager is not None:
            await viewer_manager.stop()
        logger.info("bot_server shutdown")


app = FastAPI(lifespan=lifespan, title="Meet bot server", version="0.2.0")


class JoinRequest(BaseModel):
    meet_url: str = Field(..., description="Full Meet URL or bare meeting code.")
    display_name: str | None = Field(
        default=None, description="Display name the bot will use in the meeting."
    )


class JoinResponse(BaseModel):
    topic_key: str
    ws_url: str


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _manager(request: Request) -> BotManager:
    return request.app.state.manager


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/bot/join", response_model=JoinResponse)
async def bot_join(
    req: JoinRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> JoinResponse:
    settings = _settings(request)
    check_http_token(authorization, settings)
    manager = _manager(request)
    try:
        topic_key, _session = await manager.join(req.meet_url, req.display_name)
    except CapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    ws_url = f"{settings.public_ws_base}/ws/topics/{topic_key}"
    return JoinResponse(topic_key=topic_key, ws_url=ws_url)


@app.post("/bot/leave/{topic_key}", status_code=status.HTTP_204_NO_CONTENT)
async def bot_leave(
    topic_key: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    settings = _settings(request)
    check_http_token(authorization, settings)
    manager = _manager(request)
    if not await manager.leave(topic_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no such session"
        )
    return None


@app.get("/bot/sessions")
async def bot_sessions(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    settings = _settings(request)
    check_http_token(authorization, settings)
    manager = _manager(request)
    return {"sessions": manager.list_sessions()}


@app.websocket("/ws/topics/{topic_key}")
async def ws_topic(
    websocket: WebSocket,
    topic_key: str,
    token: str | None = Query(default=None),
) -> None:
    settings: Settings = websocket.app.state.settings
    if not check_ws_token(token, settings):
        # Code 4401 is a custom close code in the 4000-4999 private range.
        await websocket.close(code=4401, reason="invalid token")
        return
    await websocket.accept()
    broker: Broker = websocket.app.state.broker
    await broker.subscribe(topic_key, websocket)
    try:
        # Phase 1: we don't expect client messages, but receive_text() blocks
        # until disconnect so the loop exits when the client goes away.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("ws topic=%s recv raised: %s", topic_key, exc)
    finally:
        await broker.unsubscribe(topic_key, websocket)
