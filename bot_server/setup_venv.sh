#!/usr/bin/env bash
# bot_server 専用 venv 構築 (Phase 2)
#
# Usage:
#   ./bot_server/setup_venv.sh                  # bot_server/venv を作る
#   PY=python3.12 ./bot_server/setup_venv.sh    # 別 python で
#   SKIP_BROWSER=1 ./bot_server/setup_venv.sh   # playwright install を飛ばす

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

PY="${PY:-python3}"

if [[ -d "$VENV_DIR" ]]; then
  echo "[+] venv already exists at $VENV_DIR; reusing"
else
  echo "[+] creating venv at $VENV_DIR using $PY"
  "$PY" -m venv "$VENV_DIR"
fi

VPY="$VENV_DIR/bin/python"
"$VPY" -m pip install --upgrade pip wheel
"$VPY" -m pip install -r "$SCRIPT_DIR/requirements.txt"

if [[ "${SKIP_BROWSER:-0}" != "1" ]]; then
  echo "[+] installing Playwright Chromium driver"
  "$VPY" -m playwright install chromium
else
  echo "[+] SKIP_BROWSER=1 — Playwright Chromium install skipped"
fi

cat <<EOF
[OK] bot_server venv ready at $VENV_DIR
- Activate: source $VENV_DIR/bin/activate
- Run dev:  PY=$VPY BOT_TOKEN=devtoken ./bot_server/run_dev.sh
EOF
