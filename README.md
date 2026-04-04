# Meeting Assistant

> **AI-Powered Real-time Meeting Transcription & Research**
> 会議の音声をリアルタイムで文字起こしし、発言内容に基づく自動リサーチで会議の質を向上させる。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Electron](https://img.shields.io/badge/electron-40+-9feaf9.svg)](https://www.electronjs.org/)

---

## Architecture

```
 +------------------------------------------------------------------+
 |                        Electron (Desktop App)                     |
 |                                                                   |
 |   +------------------+  +------------------+  +---------------+  |
 |   | Meeting Detector  |  |   Renderer UI    |  |  Tray Icon    |  |
 |   | (active-win)     |  |   (vanilla JS)   |  |  & Controls   |  |
 |   +--------+---------+  +--------+---------+  +-------+-------+  |
 |            |                      |                    |          |
 +------------|----------------------|--------------------|-----------+
              |                      |                    |
              |    WebSocket (ws://localhost:8000/ws)      |
              +------------------+   +--------------------+
                                 |   |
 +-------------------------------|---|-------------------------------+
 |                        FastAPI Backend                            |
 |                                                                   |
 |   +-------------------+    +--------------------+                 |
 |   | Audio Interceptor |    |  Transcription Svc |                 |
 |   | (PulseAudio /     |--->|  - faster-whisper   |                 |
 |   |  PipeWire)        |    |  - OpenAI Whisper   |                 |
 |   +-------------------+    +--------+-----------+                 |
 |                                     |                             |
 |                          +----------v-----------+                 |
 |                          | Research Orchestrator |                 |
 |                          | (parallel execution)  |                 |
 |                          +--+-------+-----+--+                    |
 |                             |       |       |                     |
 |                +------------+  +----+----+  +------------+       |
 |                |  LLM       |  |  Brave  |  | Limitless  |       |
 |                |  Pipeline  |  | Search  |  |  API       |       |
 |                +------------+  +---------+  +------------+       |
 |                                                                   |
 |   +---------------+  +----------------+  +-------------------+   |
 |   | SQLite DB     |  | File Manager   |  | Slack Service     |   |
 |   | (sessions,    |  | (Markdown/DOCX |  | (thread posting)  |   |
 |   |  transcripts) |  |  export)       |  |                   |   |
 |   +---------------+  +----------------+  +-------------------+   |
 |                                                                   |
 |   +-------------------+                                           |
 |   | Google Calendar   |                                           |
 |   | (title auto-fill) |                                           |
 |   +-------------------+                                           |
 +-------------------------------------------------------------------+

 Audio Flow:
 +---------+     +------------------+     +---------------+
 | Mic /   |---->| Virtual Sink     |---->| Real Speaker  |
 | App     |     | (PulseAudio)     |     | (output)      |
 +---------+     +--------+---------+     +---------------+
                          |
                          v
                  +-------+--------+
                  | Recording &    |
                  | Transcription  |
                  +----------------+
```

---

## Features

- **Real-time Transcription** - Whisper (API / local faster-whisper) で音声を即座にテキスト化
- **Research Orchestrator** - 発言内容から人名・企業名を抽出し、複数ソースで並列リサーチ
- **Meeting Auto-detection** - Zoom / Google Meet を検知して録音開始を提案
- **Slack Integration** - リサーチ結果をSlackスレッドにリアルタイム投稿
- **Google Calendar** - 会議タイトルを自動取得
- **File Export** - Markdown / DOCX 形式で議事録エクスポート
- **Fully Local Mode** - faster-whisper でオフライン動作 & プライバシー保護
- **Recording-time Settings** - 録音中でも設定変更が可能

---

## Quick Start

### Requirements

- **OS**: Linux (Ubuntu 22.04+, PulseAudio / PipeWire)
- **Python**: 3.10+
- **Node.js**: 18+

### Install

```bash
git clone https://github.com/srac-technologies/audio-interceptor.git
cd audio-interceptor

# Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit as needed

# Frontend
cd ../frontend
npm install

# Launch
npm start
```

Backend auto-starts with Electron. To run manually:

```bash
cd backend && source venv/bin/activate && python3 server.py
```

---

## Transcription Modes

### API Mode (default)

```env
WHISPER_MODE=api
OPENAI_API_KEY=your-api-key
```

### Local Mode (offline)

```env
WHISPER_MODE=local
WHISPER_MODEL=small   # tiny | base | small | medium
WHISPER_LANGUAGE=ja   # ja | en | auto
```

| Model  | Size   | Speed (CPU)* | Accuracy | Notes      |
|--------|--------|-------------|----------|------------|
| tiny   | 39MB   | ~5s/min     | Low      | Fastest    |
| base   | 74MB   | ~10s/min    | Medium   | Lightweight|
| **small** | **244MB** | **~30s/min** | **High** | **Recommended** |
| medium | 1.5GB  | ~60s/min    | Highest  | GPU recommended |

*Benchmarked on Intel Core i5-1335U

---

## Project Structure

```
audio-interceptor/
├── backend/
│   ├── server.py                # FastAPI server & WebSocket hub
│   ├── audio_interceptor.py     # PulseAudio/PipeWire capture
│   ├── transcription.py         # Whisper transcription service
│   ├── research_orchestrator.py # Parallel research engine
│   ├── llm_pipeline.py          # LLM pipeline (advice/summary)
│   ├── slack_service.py         # Slack thread posting
│   ├── calendar_service.py      # Google Calendar integration
│   ├── file_manager.py          # Markdown/DOCX export
│   ├── database.py              # SQLite management
│   └── requirements.txt
├── frontend/
│   ├── main/index.js            # Electron main process
│   ├── renderer/index.html      # UI (vanilla JS, dark theme)
│   └── package.json
├── ROADMAP.md
├── CHANGELOG.md
└── README.md
```

---

## Development

```bash
# Backend (hot reload)
cd backend && source venv/bin/activate
uvicorn server:app --reload

# Frontend (separate terminal)
cd frontend && npm run dev
```

---

## License

MIT
