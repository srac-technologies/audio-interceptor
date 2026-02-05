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

try:
    from fastapi import FastAPI, WebSocket, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("⚠️  FastAPI not installed. Install with: pip install fastapi uvicorn websockets")
    sys.exit(1)

# AudioInterceptorをインポート
from audio_interceptor import AudioInterceptor

app = FastAPI(title="Meeting Assistant API")

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

# グローバル状態
class AppState:
    def __init__(self):
        self.recording = False
        self.websocket_clients = set()
        self.interceptor: Optional[AudioInterceptor] = None

state = AppState()

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

@app.post("/recording/start")
async def start_recording(request: RecordingStartRequest):
    """録音開始"""
    if state.recording:
        return {"success": False, "message": "Already recording"}
    
    try:
        # AudioInterceptorインスタンスを作成
        state.interceptor = AudioInterceptor(
            tmp_dir=request.tmp_dir,
            target_sink=request.target_sink,
            transcribe_mode=request.transcribe_mode
        )
        
        # 文字起こしコールバックを登録（WebSocket配信用）
        if request.transcribe_mode:
            # オリジナルのtranscribe_audioメソッドをラップ
            original_transcribe = state.interceptor.transcribe_audio
            
            def transcribe_with_broadcast(filename, label):
                # 元の文字起こし処理を実行
                original_transcribe(filename, label)
                
                # WebSocket経由で配信（非同期なので別途処理が必要）
                # ここでは簡易的にログ出力のみ
                # 実際の配信は後で実装
            
            state.interceptor.transcribe_audio = transcribe_with_broadcast
        
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
            "config": {
                "tmp_dir": request.tmp_dir,
                "target_sink": request.target_sink or "default",
                "transcribe_mode": request.transcribe_mode
            }
        }
        
    except Exception as e:
        state.recording = False
        state.interceptor = None
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
        
        state.recording = False
        print("⏹️  Recording stopped")
        
        # WebSocketクライアントに通知
        await broadcast_status("recording_stopped")
        
        return {"success": True, "message": "Recording stopped"}
        
    except Exception as e:
        print(f"❌ Failed to stop recording: {e}")
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
