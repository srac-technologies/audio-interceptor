# Backend クイックスタート

## セットアップ（初回のみ）

```bash
cd ~/workspace/audio-interceptor/backend
./setup_venv.sh
```

このスクリプトは以下を実行します：
- Python仮想環境（venv）の作成
- pipのアップグレード
- 必要なパッケージのインストール（fastapi、uvicorn、websockets）

## サーバー起動

```bash
cd ~/workspace/audio-interceptor/backend
./start_server.sh
```

または、手動でvenvをアクティベート：

```bash
cd ~/workspace/audio-interceptor/backend
source venv/bin/activate
python3 server.py
```

サーバーが起動すると、**自動的に仮想スピーカー `Virtual_Speaker_Interceptor` が使用可能になります**（録音開始時に作成されます）。

## 動作確認

### 方法1: テストスクリプトを使用（推奨）

```bash
cd ~/workspace/audio-interceptor/backend
./test_api.sh
```

### 方法2: 手動でcurl

別のターミナルで：

```bash
# ステータス確認
curl http://localhost:8000/

# 利用可能なスピーカー一覧
curl http://localhost:8000/sinks

# 録音開始（録音のみ）
curl -X POST http://localhost:8000/recording/start \
  -H "Content-Type: application/json" \
  -d '{"transcribe_mode": false}'

# 録音開始（文字起こし有効）※OPENAI_API_KEY必要
curl -X POST http://localhost:8000/recording/start \
  -H "Content-Type: application/json" \
  -d '{"transcribe_mode": true}'

# ステータス確認
curl http://localhost:8000/status

# 録音停止
curl -X POST http://localhost:8000/recording/stop
```

**重要:** 録音を開始すると、仮想スピーカー `Virtual_Speaker_Interceptor` が作成されます。
これをWeb会議アプリのスピーカー設定で選択してください。

## ブラウザでドキュメント表示

FastAPIの自動生成ドキュメント：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## トラブルシューティング

### venvが見つからない

```bash
./setup_venv.sh
```

### ポート8000が既に使用されている

他のプロセスを停止するか、`server.py` の `port` を変更してください。

```python
# server.py の最後
uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")
```

### Python 3.8以上が必要

```bash
python3 --version
```

3.8未満の場合は、Pythonをアップグレードしてください。
