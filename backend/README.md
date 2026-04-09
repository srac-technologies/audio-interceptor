# Backend - Meeting Assistant

## セットアップ

### 1. 仮想環境をセットアップ

```bash
./setup_venv.sh
```

### 2. サーバーを起動

```bash
./start_server.sh
```

### 3. APIキーを設定

アプリ起動後、設定画面の「APIキー」タブからOpenAI APIキーなどを入力してください。
設定はアプリ内のデータベースに保存されます（.envファイルは不要です）。

## プラットフォーム別の依存関係

### Linux (PulseAudio/PipeWire)

```bash
# Ubuntu/Debian
sudo apt-get install pulseaudio pulseaudio-utils

# Fedora
sudo dnf install pulseaudio pulseaudio-utils

# Arch
sudo pacman -S pulseaudio pulseaudio-alsa
```

PipeWire環境では `pipewire-pulse` が必要です：

```bash
# Ubuntu 22.04+
sudo apt-get install pipewire-pulse
```

### macOS

仮想音声デバイスが必要です（スピーカー音声をキャプチャするため）：

```bash
# BlackHole（推奨）
brew install blackhole-2ch
```

インストール後、Audio MIDI Setupで「複数出力装置」を作成し、BlackHoleとスピーカーの両方を含めてください。

### Windows

以下のいずれかの仮想音声デバイスが必要です：

- **ステレオミキサー**: Windowsのサウンド設定で有効化（対応しているサウンドカードのみ）
- **VB-Audio Virtual Cable**: https://vb-audio.com/Cable/ からダウンロード

## APIエンドポイント

### `GET /`
サーバー情報を取得

### `GET /status`
録音状態を確認

### `GET /sinks`
利用可能なオーディオデバイスを取得

### `POST /recording/start`
録音を開始

**リクエストボディ:**
```json
{
  "transcribe_mode": false,
  "tmp_dir": "./tmp",
  "target_sink": null
}
```

### `POST /recording/stop`
録音を停止

## WebSocket

`ws://localhost:8000/ws` でWebSocket接続可能。

リアルタイムの文字起こし結果などが配信されます。

## ログ

文字起こし結果はコンソールに出力されます：

```
[Speaker] こんにちは
[Mic] よろしくお願いします
```
