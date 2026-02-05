#!/bin/bash
# macOS用バックエンドビルド（macOS上で実行）
set -e

echo "🔨 Building Python backend for macOS..."

source venv/bin/activate
pip install pyinstaller

pyinstaller --onefile \
  --name server \
  --add-data "meeting_assistant.db:." \
  --hidden-import google.auth \
  --hidden-import google.oauth2 \
  --hidden-import googleapiclient \
  --hidden-import openai \
  --hidden-import fastapi \
  --hidden-import uvicorn \
  --hidden-import websockets \
  --target-arch universal2 \
  server.py

echo "✅ macOS backend build complete: dist/server"
