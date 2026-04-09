# ビルドガイド

## 概要
Meeting Assistant を配布可能なバイナリとしてビルドします。

## 前提条件

- Python 3.10+
- Node.js 20+
- npm

## クロスプラットフォームビルドの制約

**PyInstallerの制約**: Pythonバックエンドは**各プラットフォーム上でビルドする必要があります**。

| ビルド環境 | 生成されるバイナリ |
|-----------|------------------|
| Linux | Linux バイナリのみ |
| macOS | macOS バイナリのみ |
| Windows | Windows .exe のみ |

GitHub Actions CI/CD（`.github/workflows/build.yml`）で各プラットフォームのビルドを自動化済みです。

## プラットフォーム別の依存関係

### Linux

```bash
# 必須: PulseAudio (音声キャプチャ)
sudo apt-get install pulseaudio pulseaudio-utils

# PipeWire環境の場合
sudo apt-get install pipewire-pulse
```

### macOS

仮想音声デバイスが必要（スピーカー音声をキャプチャするため）：

```bash
brew install blackhole-2ch
```

インストール後、Audio MIDI Setup で「複数出力装置」を作成し、BlackHole とスピーカーを含めてください。

### Windows

以下のいずれかが必要：

- **ステレオミキサー**: サウンド設定 → 録音デバイス → ステレオミキサーを有効化
- **VB-Audio Virtual Cable**: https://vb-audio.com/Cable/

## ビルド手順

### Linux用（Linux上で実行）

```bash
cd backend && ./build.sh
cd ../frontend && npm ci && npm run build:linux
```

**成果物**: `frontend/dist/*.AppImage`, `frontend/dist/*.deb`

### macOS用（macOS上で実行）

```bash
cd backend && ./build-macos.sh
cd ../frontend && npm ci && npm run build:mac
```

**成果物**: `frontend/dist/*.dmg`, `frontend/dist/*.zip`

### Windows用（Windows上で実行）

```bash
cd backend && ./build-windows.sh
cd ../frontend && npm ci && npm run build:win
```

**成果物**: `frontend/dist/*.exe`

## CI/CD 自動ビルド

GitHub Actions でタグプッシュ時に自動ビルド＆リリース作成されます：

```bash
git tag v0.1.0
git push origin v0.1.0
```

手動トリガーも可能（Actions → Build & Release → Run workflow）。

## 初回起動時の設定

アプリ起動後、設定画面の「APIキー」タブからAPIキーを設定してください。
すべての設定はアプリ内のデータベースに保存されます。`.env`ファイルは不要です。

### 最小構成

- **OpenAI API Key**: 文字起こし (Whisper API) とリサーチ機能に必要

### オプション

- **Google Service Account**: Google Calendar連携
- **Brave/Tavily/Perplexity API Keys**: ハイブリッドリサーチ機能
- **Azure Speech Key**: Azure音声認識エンジン
- **Anthropic/Google AI API Keys**: LLM精度向上プロバイダ

## 開発モードとの違い

| 項目 | 開発モード | ビルド版 |
|------|-----------|---------|
| バックエンド | `python3 server.py` | バイナリ実行 |
| 設定 | DB (アプリ内UI) | DB (アプリ内UI) |
| データベース | `backend/meeting_assistant.db` | 組み込み（初回コピー） |

## トラブルシューティング

### PyInstallerビルドエラー

依存関係が検出できない場合は `--hidden-import` を追加：

```bash
pyinstaller --onefile --hidden-import <module> server.py
```

### Electronビルドエラー

```bash
cd frontend && rm -rf node_modules package-lock.json && npm install && npm run build
```
