#!/usr/bin/env python3
"""
Meeting Assistant - Backend Server (FastAPI)
音声インターセプト + Whisper文字起こし統合版
"""

import asyncio
import sys
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

# .envファイルを読み込む
try:
    from dotenv import load_dotenv
    config_dir = os.getenv('MEETING_ASSISTANT_CONFIG_DIR', os.path.dirname(__file__))
    env_path = os.path.join(config_dir, '.env')
    load_dotenv(env_path)
    print(f"📁 Config directory: {config_dir}")
except ImportError:
    pass

try:
    from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("⚠️  FastAPI not installed. Install with: pip install fastapi uvicorn websockets python-dotenv")
    sys.exit(1)

# 自作モジュール
from audio_interceptor import AudioInterceptor
import database
from llm_pipeline import LLMPipeline
from calendar_service import calendar_service
import file_manager

# グローバル状態
class AppState:
    def __init__(self):
        self.recording = False
        self.websocket_clients = set()
        self.interceptor: Optional[AudioInterceptor] = None
        self.llm_pipeline: Optional[LLMPipeline] = None
        self.loop = None
        self.active_meeting_type_id: Optional[int] = None
        self.current_session_id: Optional[int] = None

state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時
    print("🚀 Initializing database...")
    database.init_db()
    
    state.loop = asyncio.get_running_loop()
    print("✅ Event loop captured")
    yield
    # 終了時
    if state.interceptor:
        state.interceptor.cleanup()

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

# バックグラウンド処理: セッション終了時の処理
async def process_session_end(session_id: int):
    print(f"🔄 Processing session end for ID: {session_id}")
    
    # 1. データの取得
    details = database.get_session_details(session_id)
    if not details:
        print(f"❌ Session details not found for ID: {session_id}")
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
        print("🤖 Generating summary...")
        # LLMPipelineの一時的なインスタンスを作成してサマリー生成
        # (現在のアクティブなパイプラインはクリーンアップされている可能性があるため)
        temp_pipeline = LLMPipeline()
        summary_text = await temp_pipeline.generate_summary(transcripts, summary_prompt)
        
        # DBに保存
        if summary_text:
            database.save_summary(session_id, summary_text)
            print("✅ Summary saved to DB")
    
    # 4. ファイル保存 (Markdown)
    file_path = file_manager.save_meeting_log(
        save_dir=save_dir,
        session_title=session['title'] or f"Meeting_{session_id}",
        transcripts=transcripts,
        summary=summary_text,
        advices=advices
    )
    
    if file_path:
        print(f"💾 Log saved to: {file_path}")

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
async def get_available_sinks():
    import subprocess
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True
        )
        if result.returncode != 0: return {"sinks": []}
        sinks = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                sinks.append({"id": parts[0], "name": parts[1]})
        return {"sinks": sinks}
    except Exception:
        return {"sinks": []}

def on_transcript_callback(source, text):
    if state.loop and state.loop.is_running():
        if state.current_session_id:
            try:
                database.add_transcript(state.current_session_id, source, text)
            except Exception as e:
                print(f"Failed to save transcript: {e}")

        asyncio.run_coroutine_threadsafe(broadcast_transcript(source, text), state.loop)
        
        if state.llm_pipeline:
            asyncio.run_coroutine_threadsafe(state.llm_pipeline.process_transcript(source, text), state.loop)

async def on_advice_callback(advice_data):
    if state.current_session_id:
        try:
            database.add_advice(
                state.current_session_id, 
                advice_data.get("trigger", ""), 
                advice_data.get("text", "")
            )
        except Exception as e:
            print(f"Failed to save advice: {e}")
    await broadcast_advice(advice_data)

@app.post("/recording/start")
async def start_recording(request: RecordingStartRequest):
    if state.recording:
        return {"success": False, "message": "Already recording"}
    
    print(f"🔍 Start Request: transcribe={request.transcribe_enabled}, type={request.meeting_type_id}")
    
    try:
        state.active_meeting_type_id = request.meeting_type_id
        session_title = request.title or f"Meeting {state.active_meeting_type_id or 'Untitled'}"
        
        state.current_session_id = database.create_session(
            state.active_meeting_type_id, 
            title=session_title
        )
        print(f"🆕 Session ID: {state.current_session_id}")
            
        if request.transcribe_enabled and state.active_meeting_type_id:
            state.llm_pipeline = LLMPipeline(
                meeting_type_id=state.active_meeting_type_id,
                on_advice=on_advice_callback
            )
        else:
            state.llm_pipeline = None
            
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
        
        return {"success": True, "message": "Started", "session_id": state.current_session_id}
        
    except Exception as e:
        state.recording = False
        state.interceptor = None
        state.current_session_id = None
        print(f"❌ Start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/recording/stop")
async def stop_recording(background_tasks: BackgroundTasks):
    if not state.recording:
        return {"success": False, "message": "Not recording"}
    
    try:
        if state.interceptor:
            state.interceptor.cleanup()
            state.interceptor = None
        
        session_id = state.current_session_id
        if session_id:
            database.end_session(session_id)
            print(f"🏁 Session ended: ID {session_id}")
            # バックグラウンドでサマリー生成・ファイル保存を実行
            background_tasks.add_task(process_session_end, session_id)
            state.current_session_id = None
        
        state.recording = False
        await broadcast_status("recording_stopped")
        
        return {"success": True, "message": "Stopped"}
        
    except Exception as e:
        print(f"❌ Stop failed: {e}")
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
            if state.llm_pipeline and request.meeting_type_id:
                state.llm_pipeline = LLMPipeline(
                    meeting_type_id=request.meeting_type_id,
                    on_advice=on_advice_callback
                )
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
    print(f"✅ WebSocket client connected. Total: {len(state.websocket_clients)}")
    
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
        print(f"WebSocket error: {e}")
    finally:
        state.websocket_clients.discard(websocket)
        print(f"❌ WebSocket client disconnected. Total: {len(state.websocket_clients)}")

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
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- History & Download APIs ---

@app.get("/history")
async def list_history():
    return {"sessions": database.get_sessions()}

@app.get("/history/{session_id}")
async def get_history_details(session_id: int):
    return database.get_session_details(session_id)

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
        summary=session.get('summary'), # DBにあれば
        advices=advices
    )
    
    # 一時ファイルとして保存
    filename = f"meeting_{session_id}.docx"
    tmp_path = Path("./tmp") / filename
    tmp_path.parent.mkdir(exist_ok=True)
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

async def broadcast_advice(advice_data: dict):
    if "type" not in advice_data: advice_data["type"] = "advice"
    await broadcast(json.dumps(advice_data))

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

@app.get("/calendar/today")
async def get_today_events():
    """今日のカレンダーイベント一覧を取得"""
    settings = database.get_settings()
    calendar_id = settings.get('calendar_id', 'primary')
    
    events = calendar_service.get_events_today(calendar_id=calendar_id)
    return {"events": events}

if __name__ == "__main__":
    print("🚀 Meeting Assistant Backend v0.3.0")
    uvicorn.run(app, host="0.0.0.0", port=8000)
