#!/usr/bin/env python3
"""
Meeting Assistant - Backend Server (FastAPI)
"""

import asyncio
import sys
from pathlib import Path

# TODO: FastAPIとWebSocketのインストールが必要
# pip install fastapi uvicorn websockets

try:
    from fastapi import FastAPI, WebSocket
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("⚠️  FastAPI not installed. Install with: pip install fastapi uvicorn websockets")
    sys.exit(1)

app = FastAPI(title="Meeting Assistant API")

# CORS設定（Electronからのアクセスを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル状態
class AppState:
    def __init__(self):
        self.recording = False
        self.websocket_clients = set()

state = AppState()

@app.get("/")
async def root():
    return {
        "service": "Meeting Assistant Backend",
        "version": "0.1.0",
        "status": "running"
    }

@app.get("/status")
async def get_status():
    return {
        "recording": state.recording,
        "connected_clients": len(state.websocket_clients)
    }

@app.post("/recording/start")
async def start_recording():
    """録音開始"""
    if state.recording:
        return {"success": False, "message": "Already recording"}
    
    state.recording = True
    print("🎙️  Recording started")
    
    # TODO: audio_interceptor.py の機能を統合
    
    return {"success": True, "message": "Recording started"}

@app.post("/recording/stop")
async def stop_recording():
    """録音停止"""
    if not state.recording:
        return {"success": False, "message": "Not recording"}
    
    state.recording = False
    print("⏹️  Recording stopped")
    
    return {"success": True, "message": "Recording stopped"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket接続（リアルタイム文字起こし配信用）"""
    await websocket.accept()
    state.websocket_clients.add(websocket)
    print(f"✅ WebSocket client connected. Total: {len(state.websocket_clients)}")
    
    try:
        while True:
            # クライアントからのメッセージを受信（keep-alive）
            data = await websocket.receive_text()
            
            # テスト用：エコーバック
            await websocket.send_text(f"Server received: {data}")
            
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        state.websocket_clients.remove(websocket)
        print(f"❌ WebSocket client disconnected. Total: {len(state.websocket_clients)}")

async def broadcast_transcript(source: str, text: str):
    """全接続クライアントに文字起こしを配信"""
    message = {
        "type": "transcript",
        "source": source,  # "speaker" or "mic"
        "text": text
    }
    
    import json
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

if __name__ == "__main__":
    print("🚀 Starting Meeting Assistant Backend Server...")
    print("   API: http://localhost:8000")
    print("   WebSocket: ws://localhost:8000/ws")
    print("   Docs: http://localhost:8000/docs")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
