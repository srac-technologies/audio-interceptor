#!/usr/bin/env python3
"""
Meeting Assistant - Backend Server (FastAPI)
音声インターセプト + Whisper文字起こし統合版
"""

import asyncio
import sys
import os
import json
import logging
import logging.handlers
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from logger import get_logger

logger = get_logger("server")

# ルートロガーを最初に設定（全モジュールのログが出力されるようにする）
_log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_formatter = logging.Formatter(_log_format)

# コンソール出力（stdout に出力。stderr だと Electron が全て [Python Error] と表示する）
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_formatter)

# ファイル出力（ランタイム問題の事後調査用）
_log_dir = Path(os.getenv('MEETING_ASSISTANT_LOG_DIR', os.path.join(os.path.dirname(__file__), 'logs')))
_log_dir.mkdir(parents=True, exist_ok=True)
_file_handler = logging.handlers.RotatingFileHandler(
    _log_dir / "meeting_assistant.log",
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console_handler, _file_handler],
)
logger = logging.getLogger(__name__)

# .envファイルを読み込む
try:
    from dotenv import load_dotenv
    config_dir = os.getenv('MEETING_ASSISTANT_CONFIG_DIR', os.path.dirname(__file__))
    env_path = os.path.join(config_dir, '.env')
    load_dotenv(env_path)
    logger.info("Config directory: %s", config_dir)
except ImportError:
    pass

try:
    from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    logger.critical("FastAPI not installed. Install with: pip install fastapi uvicorn websockets python-dotenv")
    sys.exit(1)

# 自作モジュール
from audio_interceptor import AudioInterceptor
import database
from llm_pipeline import LLMPipeline
from calendar_service import calendar_service
import file_manager
from slack_service import SlackService
from transcription import reset_transcription_service
from transcription_engines import get_available_engines
from refinement_providers import get_available_providers
from plugin_manager import PluginManager

# グローバル状態
class AppState:
    def __init__(self):
        self.recording = False
        self.websocket_clients = set()
        self.interceptor: Optional[AudioInterceptor] = None
        self.llm_pipeline: Optional[LLMPipeline] = None
        self.slack_service: Optional[SlackService] = None
        self.plugin_manager: Optional[PluginManager] = None
        self.loop = None
        self.active_meeting_type_id: Optional[int] = None
        self.current_session_id: Optional[int] = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時
    logger.info("Initializing database...")
    database.init_db()

    state.loop = asyncio.get_running_loop()
    logger.info("Event loop captured")

    # プラグインマネージャー初期化
    state.plugin_manager = PluginManager()
    logger.info("Plugin Manager initialized (%d plugins)", len(state.plugin_manager.plugins))

    yield
    # 終了時
    if state.interceptor:
        state.interceptor.cleanup()
    if state.plugin_manager:
        await state.plugin_manager.cleanup()

app = FastAPI(title="Meeting Assistant API", lifespan=lifespan)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# モデル定義
class RecordingStartRequest(BaseModel):
    target_sink: Optional[str] = None
    transcribe_enabled: bool = False
    tmp_dir: str = "./tmp"
    meeting_type_id: Optional[int] = None
    title: Optional[str] = None

class MeetingTypeCreate(BaseModel):
    name: str
    description: str = ""

class PromptCreate(BaseModel):
    meeting_type_id: int
    trigger_condition: str
    action_prompt: str

class RecordingUpdateRequest(BaseModel):
    title: Optional[str] = None
    meeting_type_id: Optional[int] = None

class SettingsUpdate(BaseModel):
    settings: Dict[str, str]

class ResearchSourceCreate(BaseModel):
    name: str
    source_type: str  # "custom_api" | "shell_command"
    priority: int = 5
    timeout: float = 5.0
    config: str = '{}'

class ResearchSourceUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[int] = None
    priority: Optional[int] = None
    timeout: Optional[float] = None
    config: Optional[str] = None

