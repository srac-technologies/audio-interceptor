#!/bin/bash
# Start the backend server with venv

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# venvが存在するか確認
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment not found."
    echo "   Please run ./setup_venv.sh first."
    exit 1
fi

# venvをアクティベート
echo "🔌 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# サーバーを起動
echo "🚀 Starting backend server..."
echo "   API: http://localhost:8000"
echo "   WebSocket: ws://localhost:8000/ws"
echo "   Docs: http://localhost:8000/docs"
echo ""
python3 server.py
