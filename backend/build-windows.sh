#!/bin/bash
# Windows用バックエンドビルド（WSL/Linux上で実行）
set -e

echo "🔨 Building Python backend for Windows..."

source venv/bin/activate
pip install pyinstaller

pyinstaller --onefile \
  --name server.exe \
  --add-data "meeting_assistant.db;." \
  --hidden-import google.auth \
  --hidden-import google.oauth2 \
  --hidden-import googleapiclient \
  --hidden-import openai \
  --hidden-import fastapi \
  --hidden-import uvicorn \
  --hidden-import websockets \
  --target-arch x86_64 \
  server.py

echo "✅ Windows backend build complete: dist/server.exe"
