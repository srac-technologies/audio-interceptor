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
from typing import Optional
from contextlib import asynccontextmanager

# .envファイルを読み込む（パッケージモードでは設定ディレクトリから）
try:
    from dotenv import load_dotenv
    config_dir = os.getenv('MEETING_ASSISTANT_CONFIG_DIR', os.path.dirname(__file__))
    env_path = os.path.join(config_dir, '.env')
    load_dotenv(env_path)
    print(f"📁 Config directory: {config_dir}")
except ImportError:
    pass  # python-dotenvがない場合はスキップ

try:
    from fastapi import FastAPI, WebSocket, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("⚠️  FastAPI not installed. Install with: pip install fastapi uvicorn websockets python-dotenv")
    sys.exit(1)

# AudioInterceptorをインポート
from audio_interceptor import AudioInterceptor
# Databaseをインポート
import database
# LLMPipelineをインポート
from llm_pipeline import LLMPipeline
# CalendarServiceをインポート
from calendar_service import calendar_service

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

# CORS設定（Electronからのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# リクエストボディのモデル
class RecordingStartRequest(BaseModel):
    target_sink: Optional[str] = None
    transcribe_mode: bool = False
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

@app.get("/")
async def root():
    return {
        "service": "Meeting Assistant Backend",
        "version": "0.2.0",
        "status": "running",
        "audio_interceptor": "integrated"
    }

@app.get("/status")
async def get_status():
    return {
        "recording": state.recording,
        "connected_clients": len(state.websocket_clients),
        "transcribe_mode": state.interceptor.transcribe_mode if state.interceptor else False
    }

