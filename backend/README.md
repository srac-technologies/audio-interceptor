# Backend - Meeting Assistant

## セットアップ

### 1. 仮想環境をセットアップ

```bash
./setup_venv.sh
```

### 2. 環境変数を設定

`.env`ファイルを作成：

```bash
cp .env.example .env
```

`.env`を編集してOpenAI APIキーを設定：

```
OPENAI_API_KEY=sk-proj-...
```

### 3. サーバーを起動

```bash
./start_server.sh
```

## 環境変数

`.env`ファイルに以下を設定できます：

| 変数名 | 説明 | 必須 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI APIキー（文字起こし用） | 文字起こし機能を使う場合 |

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
[Speaker 🔊] こんにちは
[Mic 🎤] よろしくお願いします
```

## トラブルシューティング

### python-dotenv が見つからない

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### APIキーが無効

`.env`ファイルのAPIキーを確認してください：

```bash
cat .env
```

サーバーを再起動すると新しい設定が反映されます。
