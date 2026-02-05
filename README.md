# ⚡ Meeting Assistant

> **AI-Powered Real-time Meeting Transcription & Assistant**  
> 会議を録音・文字起こし・AIアドバイスで、あなたの生産性を爆上げ。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/node-18+-green.svg)](https://nodejs.org/)

[English](#english) | [日本語](#日本語)

---

## 🎯 何ができるの？

- 🎙️ **リアルタイム文字起こし** - WhisperでZoom/Meet等の音声を即座にテキスト化
- 🤖 **AI会議アシスタント** - 文脈を理解して、その場でアドバイス提供
- 🔍 **会議自動検知** - Zoom/Google Meetを検知して録音開始を提案
- 📝 **議事録自動生成** - 終了後、サマリーを自動作成（開発中）
- 🔒 **完全ローカル対応** - faster-whisperでオフライン動作＆プライバシー保護
- 💻 **ハッカーライクUI** - ミニマルなダークテーマで作業効率UP

<p align="center">
  <img src="screenshots/ui-demo.gif" alt="Demo" width="700">
</p>

---

## 🚀 クイックスタート

### 必要要件

- **OS**: Linux（Ubuntu 22.04推奨、PulseAudio/PipeWire必須）
- **Python**: 3.10以上
- **Node.js**: 18以上

### インストール（5分で完了）

```bash
# 1. リポジトリをクローン
git clone https://github.com/yourusername/meeting-assistant.git
cd meeting-assistant

# 2. バックエンドセットアップ
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 環境設定（.envファイル作成）
cp .env.example .env
# エディタで .env を開き、必要に応じてAPIキーを設定

# 4. フロントエンドセットアップ
cd ../frontend
npm install  # または bun install

# 5. 起動！
npm start
```

バックエンドは自動起動しますが、手動で起動する場合：

```bash
cd backend
source venv/bin/activate
python3 server.py
```

---

## 📖 使い方

### 基本的な流れ

1. **アプリを起動** → `npm start`
2. **会議ツールを開く** → Zoom/Google Meet等
3. **通知が来たら「開始する」をクリック** → 自動録音開始
4. **会議に集中** → AIが文字起こし＆アドバイス提供
5. **終了ボタンを押す** → 議事録が保存される

### 文字起こしモード

#### 🌐 API モード（デフォルト）
- OpenAI Whisper API使用
- 高速・高精度
- API料金: $0.006/分

```env
# .env
WHISPER_MODE=api
OPENAI_API_KEY=your-api-key-here
```

#### 🔒 ローカルモード（プライバシー重視）
- faster-whisper使用
- 完全オフライン動作
- 初回のみモデルダウンロード（244MB）

```env
# .env
WHISPER_MODE=local
WHISPER_MODEL=small  # tiny, base, small, medium から選択
WHISPER_LANGUAGE=ja  # ja, en, auto
```

**推奨モデル**: `small`（精度とスピードのバランス◎）

| モデル | サイズ | CPU処理速度* | 精度 | 用途 |
|--------|--------|-------------|------|------|
| tiny   | 39MB   | 5秒/分      | 低   | 超高速 |
| base   | 74MB   | 10秒/分     | 中   | 軽量 |
| **small** | **244MB** | **30秒/分** | **高** | **推奨** |
| medium | 1.5GB  | 60秒/分     | 最高 | GPU推奨 |

*Intel Core i5-1335U での目安

---

## 🎨 機能ハイライト

### 1. システムレベルで音声キャプチャ

PulseAudio/PipeWireを使って、**どんな会議ツールでも**録音可能。会議ツール側の設定変更は不要。

```
[マイク] → [仮想スピーカー] → [実スピーカー]
              ↓
          [録音＆文字起こし]
```

### 2. AIアドバイス機能

会議種別ごとにカスタマイズ可能なプロンプトで、文脈に応じたアドバイスを提供。

例：
- **営業MTG**: 「価格が高い」→ ROI強調を提案
- **技術相談**: 専門用語 → 関連ドキュメント提示
- **1on1**: フィードバック分析 → 改善提案

設定画面から、ノーコードでプロンプトをカスタマイズ可能。

### 3. 会議履歴管理

- 文字起こしテキストの全文検索
- 日付・会議種別でフィルタ
- Markdown形式でエクスポート

### 4. Google Calendar連携

会議タイトルを自動取得。手動入力不要。

```bash
# backend/.env
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account-key.json
```

---

## 🏗️ アーキテクチャ

```
┌─────────────────────────────────────────┐
│          Electron (Frontend)            │
│  - UI (React-like vanilla JS)           │
│  - Meeting Detection (active-win)       │
│  - WebSocket Client                     │
└──────────────┬──────────────────────────┘
               │
               │ WebSocket (ws://localhost:8000/ws)
               │
┌──────────────▼──────────────────────────┐
│      FastAPI Backend (Python)           │
│  - Audio Interceptor (PulseAudio)       │
│  - Transcription Service                │
│    - faster-whisper (local)             │
│    - OpenAI Whisper API                 │
│  - LLM Pipeline (AI Advice)             │
│  - Database (SQLite)                    │
└─────────────────────────────────────────┘
```

---

## 📂 プロジェクト構成

```
meeting-assistant/
├── backend/                    # Python バックエンド
│   ├── server.py              # FastAPI サーバー
│   ├── audio_interceptor.py   # 音声インターセプター
│   ├── transcription.py       # 文字起こしサービス
│   ├── database.py            # SQLite管理
│   ├── llm_pipeline.py        # LLMパイプライン
│   ├── calendar_service.py    # Google Calendar連携
│   ├── requirements.txt       # Python依存関係
│   └── .env                   # 環境設定
├── frontend/                  # Electron フロントエンド
│   ├── main/
│   │   └── index.js          # メインプロセス
│   ├── renderer/
│   │   └── index.html        # レンダラープロセス
│   └── package.json
├── ROADMAP.md                 # 今後の実装予定
├── BLOG_POST.md               # 宣伝用ブログ記事
└── README.md                  # このファイル
```

---

## 🛠️ 開発

### 開発環境のセットアップ

```bash
# バックエンド（ホットリロード）
cd backend
source venv/bin/activate
uvicorn server:app --reload

# フロントエンド（別ターミナル）
cd frontend
npm run dev
```

### テスト

```bash
# 文字起こしサービス単体テスト
cd backend
source venv/bin/activate
python3 transcription.py test_audio.wav

# 自動テストスクリプト
./test_transcription.sh
```

### デバッグモード

```bash
# 開発者ツールを開く
# frontend/main/index.js の以下をコメント解除:
mainWindow.webContents.openDevTools();
```

---

## 🤝 コントリビュート

プルリクエスト大歓迎！以下のガイドラインをご確認ください：

1. Fork してブランチを作成: `git checkout -b feature/amazing-feature`
2. コミット: `git commit -m 'feat: Add amazing feature'`
3. Push: `git push origin feature/amazing-feature`
4. Pull Request を作成

### 貢献できる分野

- 🐛 **バグ修正**: Issueで報告されたバグの修正
- ✨ **新機能**: ROADMAPの機能実装
- 📚 **ドキュメント**: README、コメント、チュートリアル
- 🌍 **翻訳**: UI多言語化
- 🎨 **デザイン**: UIの改善

---

## 📋 ロードマップ

詳細は [ROADMAP.md](ROADMAP.md) を参照。

### 近日実装予定

- [ ] オーバーレイ字幕（会議画面上に表示）
- [ ] 会議サマリー自動生成
- [ ] Chrome拡張連携
- [ ] GPU対応（faster-whisper CUDA）
- [ ] macOS/Windows対応

### 中長期

- [ ] マルチ言語UI
- [ ] チーム機能（議事録共有）
- [ ] モバイルアプリ
- [ ] 感情分析・アナリティクス

---

## 🙏 謝辞

このプロジェクトは以下のオープンソースプロジェクトに支えられています：

- [OpenAI Whisper](https://github.com/openai/whisper) - 音声認識モデル
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - Whisper高速化
- [Electron](https://www.electronjs.org/) - クロスプラットフォームアプリ
- [FastAPI](https://fastapi.tiangolo.com/) - Python Webフレームワーク

---

## 📜 ライセンス

MIT License - 詳細は [LICENSE](LICENSE) を参照

---

## 📞 サポート・コミュニティ

- **GitHub Issues**: バグ報告・機能リクエスト
- **Discord**: [コミュニティリンク予定]
- **Twitter**: [@tan_t](https://twitter.com/tan_t)

---

## ⭐ スターをお願いします！

このプロジェクトが役に立ったら、GitHubでスターをつけてください 🙏

[![GitHub stars](https://img.shields.io/github/stars/yourusername/meeting-assistant.svg?style=social&label=Star)](https://github.com/yourusername/meeting-assistant)

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/yourusername">@tan_t</a>
</p>

<p align="center">
  <sub>会議はコミュニケーションのツールであって、作業ではない。</sub>
</p>