@app.get("/sinks")
async def get_available_sinks():
    """利用可能なオーディオシンク（出力デバイス）を取得"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return {"sinks": []}
        
        sinks = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                sinks.append({
                    "id": parts[0],
                    "name": parts[1],
                    "driver": parts[2] if len(parts) > 2 else "unknown"
                })
        return {"sinks": sinks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def on_transcript_callback(source, text):
    """AudioInterceptorからのコールバック（別スレッドで呼ばれる）"""
    if state.loop and state.loop.is_running():
        # DB保存 (メインスレッドで実行する必要はないが、簡単のため)
        if state.current_session_id:
            try:
                database.add_transcript(state.current_session_id, source, text)
            except Exception as e:
                print(f"Failed to save transcript: {e}")

        # 文字起こし配信
        asyncio.run_coroutine_threadsafe(broadcast_transcript(source, text), state.loop)
        
        # LLMパイプライン処理（文字起こしモードが有効で、パイプラインがある場合）
        if state.llm_pipeline:
            asyncio.run_coroutine_threadsafe(state.llm_pipeline.process_transcript(source, text), state.loop)

async def on_advice_callback(advice_data):
    """LLMパイプラインからのアドバイスコールバック"""
    # DB保存
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
    """録音開始"""
    if state.recording:
        return {"success": False, "message": "Already recording"}
    
    # デバッグ：リクエスト内容をログ出力
    print(f"🔍 Recording start request: transcribe_mode={request.transcribe_mode}, meeting_type_id={request.meeting_type_id}")
    
    try:
        # 会議種別を設定
        state.active_meeting_type_id = request.meeting_type_id
        if state.active_meeting_type_id:
            print(f"📋 Meeting Type ID: {state.active_meeting_type_id}")
            
        # 新しいセッションを作成
        session_title = request.title or f"Meeting {state.active_meeting_type_id or 'Untitled'}"
        state.current_session_id = database.create_session(
            state.active_meeting_type_id, 
            title=session_title
        )
        print(f"🆕 Session started: ID {state.current_session_id}, Title: {session_title}")
            
        # LLMパイプライン初期化
        if request.transcribe_mode and state.active_meeting_type_id:
            state.llm_pipeline = LLMPipeline(
                meeting_type_id=state.active_meeting_type_id,
                on_advice=on_advice_callback
            )
            print("🧠 LLM Pipeline initialized")
        else:
            state.llm_pipeline = None
            
        # AudioInterceptorインスタンスを作成
        state.interceptor = AudioInterceptor(
            tmp_dir=request.tmp_dir,
            target_sink=request.target_sink,
            transcribe_mode=request.transcribe_mode,
            on_transcript=on_transcript_callback
        )
        
        # セットアップ
        state.interceptor.setup()
        
        # 録音開始
        state.interceptor.start_intercepting()
        
        state.recording = True
        print("🎙️  Recording started")
        
        # WebSocketクライアントに通知
        await broadcast_status("recording_started")
        
        return {
            "success": True,
            "message": "Recording started",
            "session_id": state.current_session_id,
            "config": {
                "tmp_dir": request.tmp_dir,
                "target_sink": request.target_sink or "default",
                "transcribe_mode": request.transcribe_mode
            }
        }
        
    except Exception as e:
        state.recording = False
        state.interceptor = None
        state.current_session_id = None
        print(f"❌ Failed to start recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/recording/stop")
async def stop_recording():
    """録音停止"""
    if not state.recording:
        return {"success": False, "message": "Not recording"}
    
    try:
        if state.interceptor:
            state.interceptor.cleanup()
            state.interceptor = None
        
        # セッション終了処理
        if state.current_session_id:
            database.end_session(state.current_session_id)
            print(f"🏁 Session ended: ID {state.current_session_id}")
            state.current_session_id = None
        
        state.recording = False
        print("⏹️  Recording stopped")
        
        # WebSocketクライアントに通知
        await broadcast_status("recording_stopped")
        
        return {"success": True, "message": "Recording stopped"}
        
    except Exception as e:
        print(f"❌ Failed to stop recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/recording")
async def update_recording(request: RecordingUpdateRequest):
    """録音中の設定を更新（タイトル、会議種別）"""
    if not state.recording or not state.current_session_id:
        return {"success": False, "message": "Not recording"}
    
    try:
        conn = database.get_db_connection()
        cursor = conn.cursor()
        
        if request.title is not None:
            cursor.execute('UPDATE sessions SET title = ? WHERE id = ?', (request.title, state.current_session_id))
            print(f"📝 Session title updated: {request.title}")
        
        if request.meeting_type_id is not None:
            cursor.execute('UPDATE sessions SET meeting_type_id = ? WHERE id = ?', (request.meeting_type_id, state.current_session_id))
            state.active_meeting_type_id = request.meeting_type_id
            
            # LLMパイプラインを再初期化
            if state.llm_pipeline and request.meeting_type_id:
                state.llm_pipeline = LLMPipeline(
                    meeting_type_id=request.meeting_type_id,
                    on_advice=on_advice_callback
                )
                print(f"🔄 LLM Pipeline reloaded for meeting type: {request.meeting_type_id}")
            
        conn.commit()
        conn.close()
        
        return {"success": True, "message": "Recording updated"}
        
    except Exception as e:
        print(f"❌ Failed to update recording: {e}")
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

async def broadcast_transcript(source: str, text: str):
    """全接続クライアントに文字起こしを配信"""
    message = {
        "type": "transcript",
        "source": source,  # "speaker" or "mic"
        "text": text
    }
    
    message_str = json.dumps(message)
    
    # 全クライアントに送信
    disconnected = set()
    for client in state.websocket_clients:
        try:
            await client.send_text(message_str)
        except:
            disconnected.add(client)
    
    # 切断されたクライアントを削除
    state.websocket_clients -= disconnected

async def broadcast_advice(advice_data: dict):
    """全接続クライアントにアドバイスを配信"""
    message = advice_data
    # typeはLLMPipeline側ですでに "advice" に設定されている想定だが念のため
    if "type" not in message:
        message["type"] = "advice"
        
    message_str = json.dumps(message)
    
    disconnected = set()
    for client in state.websocket_clients:
        try:
            await client.send_text(message_str)
        except:
            disconnected.add(client)
    state.websocket_clients -= disconnected

async def broadcast_status(status: str):
    """ステータス変更を全クライアントに配信"""
    message = {
        "type": "status",
        "status": status,
        "recording": state.recording
    }
    
    message_str = json.dumps(message)
    
    disconnected = set()
    for client in state.websocket_clients:
        try:
            await client.send_text(message_str)
        except:
            disconnected.add(client)
    
    state.websocket_clients -= disconnected

# --- Master Data APIs ---

@app.get("/meeting-types")
async def list_meeting_types():
    """会議種別一覧を取得"""
    return {"meeting_types": database.get_meeting_types()}

@app.get("/meeting-types/{type_id}/prompts")
async def list_prompts(type_id: int):
    """指定された会議種別のプロンプト一覧を取得"""
    return {"prompts": database.get_prompts_for_type(type_id)}

@app.post("/meeting-types")
async def create_meeting_type(item: MeetingTypeCreate):
    """会議種別を作成"""
    new_id = database.create_meeting_type(item.name, item.description)
    return {"id": new_id, "name": item.name, "description": item.description}

@app.delete("/meeting-types/{type_id}")
async def delete_meeting_type(type_id: int):
    """会議種別を削除"""
    database.delete_meeting_type(type_id)
    return {"success": True}

@app.post("/prompts")
async def create_prompt(item: PromptCreate):
    """プロンプトを作成"""
    new_id = database.create_prompt(item.meeting_type_id, item.trigger_condition, item.action_prompt)
    return {"id": new_id, "meeting_type_id": item.meeting_type_id}

@app.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: int):
    """プロンプトを削除"""
    database.delete_prompt(prompt_id)
    return {"success": True}

# --- History APIs ---

@app.get("/history")
async def list_history():
    """会議履歴一覧を取得"""
    return {"sessions": database.get_sessions()}

@app.get("/history/{session_id}")
async def get_history_details(session_id: int):
    """会議の詳細（ログ・アドバイス）を取得"""
    return database.get_session_details(session_id)

# --- Calendar APIs ---

@app.get("/calendar/current")
async def get_current_calendar_event():
    """現在時刻付近のカレンダーイベントを取得"""
    event = calendar_service.get_current_event()
    if event:
        return {"success": True, "event": event}
    else:
        return {"success": False, "message": "No event found"}

@app.get("/calendar/today")
async def get_today_events():
    """今日のカレンダーイベント一覧を取得"""
    events = calendar_service.get_events_today()
    return {"events": events}

if __name__ == "__main__":
    print("🚀 Starting Meeting Assistant Backend Server...")
    print("   API: http://localhost:8000")
    print("   WebSocket: ws://localhost:8000/ws")
    print("   Docs: http://localhost:8000/docs")
    print("")
    print("🎤 Audio Interceptor: Integrated")
    print("   Virtual Speaker: Virtual_Speaker_Interceptor")
    print("")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
