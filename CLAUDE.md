# CLAUDE.md

## Project Overview

Meeting Assistant — Electron + Python のデスクトップアプリ。会議音声をリアルタイムで文字起こしし、発言内容に基づく自動リサーチを提供する。

## Tech Stack

- **Backend**: Python 3.10+ / FastAPI / uvicorn / SQLite
- **Frontend**: Electron 40 + Chrome Extension / vanilla JavaScript (フレームワークなし)
- **Frontend Architecture**: shared/ (プラットフォーム共通UI) + renderer/ (Electron) + chrome-extension/ (Chrome)
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
frontend/
├── shared/                    プラットフォーム共通コード
│   ├── css/theme.css          共通テーマ (CSS Variables)
│   ├── api/client.js          ApiClient (HTTP + WebSocket)
│   ├── platform.js            PlatformAdapter インターフェース
│   └── components/            再利用可能UIコンポーネント
│       ├── transcript-panel.js   文字起こし表示
│       ├── research-panel.js     リサーチ結果表示
│       ├── settings-modal.js     設定画面
│       └── history-modal.js      履歴画面
├── main/index.js              Electron main process
├── renderer/                  Electron renderer
│   ├── index.html             シェル HTML (shared CSS を参照)
│   ├── app.js                 Electron アプリブートストラップ
│   └── platform-electron.js   Electron アダプタ (IPC)
└── chrome-extension/          Chrome Extension
    ├── manifest.json
    ├── background.js
    └── sidepanel/
        ├── index.html         シェル HTML (shared CSS を参照)
        ├── app.js             Chrome アプリブートストラップ
        └── platform-chrome.js Chrome アダプタ (HTTP直接)

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
- **JavaScript**: vanilla JS (ES Modules), camelCase。共通コードは shared/ に、プラットフォーム固有は各 adapter に分離。
- **DB**: SQLite, `sqlite3.Row` で dict-like アクセス。
- **エラーハンドリング**: try-catch + logging。import 失敗時は graceful degradation。
- **UI**: 共通テーマ CSS (`shared/css/theme.css`), CSS Variables, ダークテーマ (`#00ffaa` アクセント)。`ma-` プレフィックスで名前空間。

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
- **PlatformAdapter**: Electron/Chrome Extension の差異を吸収。UI コンポーネントは adapter 経由でプラットフォーム機能にアクセス
- **ApiClient**: HTTP + WebSocket をラップ。イベントベースでメッセージをディスパッチ

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
