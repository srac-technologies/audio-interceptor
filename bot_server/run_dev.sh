#!/usr/bin/env bash
# Phase 1 開発用ランナー — bot_server を uvicorn でホットリロード起動。
#
# Usage:
#   BOT_TOKEN=dev-token ./run_dev.sh
#
# 環境変数 (詳細は settings.py):
#   BOT_TOKEN              (必須) shared secret
#   HOST                   bind host (default: 127.0.0.1)
#   PORT                   bind port (default: 8765)
#   DUMMY_PUBLISHER        1/0 (default: 1) — Phase 1 用ダミー publisher
#   DUMMY_INTERVAL         秒 (default: 5)
#   MAX_CONCURRENT_MEETINGS (default: 3)
#   LOG_LEVEL              DEBUG/INFO/WARNING (default: INFO)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PY="${PY:-/home/tan_t/workspace/posture-feedback/.venv/bin/python}"

if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "ERROR: BOT_TOKEN env is required." >&2
  echo "Try: BOT_TOKEN=\$(openssl rand -hex 32) $0" >&2
  exit 64
fi

if [[ ! -x "$PY" ]]; then
  echo "ERROR: python not found at $PY (override with PY=...)" >&2
  exit 2
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"

cd "$REPO_DIR"
exec "$PY" -m uvicorn bot_server.main:app \
  --host "$HOST" --port "$PORT" --reload --reload-dir "$SCRIPT_DIR"