# バックグラウンド処理: セッション終了時の処理
async def process_session_end(session_id: int):
    logger.info("Processing session end for ID: %d", session_id)
    
    # 1. データの取得
    details = database.get_session_details(session_id)
    if not details:
        logger.error("Session details not found for ID: %d", session_id)
        return
        
    session = details['session']
    transcripts = details['transcripts']
    advices = details['advices']
    
    # 2. 設定の読み込み
    settings = database.get_settings()
    auto_summary = settings.get('auto_summary_enabled', 'false') == 'true'
    summary_prompt = settings.get('summary_prompt')
    save_dir = settings.get('save_dir', str(Path.home() / "Documents" / "MeetingLogs"))
    
    summary_text = None
    
    # 3. サマリー生成 (設定でONの場合)
    if auto_summary:
        logger.info("Generating summary...")
        # LLMPipelineの一時的なインスタンスを作成してサマリー生成
        # (現在のアクティブなパイプラインはクリーンアップされている可能性があるため)
        temp_pipeline = LLMPipeline()
        summary_text = await temp_pipeline.generate_summary(
            transcripts=transcripts,
            start_time=session.get('start_time'),
            prompt_text=summary_prompt
        )
        
        # DBに保存
        if summary_text:
            database.save_summary(session_id, summary_text)
            logger.info("Summary saved to DB for session %d", session_id)

            # プラグインにsummary_generatedイベントを配信
            if state.plugin_manager:
                await state.plugin_manager.emit("summary_generated", {
                    "session_id": session_id,
                    "summary": summary_text,
                    "title": session.get('title', ''),
                })
    
    # 4. ファイル保存 (Markdown)
    file_path = file_manager.save_meeting_log(
        save_dir=save_dir,
        session_title=session['title'] or f"Meeting_{session_id}",
        transcripts=transcripts,
        start_time=session.get('start_time'),
        summary=summary_text,
        advices=advices
    )
    
    if file_path:
        logger.info("Log saved to: %s", file_path)

# --- Endpoints ---

@app.get("/")
async def root():
    return {
        "service": "Meeting Assistant Backend",
        "version": "0.3.0",
        "status": "running"
    }

@app.get("/status")
async def get_status():
    return {
        "recording": state.recording,
        "connected_clients": len(state.websocket_clients),
        "transcribe_enabled": state.interceptor.transcribe_enabled if state.interceptor else False
    }

@app.get("/sinks")
async def get_available_sinks_endpoint():
    from audio_interceptor import create_audio_backend
    try:
        backend = create_audio_backend()
        sinks = backend.get_available_sinks()
        return {"sinks": sinks}
    except Exception:
        return {"sinks": []}

def on_transcript_callback(source, text):
    if state.loop and state.loop.is_running():
        if state.current_session_id:
            try:
                database.add_transcript(state.current_session_id, source, text)
            except Exception as e:
                logger.error("Failed to save transcript: %s", e)

        asyncio.run_coroutine_threadsafe(broadcast_transcript(source, text), state.loop)

        # プラグインにtranscriptionイベントを配信
        if state.plugin_manager:
            asyncio.run_coroutine_threadsafe(
                state.plugin_manager.emit("transcription", {
                    "source": source,
                    "text": text,
                    "session_id": state.current_session_id,
                }),
                state.loop
            )

        if state.llm_pipeline:
            # スピーカーのみリサーチ対象
            if source.lower() == "speaker":
                logger.debug("[SPEAKER] Sending to LLM pipeline: %s...", text[:50])
            else:
                logger.debug("[MIC] Skipping: %s...", text[:30])
            asyncio.run_coroutine_threadsafe(state.llm_pipeline.process_transcript(source, text), state.loop)

