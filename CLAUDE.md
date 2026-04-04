# CLAUDE.md

## Project Overview

Meeting Assistant — Electron + Python のデスクトップアプリ。会議音声をリアルタイムで文字起こしし、発言内容に基づく自動リサーチを提供する。

## Tech Stack

- **Backend**: Python 3.10+ / FastAPI / uvicorn / SQLite
- **Frontend**: Electron 40 / vanilla JavaScript (フレームワークなし)
- **Audio**: PulseAudio / PipeWire (Linux)
- **Transcription**: faster-whisper (local) or OpenAI Whisper API
- **LLM**: OpenAI GPT-4o-mini / GPT-4o

## Quick Commands

```bash
# Backend
cd backend && source venv/bin/activate
python3 server.py                    # 起動
uvicorn server:app --reload          # 開発（ホットリロード）

# Frontend
cd frontend
npm start                            # Electron 起動（backend も自動起動）

# Build
cd frontend && npm run build:linux   # Linux (AppImage + deb)
cd backend && ./build.sh             # PyInstaller
```

## Architecture

```
Electron (main/index.js)
  │  spawn python3 server.py
  │  WebSocket ws://localhost:8000/ws
  ▼
FastAPI (server.py)
  ├── audio_interceptor.py    PulseAudio capture
  ├── transcription.py        Whisper (local / API)
  ├── llm_pipeline.py         NER + Research Orchestrator
  ├── research_orchestrator.py  並列リサーチ (LLM, Brave, Limitless)
  ├── slack_service.py        Slack スレッド投稿
  ├── calendar_service.py     Google Calendar 連携
  ├── file_manager.py         Markdown / DOCX export
  └── database.py             SQLite (sessions, transcripts, settings)
```

## Code Conventions

- **Python**: PEP 8 準拠。型ヒント使用 (`Optional`, `Dict`, `List`)。async/await。クラスベース。
- **JavaScript**: vanilla JS, camelCase。IPC (`ipcMain` / `ipcRenderer`)。
- **DB**: SQLite, `sqlite3.Row` で dict-like アクセス。
- **エラーハンドリング**: try-catch + logging。import 失敗時は graceful degradation。
- **UI**: inline CSS, ダークテーマ (`#00ffaa` アクセント)。

## Commit Messages

日本語。必要に応じて `feat:` / `fix:` プレフィックス。

```
feat: マイクミュート機能を追加
fix: 音声ブツブツ問題を修正 (latency 1ms→50ms)
ドキュメント更新: 録音中の設定変更について追記
```

## Key Patterns

- **WebSocket Hub**: server.py が全クライアントに transcription/research 結果をブロードキャスト
- **Research Orchestrator**: `ResearchSource` 基底クラス → 複数ソースを `asyncio.as_completed` で並列実行、完了順に配信
- **Global AppState**: シングルトンで interceptor, llm_pipeline, slack_service を保持
- **Settings**: SQLite `app_settings` テーブル。録音中でも動的リロード対応

## .env (backend/)

```env
WHISPER_MODE=local          # local | api
WHISPER_MODEL=small         # tiny | base | small | medium
WHISPER_LANGUAGE=ja         # ja | en | auto
OPENAI_API_KEY=sk-...       # API mode + research で必須
BRAVE_API_KEY=BSA...        # optional (hybrid research)
LIMITLESS_API_KEY=...       # optional (hybrid research)
```

## Important Notes

- `creds.json` は `.gitignore` 済み。絶対にコミットしない
- `meeting_assistant.db` はローカル開発用。変更があってもコミット不要
- frontend は vanilla JS — React/Vue 等は使っていない
- 音声キャプチャは Linux (PulseAudio/PipeWire) 前提。macOS/Windows は build スクリプトのみ存在
