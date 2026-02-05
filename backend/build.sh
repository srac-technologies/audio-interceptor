#!/bin/bash
set -e

echo "🔨 Building Python backend..."

# venvをアクティベート
source venv/bin/activate

# PyInstallerをインストール（まだの場合）
pip install pyinstaller

# ビルド
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
  server.py

echo "✅ Backend build complete: dist/server"