async def on_research_callback(research_data):
    """リサーチ結果のコールバック（UI配信 + Slack投稿 + DB保存）"""
    entity = research_data.get("entity", "")
    text = research_data.get("text", "")
    
    # 1. DBに保存（advicesテーブルを再利用）
    if state.current_session_id:
        try:
            database.add_advice(
                state.current_session_id, 
                entity,  # trigger_condition → entity
                text     # advice_text → research result
            )
        except Exception as e:
            logger.error("Failed to save research: %s", e)
    
    # 2. WebSocketでUI配信
    await broadcast_research(research_data)

    # 2.5. プラグインにresearch_resultイベントを配信
    if state.plugin_manager:
        await state.plugin_manager.emit("research_result", {
            "entity": entity,
            "text": text,
            "session_id": state.current_session_id,
            "source": research_data.get("source", ""),
            "metadata": research_data.get("metadata", {}),
        })

    # 3. Slackに投稿（同期関数をスレッドで実行）
    if state.slack_service:
        asyncio.create_task(
            asyncio.to_thread(state.slack_service.post_research_result, entity, text)
        )

@app.post("/recording/start")
async def start_recording(request: RecordingStartRequest):
    if state.recording:
        return {"success": False, "message": "Already recording"}
    
    logger.info("Start Request: transcribe=%s, type=%s", request.transcribe_enabled, request.meeting_type_id)
    
    try:
        state.active_meeting_type_id = request.meeting_type_id
        
        # タイトルが指定されていない場合、カレンダーから取得を試みる
        session_title = request.title
        if not session_title:
            settings = database.get_settings()
            calendar_id = settings.get('calendar_id', 'primary')
            event = calendar_service.get_current_event(calendar_id=calendar_id, time_window_minutes=30)
            if event:
                session_title = event['summary']
                logger.info("Calendar event found: %s", session_title)
            else:
                session_title = f"Meeting {state.active_meeting_type_id or 'Untitled'}"
        
        state.current_session_id = database.create_session(
            state.active_meeting_type_id, 
            title=session_title
        )
        logger.info("Session ID: %d", state.current_session_id)

        # リサーチ機能の初期化
        logger.info("Transcribe enabled: %s", request.transcribe_enabled)
        
        if request.transcribe_enabled:
            settings = database.get_settings()
            research_enabled = settings.get('research_enabled', 'false') == 'true'
            logger.info("Research enabled (from DB): %s", research_enabled)
            
            if research_enabled:
                # LLMパイプライン（リサーチ用）
                state.llm_pipeline = LLMPipeline(on_research=on_research_callback)
                logger.info("LLM Pipeline initialized")
                
                # Slackサービスの初期化
                slack_bot_token = settings.get('slack_bot_token', '')
                slack_channel = settings.get('slack_channel', '')
                
                if slack_bot_token and slack_channel:
                    state.slack_service = SlackService(
                        bot_token=slack_bot_token,
                        channel=slack_channel
                    )
                    # スレッド作成（同期関数をスレッドで実行）
                    success = await asyncio.to_thread(
                        state.slack_service.create_thread, 
                        session_title
                    )
                    if success:
                        logger.info("Slack thread created for: %s", session_title)
                    else:
                        logger.warning("Failed to create Slack thread")
                        state.slack_service = None
                else:
                    state.slack_service = None
                    logger.info("Slack bot token or channel not configured")
            else:
                state.llm_pipeline = None
                state.slack_service = None
                logger.info("Research feature disabled")
        else:
            state.llm_pipeline = None
            state.slack_service = None
            logger.info("Transcribe disabled, no LLM pipeline")
            
        state.interceptor = AudioInterceptor(
            tmp_dir=request.tmp_dir,
            target_sink=request.target_sink,
            transcribe_enabled=request.transcribe_enabled,
            on_transcript=on_transcript_callback
        )
        state.interceptor.setup()
        state.interceptor.start_intercepting()
        
        state.recording = True
        await broadcast_status("recording_started")

        # プラグインにsession_startイベントを配信
        if state.plugin_manager:
            await state.plugin_manager.emit("session_start", {
                "session_id": state.current_session_id,
                "title": session_title,
                "meeting_type_id": state.active_meeting_type_id,
            })

        return {"success": True, "message": "Started", "session_id": state.current_session_id}
        
    except Exception as e:
        state.recording = False
        state.interceptor = None
        state.current_session_id = None
        logger.error("Recording start failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/recording/stop")
