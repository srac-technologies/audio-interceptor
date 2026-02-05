#!/bin/bash
# Backend venv setup script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

echo "🚀 Setting up Python virtual environment..."

# Python3が利用可能か確認
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 not found. Please install Python 3.8 or later."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "   Python version: $PYTHON_VERSION"

# venvを作成
if [ -d "$VENV_DIR" ]; then
    echo "⚠️  venv directory already exists. Remove it? [y/N]"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo "   Removing existing venv..."
        rm -rf "$VENV_DIR"
    else
        echo "   Using existing venv."
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# venvをアクティベート
echo "🔌 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# pipをアップグレード
echo "⬆️  Upgrading pip..."
pip install --upgrade pip

# 依存関係をインストール
echo "📥 Installing dependencies..."
pip install fastapi uvicorn websockets

echo ""
echo "✅ Setup complete!"
echo ""
echo "To activate the virtual environment, run:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo "To start the backend server:"
echo "   cd $SCRIPT_DIR"
echo "   source venv/bin/activate"
echo "   python3 server.py"
echo ""
