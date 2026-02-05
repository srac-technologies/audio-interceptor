# 🎙️ Meeting Assistant

**AI-Powered Meeting Assistant** - リアルタイム文字起こし＆会議支援システム

## プロジェクト構成

```
audio-interceptor/
├── backend/                    # Python バックエンド
│   ├── audio_interceptor.py   # 音声インターセプター（既存）
│   ├── server.py              # FastAPI サーバー（新規）
│   ├── README.md              # 旧ドキュメント
│   ├── USAGE.md
│   └── PROJECT_SUMMARY.md
├── frontend/                   # Electron フロントエンド
│   ├── main/
│   │   └── index.js           # メインプロセス
│   ├── renderer/
│   │   └── index.html         # レンダラープロセス（UI）
│   ├── package.json
│   └── node_modules/
└── tmp/                        # 録音ファイル保存先
```

## アーキテクチャ

### 1. Electron (フロントエンド)
- **Main Process**: Pythonバックエンドを起動・管理
- **Renderer Process**: React UI（会議中の文字起こし表示、ステータス管理）
- **Detection**: アクティブウィンドウ監視（Zoom、Google Meet等を検知）

### 2. Python Backend (FastAPI)
- **音声インターセプト**: PulseAudio/PipeWire経由で仮想デバイス制御
- **Whisper API**: リアルタイム文字起こし
- **LLM処理**: 会議種別に応じたAIアドバイス生成
- **WebSocket**: Electronへのリアルタイム配信

### 3. 状態管理
- **Idle**: 待機中
- **Standby**: 会議検知済み、ユーザー承認待ち
- **Active**: 録音・文字起こし実行中

## セットアップ

### 必要要件
- **OS**: Linux (PulseAudio/PipeWire)
- **Python**: 3.8以上
- **Node.js**: 18以上（nix profileからbun/node利用）

### インストール

#### 1. Pythonバックエンド
```bash
cd backend
pip install fastapi uvicorn websockets
```

#### 2. Electronフロントエンド
```bash
cd frontend
npm install  # または bun install
```

## 実行

### 開発モード

#### バックエンド起動
```bash
cd backend
python3 server.py
# → http://localhost:8000 で起動
```

#### フロントエンド起動
```bash
cd frontend
npm start  # または bun run start
```

## 現在の実装状況

### ✅ 完了
- [x] 音声インターセプター（単体CLI版）
- [x] Whisper API連携（文字起こし）
- [x] インタラクティブな出力デバイス選択
- [x] Electronプロジェクト構造
- [x] FastAPIサーバー基盤
- [x] UI基礎デザイン（待機画面、録音画面）

### 🚧 実装中
- [ ] ElectronとPython間のWebSocket通信
- [ ] 会議検知機能（プロセス/ウィンドウ監視）
- [ ] Google Calendar連携
- [ ] 会議種別管理とプロンプトDB（SQLite）
- [ ] LLMパイプライン（判定→処理）
- [ ] リアルタイム文字起こし表示
- [ ] AIアドバイス表示

### 📋 今後の予定
- [ ] Chrome拡張（Web会議詳細情報取得）
- [ ] オーバーレイUI（会議画面上に字幕表示）
- [ ] 会議サマリー自動生成
- [ ] 音声アーカイブ管理

## 技術スタック

- **Frontend**: Electron, React (予定), WebSocket
- **Backend**: Python, FastAPI, SQLite
- **Audio**: PulseAudio/PipeWire, `parec`
- **AI**: OpenAI Whisper API, GPT-4 API (予定)
- **Detection**: `active-win` (Node.js), プロセス監視

## 開発履歴

- **2026-02-05**: 初回実装（CLIベースの音声インターセプター）
- **2026-02-05 15:00**: Electron + FastAPI アーキテクチャへ移行開始

## ライセンス

MIT License