async def stop_recording(background_tasks: BackgroundTasks):
    if not state.recording:
        return {"success": False, "message": "Not recording"}
    
    try:
        if state.interceptor:
            state.interceptor.cleanup()
            state.interceptor = None
        
        # LLMパイプラインとSlackサービスのクリーンアップ
        if state.llm_pipeline:
            cache_size = len(state.llm_pipeline.researched_entities)
            logger.info("リサーチキャッシュをクリア（%d件）", cache_size)
            state.llm_pipeline = None
        
        if state.slack_service:
            state.slack_service = None
        
        session_id = state.current_session_id
        if session_id:
            database.end_session(session_id)
            logger.info("Session ended: ID %d", session_id)
            # バックグラウンドでサマリー生成・ファイル保存を実行
            background_tasks.add_task(process_session_end, session_id)
            state.current_session_id = None
        
        state.recording = False
        await broadcast_status("recording_stopped")

        # プラグインにsession_endイベントを配信
        if state.plugin_manager and session_id:
            await state.plugin_manager.emit("session_end", {
                "session_id": session_id,
            })

        return {"success": True, "message": "Stopped"}
        
    except Exception as e:
        logger.error("Recording stop failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/recording/mute-mic")
async def mute_microphone(mute_request: dict):
    """マイクのミュート/ミュート解除"""
    if not state.recording or not state.interceptor:
        return {"success": False, "message": "Not recording"}
    
    try:
        muted = mute_request.get("muted", False)
        state.interceptor.set_mic_mute(muted)
        
        # WebSocketで状態をブロードキャスト
        await broadcast(json.dumps({
            "type": "mic_mute_status",
            "muted": muted
        }))
        
        return {"success": True, "muted": muted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/recording")
async def update_recording(request: RecordingUpdateRequest):
    if not state.recording or not state.current_session_id:
        return {"success": False, "message": "Not recording"}
    
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        if request.title is not None:
            cursor.execute('UPDATE sessions SET title = ? WHERE id = ?', (request.title, state.current_session_id))
        if request.meeting_type_id is not None:
            cursor.execute('UPDATE sessions SET meeting_type_id = ? WHERE id = ?', (request.meeting_type_id, state.current_session_id))
            state.active_meeting_type_id = request.meeting_type_id
            # Note: リサーチ機能はmeeting_type_idに依存しないため、再初期化不要
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket接続（リアルタイム文字起こし配信用）"""
    await websocket.accept()
    state.websocket_clients.add(websocket)
    logger.info("WebSocket client connected. Total: %d", len(state.websocket_clients))
    
    # 現在のステータスを送信
    await websocket.send_text(json.dumps({
        "type": "status",
        "recording": state.recording
    }))
    
    try:
        while True:
            # クライアントからのメッセージを受信（keep-alive）
            data = await websocket.receive_text()
            # ping/pongハンドリング
            if data == "ping":
                await websocket.send_text("pong")
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        state.websocket_clients.discard(websocket)
        logger.info("WebSocket client disconnected. Total: %d", len(state.websocket_clients))

# --- Plugin WebSocket & API ---

@app.websocket("/ws/plugins")
async def plugin_websocket_endpoint(websocket: WebSocket):
    """プラグイン用WebSocketエンドポイント（外部プロセスから購読）"""
    await websocket.accept()

    # 初回メッセージで購読イベントを指定可能
    # {"subscribe": ["transcription", "research_result"]} or {} for all
    subscribed_events = []
    try:
        # 最初のメッセージを短時間待機（購読設定）
        init_data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
        init_msg = json.loads(init_data)
        subscribed_events = init_msg.get("subscribe", [])
    except (asyncio.TimeoutError, json.JSONDecodeError):
        pass  # タイムアウトまたは不正なJSON → 全イベント購読

    state.plugin_manager.register_ws_client(websocket, subscribed_events)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except Exception:
        pass
    finally:
        state.plugin_manager.unregister_ws_client(websocket)

class PluginCreateRequest(BaseModel):
    name: str
    protocol: str  # websocket | pipe | webhook | exec
    endpoint: str = ""
    events: List[str] = []
    enabled: bool = True

class PluginUpdateRequest(BaseModel):
    protocol: Optional[str] = None
    endpoint: Optional[str] = None
    events: Optional[List[str]] = None
    enabled: Optional[bool] = None

@app.get("/plugins")
async def list_plugins():
    """プラグイン一覧"""
    return {"plugins": state.plugin_manager.list_plugins()}

@app.post("/plugins")
async def create_plugin(request: PluginCreateRequest):
    """プラグイン登録"""
    plugin = state.plugin_manager.add_plugin(request.model_dump())
    return {"success": True, "plugin": plugin.to_dict()}

@app.get("/plugins/{name}")
async def get_plugin(name: str):
    """プラグイン取得"""
    plugin = state.plugin_manager.get_plugin(name)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"plugin": plugin.to_dict()}

@app.put("/plugins/{name}")
async def update_plugin(name: str, request: PluginUpdateRequest):
    """プラグイン更新"""
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    plugin = state.plugin_manager.update_plugin(name, updates)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"success": True, "plugin": plugin.to_dict()}

@app.delete("/plugins/{name}")
async def delete_plugin(name: str):
    """プラグイン削除"""
    if state.plugin_manager.remove_plugin(name):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Plugin not found")

@app.get("/plugins/events/types")
async def list_event_types():
    """利用可能なイベント種別一覧"""
    from plugin_manager import PLUGIN_EVENTS
    return {"events": PLUGIN_EVENTS}

# --- Settings API ---

@app.get("/settings")
async def get_settings():
    """設定一覧を取得"""
    return {"settings": database.get_settings()}

@app.post("/settings")
async def update_settings(update: SettingsUpdate):
    """設定を更新"""
    try:
        for key, value in update.settings.items():
            database.update_setting(key, value)
        # エンジン関連の設定が変更されたらシングルトンをリセット
        engine_keys = {"transcription_engine", "transcription_model", "transcription_language"}
        if engine_keys & set(update.settings.keys()):
            reset_transcription_service()
            logger.info("Transcription service reset due to engine settings change")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Transcription Engine & Refinement Provider APIs ---

@app.get("/transcription/engines")
async def list_transcription_engines():
    """利用可能な文字起こしエンジン一覧"""
    return {"engines": get_available_engines()}

@app.get("/transcription/refinement-providers")
async def list_refinement_providers():
    """利用可能な精度向上LLMプロバイダ一覧"""
    return {"providers": get_available_providers()}

# --- History & Download APIs ---

@app.get("/history")
async def list_history():
    return {"sessions": database.get_sessions()}

@app.get("/history/{session_id}")
async def get_history_details(session_id: int):
    return database.get_session_details(session_id)

@app.patch("/history/{session_id}")
async def update_history(session_id: int, update_data: dict):
    """履歴のタイトルなどを更新"""
    try:
        if 'title' in update_data:
            database.update_session_title(session_id, update_data['title'])
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history/{session_id}/download/docx")
async def download_docx(session_id: int):
    """履歴のDocxダウンロード"""
    details = database.get_session_details(session_id)
    if not details:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session = details['session']
    transcripts = details['transcripts']
    advices = details['advices']
    
    # Docx生成
    doc = file_manager.generate_docx(
        session_title=session['title'] or f"Meeting_{session_id}",
        transcripts=transcripts,
        start_time=session.get('start_time'),
        summary=session.get('summary'), # DBにあれば
        advices=advices
    )
    
    # 一時ファイルとして保存（パッケージ版ではconfig_dir配下を使用）
    filename = f"meeting_{session_id}.docx"
    tmp_base = Path(config_dir) / "tmp"
    tmp_path = tmp_base / filename
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(tmp_path)
    
    return FileResponse(
        path=tmp_path, 
        filename=filename,
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )

# --- WebSocket Helpers ---

async def broadcast_status(status: str):
    message = json.dumps({"type": "status", "status": status, "recording": state.recording})
    await broadcast(message)

async def broadcast_transcript(source: str, text: str):
    message = json.dumps({"type": "transcript", "source": source, "text": text})
    await broadcast(message)

async def broadcast_research(research_data: dict):
    """リサーチ結果をWebSocketで配信（UI表示用）"""
    # UIのadviceパネルを再利用するため、フォーマットを合わせる
    ui_message = {
        "type": "advice",  # UIは"advice"イベントを期待
        "trigger": research_data.get("entity", ""),  # entity → trigger
        "text": research_data.get("text", ""),
        "timestamp": research_data.get("timestamp", "")
    }
    await broadcast(json.dumps(ui_message))

async def broadcast(message: str):
    disconnected = set()
    for client in state.websocket_clients:
        try:
            await client.send_text(message)
        except:
            disconnected.add(client)
    state.websocket_clients -= disconnected

# --- Master Data (Simplified for brevity) ---
@app.get("/meeting-types")
async def list_types(): return {"meeting_types": database.get_meeting_types()}
@app.get("/meeting-types/{tid}/prompts")
async def list_prompts_api(tid: int): return {"prompts": database.get_prompts_for_type(tid)}
@app.post("/meeting-types")
async def create_type_api(item: MeetingTypeCreate): 
    return {"id": database.create_meeting_type(item.name, item.description)}
@app.delete("/meeting-types/{tid}")
async def delete_type_api(tid: int): 
    database.delete_meeting_type(tid); return {"success": True}
@app.post("/prompts")
async def create_prompt_api(item: PromptCreate):
    return {"id": database.create_prompt(item.meeting_type_id, item.trigger_condition, item.action_prompt)}
@app.delete("/prompts/{pid}")
async def delete_prompt_api(pid: int):
    database.delete_prompt(pid); return {"success": True}
# --- Research Sources API ---

@app.get("/research-sources")
async def list_research_sources():
    """リサーチソース一覧を取得"""
    return {"sources": database.get_research_sources()}

@app.post("/research-sources")
async def create_research_source_api(item: ResearchSourceCreate):
    """リサーチソースを追加"""
    new_id = database.create_research_source(
        name=item.name,
        source_type=item.source_type,
        priority=item.priority,
        timeout=item.timeout,
        config=item.config
    )
    return {"id": new_id}

@app.put("/research-sources/{source_id}")
async def update_research_source_api(source_id: int, item: ResearchSourceUpdate):
    """リサーチソースを更新"""
    updates = {k: v for k, v in item.model_dump().items() if v is not None}
    if updates:
        database.update_research_source(source_id, **updates)
    return {"success": True}

@app.delete("/research-sources/{source_id}")
async def delete_research_source_api(source_id: int):
    """リサーチソースを削除（組み込みソースは削除不可）"""
    source = database.get_research_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source['source_type'] == 'builtin':
        raise HTTPException(status_code=400, detail="Cannot delete builtin source")
    database.delete_research_source(source_id)
    return {"success": True}

# --- Calendar APIs ---

@app.get("/calendar/current")
async def get_current_calendar_event():
    """現在時刻付近のカレンダーイベントを取得"""
    settings = database.get_settings()
    calendar_id = settings.get('calendar_id', 'primary')
    
    event = calendar_service.get_current_event(calendar_id=calendar_id)
    if event:
        return {"success": True, "event": event}
    else:
        return {"success": False, "message": "No event found"}

@app.get("/calendar/events")
async def get_concurrent_calendar_events():
    """現在時刻付近の全カレンダーイベントを取得（同一時間帯の複数候補対応）"""
    settings = database.get_settings()
    calendar_id = settings.get('calendar_id', 'primary')

    events = calendar_service.get_concurrent_events(calendar_id=calendar_id)
    return {"success": True, "events": events}

@app.get("/calendar/today")
async def get_today_events():
    """今日のカレンダーイベント一覧を取得"""
    settings = database.get_settings()
    calendar_id = settings.get('calendar_id', 'primary')
    
    events = calendar_service.get_events_today(calendar_id=calendar_id)
    return {"events": events}

if __name__ == "__main__":
    logger.info("Meeting Assistant Backend v0.3.0")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
