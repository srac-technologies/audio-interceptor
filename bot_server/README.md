# bot_server (Phase 1: skeleton)

リモート常駐型 Meet bot サーバーの土台。Phase 1 は **FastAPI + in-memory topic broker + ダミー publisher** までで、実際の Meet bot ワーカーは Phase 2 で追加。

## ファイル

```
bot_server/
├── main.py          FastAPI app + ルーティング
├── settings.py      env 読み込み
├── auth.py          Bearer token 検証
├── broker.py        topic 別 WebSocket fan-out
├── bot_manager.py   セッション管理 + ダミー publisher
├── requirements.txt
├── run_dev.sh       開発用 uvicorn ランナー
└── spike/           Phase 0 のスパイク (Meet 入場検証)
```

## 起動 (開発)

```bash
cd /home/tan_t/workspace/audio-interceptor
export BOT_TOKEN=$(openssl rand -hex 32)
./bot_server/run_dev.sh
```

デフォルトでは `127.0.0.1:8765` で listen。posture-feedback の venv (Python 3.12, fastapi 0.136 入り) を流用しています。別 venv を使う場合は `PY=/path/to/python ./bot_server/run_dev.sh`。

## 環境変数

| 名前 | デフォルト | 用途 |
|---|---|---|
| `BOT_TOKEN` | **必須** | shared Bearer token (HTTP/WS 両方) |
| `HOST` | `127.0.0.1` | bind host |
| `PORT` | `8765` | bind port |
| `PUBLIC_WS_BASE` | `ws://HOST:PORT` | クライアントに返す ws URL の基底。リバプロ越しなら `wss://example.com` |
| `MAX_CONCURRENT_MEETINGS` | `3` | 同時セッション上限 (超過時 503) |
| `IDLE_EVICTION_SECONDS` | `300` | 購読者ゼロからセッション撤収までの猶予 (Phase 1 未実装) |
| `DUMMY_PUBLISHER` | `1` | Phase 1 だけ用のダミー文字起こし発火 |
| `DUMMY_INTERVAL` | `5` | ダミーの間隔秒 |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING |

## エンドポイント

### `POST /bot/join`

```bash
curl -X POST http://127.0.0.1:8765/bot/join \
  -H "Authorization: Bearer $BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"meet_url":"https://meet.google.com/abc-defg-hij","display_name":"Audio Bot"}'
```

レスポンス:

```json
{"topic_key":"abc-defg-hij","ws_url":"ws://127.0.0.1:8765/ws/topics/abc-defg-hij"}
```

`meet_url` には `abc-defg-hij` の生コードも受け付けます。

### `POST /bot/leave/{topic_key}`

```bash
curl -X POST http://127.0.0.1:8765/bot/leave/abc-defg-hij \
  -H "Authorization: Bearer $BOT_TOKEN"
```

204 (成功) / 404 (該当無し)。

### `GET /bot/sessions`

アクティブなセッション一覧。

### `WSS /ws/topics/{topic_key}?token=<BOT_TOKEN>`

購読側。受信メッセージは JSON、`type` で分岐:

```json
{"type":"status","state":"joining|joined|left","topic_key":"...","ts":"..."}
{"type":"transcript","source":"meet","speaker":"...","text":"...","ts":"..."}
```

## スモークテスト (wscat + curl)

ターミナル A — bot_server 起動:

```bash
BOT_TOKEN=devtoken ./bot_server/run_dev.sh
```

ターミナル B — 購読:

```bash
npx wscat -c "ws://127.0.0.1:8765/ws/topics/abc-defg-hij?token=devtoken"
```

ターミナル C — join:

```bash
curl -X POST http://127.0.0.1:8765/bot/join \
  -H "Authorization: Bearer devtoken" \
  -H "Content-Type: application/json" \
  -d '{"meet_url":"abc-defg-hij","display_name":"Demo"}'
```

期待される B の出力:

```
< {"type":"status","state":"joining",...}
< {"type":"status","state":"joined",...}
< {"type":"transcript","source":"meet","speaker":"Demo","text":"...",...}  (5秒おき)
...
```

`DUMMY_PUBLISHER=0` を立てるとダミー出力は止まります。Phase 2 で実 bot に置き換えたら無効化推奨。

## 次 (Phase 2)

`bot_server/worker.py` (subprocess per meeting) + `meet_audio_source.py` (Phase 0 スパイクの本実装) + `transcribers/` (faster-whisper) を追加して、`bot_manager.BotSession.start()` を「`asyncio.create_subprocess_exec(worker.py)`」に差し替える。
