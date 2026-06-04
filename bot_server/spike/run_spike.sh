#!/usr/bin/env bash
# Phase 0 spike runner — Meet 入場 & Web Audio PCM 取得を試す。
#
# Usage:
#   ./run_spike.sh <meet-url> [duration_sec]
#
# Example:
#   ./run_spike.sh https://meet.google.com/abc-defg-hij 60
#
# 環境変数で挙動を調整可能:
#   POSTURE_VENV     posture-feedback の venv (default: 既知のパス)
#   CHANNEL          chromium channel ('chrome' or 'chromium', default: chrome)
#   PROFILE_DIR      Chrome の persistent profile dir
#   ADMISSION_TO     admission 待ち秒数 (default: 180)
#   WAV_OUT          出力 WAV パス (default: 自動命名)
#   SHOTS_DIR        定期スクショ保存ディレクトリ (default: 自動命名)
#   SHOTS_INTERVAL   スクショ間隔秒 (default: 5)
#   BOT_NAME         Meet 入場時の表示名 (default: 'Audio Spike Bot')
#   INJECT_WHEN      'pre' or 'post' (default: post)
#                    pre  = add_init_script を navigate 前に注入(危険・蹴られやすい)
#                    post = 入場成功後に注入(posture-feedback と同じパターン)
#   DRIVER           'playwright' (default) or 'patchright'
#                    playwright = plain Playwright + stealth flag
#                    patchright = posture-feedback と同じ stealth fork
#   INSTALL_BROWSER  '1' で playwright install chromium を毎回走らせる
#   XVFB             'auto' (default) / 'always' / 'never'
#                    auto は $DISPLAY が空なら xvfb-run で包む

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <meet-url> [duration_sec]" >&2
  echo "Example: $0 https://meet.google.com/abc-defg-hij 60" >&2
  exit 64
fi

MEET_URL="$1"
DURATION="${2:-60}"

POSTURE_VENV="${POSTURE_VENV:-/home/tan_t/workspace/posture-feedback/.venv}"
CHANNEL="${CHANNEL:-chrome}"
PROFILE_DIR="${PROFILE_DIR:-$HOME/.cache/meet-audio-spike-profile}"
ADMISSION_TO="${ADMISSION_TO:-180}"
TS="$(date +%Y%m%d_%H%M%S)"
WAV_OUT="${WAV_OUT:-$SCRIPT_DIR/spike_audio_${TS}.wav}"
SHOTS_DIR="${SHOTS_DIR:-$SCRIPT_DIR/shots_${TS}}"
SHOTS_INTERVAL="${SHOTS_INTERVAL:-5}"
BOT_NAME="${BOT_NAME:-Audio Spike Bot}"
INJECT_WHEN="${INJECT_WHEN:-post}"
DRIVER="${DRIVER:-playwright}"
XVFB="${XVFB:-auto}"

PY="$POSTURE_VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: python not found at $PY" >&2
  echo "POSTURE_VENV を正しく指してください (例: POSTURE_VENV=/path/to/venv $0 ...)" >&2
  exit 2
fi

if [[ "${INSTALL_BROWSER:-0}" == "1" ]]; then
  echo "[+] playwright install chromium"
  "$PY" -m playwright install chromium
fi

if ! "$PY" -c "import playwright" 2>/dev/null; then
  echo "ERROR: playwright が $PY で import できません。venv を見直してください。" >&2
  exit 3
fi

# Xvfb 判定
use_xvfb=0
case "$XVFB" in
  always) use_xvfb=1 ;;
  never)  use_xvfb=0 ;;
  auto)
    if [[ -z "${DISPLAY:-}" ]]; then use_xvfb=1; fi
    ;;
  *)
    echo "ERROR: XVFB は auto|always|never のいずれか (got: $XVFB)" >&2
    exit 64
    ;;
esac

if [[ "$use_xvfb" -eq 1 ]]; then
  if ! command -v xvfb-run >/dev/null 2>&1; then
    echo "ERROR: xvfb-run が見つかりません。apt install xvfb してください。" >&2
    exit 4
  fi
fi

mkdir -p "$SHOTS_DIR"

echo "[+] meet_url        : $MEET_URL"
echo "[+] duration        : ${DURATION}s"
echo "[+] python          : $PY"
echo "[+] chrome channel  : $CHANNEL"
echo "[+] profile dir     : $PROFILE_DIR"
echo "[+] admission to    : ${ADMISSION_TO}s"
echo "[+] wav out         : $WAV_OUT"
echo "[+] shots dir       : $SHOTS_DIR (interval ${SHOTS_INTERVAL}s)"
echo "[+] bot name        : $BOT_NAME"
echo "[+] inject when     : $INJECT_WHEN"
echo "[+] driver          : $DRIVER"
echo "[+] xvfb            : $([[ $use_xvfb -eq 1 ]] && echo on || echo off)"
echo

cmd=(
  "$PY" "$SCRIPT_DIR/spike_audio.py"
  --meet-url "$MEET_URL"
  --duration "$DURATION"
  --channel "$CHANNEL"
  --profile-dir "$PROFILE_DIR"
  --admission-timeout "$ADMISSION_TO"
  --wav-out "$WAV_OUT"
  --shots-dir "$SHOTS_DIR"
  --shots-interval "$SHOTS_INTERVAL"
  --bot-name "$BOT_NAME"
  --inject-when "$INJECT_WHEN"
  --driver "$DRIVER"
)

if [[ "$use_xvfb" -eq 1 ]]; then
  # 1280x800 は Meet がモバイル UI に落ちない最低限の大きさ目安。
  exec xvfb-run -a -s "-screen 0 1280x800x24" "${cmd[@]}"
else
  exec "${cmd[@]}"
fi
