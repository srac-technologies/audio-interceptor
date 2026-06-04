# bot_server (Phase 2)

リモート常駐型 Google Meet bot サーバー。Meet に参加 → 音声を in-page Web Audio で取得 → faster-whisper で文字起こし → topic 別 WebSocket で fan-out。Phase 0 の入場可否検証で確立した stealth レシピを本実装化。

## ファイル

```
bot_server/
├── main.py              FastAPI app + 4 endpoints + lifespan
├── settings.py          env 読み込み
├── auth.py              Bearer token (constant-time compare)
├── broker.py            in-memory topic pub/sub
├── bot_manager.py       BotSession (subprocess spawn + stdout reader)
├── worker.py            per-meeting subprocess エントリーポイント
├── meet_audio_source.py Playwright で Meet 入場 + 音声 event 公開
├── bootstrap_audio.js   in-page bridge (AudioWorklet + DOM hooks)
├── audio_pipeline.py    PCM チャンク + 無音フィルタ + transcriber 接続
├── transcribers.py      faster-whisper wrapper
├── _fake_worker.py      テスト用 (Meet/Whisper なしで subprocess 経路を確認)
├── requirements.txt
├── setup_venv.sh        venv 構築 (Playwright Chromium インストール込み)
├── run_dev.sh           開発用 uvicorn ランナー
└── spike/               Phase 0 入場可否スパイク (検証済み、参照用)
```

## セットアップ

```bash
cd /home/tan_t/workspace/audio-interceptor
./bot_server/setup_venv.sh           # venv + 依存 + Playwright Chromium
export BOT_TOKEN=$(openssl rand -hex 32)
PY=./bot_server/venv/bin/python ./bot_server/run_dev.sh
```

Whisper モデルは初回 transcribe 時にダウンロードされます (`small` で ~470MB)。事前に `WHISPER_MODEL=tiny` で動作確認推奨。

## 環境変数

| 名前 | デフォルト | 用途 |
|---|---|---|
| `BOT_TOKEN` | **必須** | shared Bearer token (HTTP/WS 両方) |
| `HOST` | `127.0.0.1` | bind host |
| `PORT` | `8765` | bind port |
| `PUBLIC_WS_BASE` | `ws://HOST:PORT` | クライアントに返す ws URL の基底 (リバプロ越しは `wss://...`) |
| `MAX_CONCURRENT_MEETINGS` | `3` | 同時セッション上限 (超過時 503) |
| `IDLE_EVICTION_SECONDS` | `300` | 購読者ゼロからセッション撤収までの猶予 (将来) |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING |
| `DUMMY_PUBLISHER` | `0` | `1` でダミー publisher (Phase 1 fallback)。subprocess を起こさず broker 単体テスト用 |
| `DUMMY_INTERVAL` | `5` | ダミーの間隔秒 |
| `WORKER_PYTHON` | sys.executable | worker subprocess を起動する Python |
| `WORKER_MODULE` | `bot_server.worker` | テストで `bot_server._fake_worker` に差替可 |
| `WORKER_PROFILE_DIR_TEMPLATE` | (空) | 例: `/var/lib/bot/profiles/{topic_key}`。永続 Chrome profile 必須なら設定 |
| `WORKER_HEADLESS` | `0` | `1` で headless (本番では xvfb 推奨で `0` のまま) |
| `WORKER_SHUTDOWN_TIMEOUT` | `30` | SIGTERM 後 SIGKILL までの猶予秒 |
| `CHROME_CHANNEL` | `chrome` | システム Google Chrome (`chrome`) または Playwright bundled (`chromium`) |
| `ADMISSION_TIMEOUT` | `180` | Meet 入場待ちの上限秒 |
| `WHISPER_MODEL` | `small` | `tiny` / `base` / `small` / `medium` / `large-v3` |
| `WHISPER_LANGUAGE` | `ja` | `ja` / `en` / `auto` |
| `CHUNK_SECONDS` | `10` | 文字起こしチャンク窓 |
| `WHISPER_DEVICE` | `auto` | `cpu` / `cuda` / `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` (cpu) | `int8` / `float16` / `float32` |

## エンドポイント

### `POST /bot/join`

```bash
curl -X POST http://127.0.0.1:8765/bot/join \
  -H "Authorization: Bearer $BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"meet_url":"https://meet.google.com/abc-defg-hij","display_name":"Audio Bot"}'
```

```json
{"topic_key":"abc-defg-hij","ws_url":"ws://127.0.0.1:8765/ws/topics/abc-defg-hij"}
```

`meet_url` には `abc-defg-hij` の生コードも受け付けます。

### `POST /bot/leave/{topic_key}`

204 / 404。SIGTERM で worker を停止 → Meet 退室 → "left" 配信。

### `GET /bot/sessions`

アクティブなセッション一覧 (各 topic_key の subscriber 数も)。

### `WSS /ws/topics/{topic_key}?token=<BOT_TOKEN>`

購読側 — JSON ストリーム:

```json
{"type":"status","state":"joining|joined|left|error","detail":"...","topic_key":"...","ts":"..."}
{"type":"transcript","source":"meet","speaker":"<name|null>","text":"...","ts":"...","language":"ja","duration_s":7.4}
```

## スモークテスト

### A. Meet なしで subprocess パスを試す (fake worker)

```bash
BOT_TOKEN=devtoken \
WORKER_MODULE=bot_server._fake_worker \
DUMMY_PUBLISHER=0 \
./bot_server/run_dev.sh
```

別端末:

```bash
npx wscat -c "ws://127.0.0.1:8765/ws/topics/abc-defg-hij?token=devtoken"
# 別端末で:
curl -X POST http://127.0.0.1:8765/bot/join \
  -H "Authorization: Bearer devtoken" -H "Content-Type: application/json" \
  -d '{"meet_url":"abc-defg-hij","display_name":"Demo"}'
# 数秒待つと擬似 transcript が来る
curl -X POST http://127.0.0.1:8765/bot/leave/abc-defg-hij -H "Authorization: Bearer devtoken"
```

期待される出力:

```
< {"type":"status","state":"joining"}                # BotSession から
< {"type":"status","state":"joining","detail":"fake worker"}  # worker から
< {"type":"status","state":"joined","detail":"fake admitted"}
< {"type":"transcript","speaker":"Demo","text":"..."}   # 2秒おき
< {"type":"status","state":"left","detail":"fake worker exit"}
```

### B. 実 Meet で end-to-end

1. テスト用 Meet ルームを別アカウントで作成 + ホスト admission をオフ (誰でも入れる) もしくは admit する人を用意。
2. ```bash
   BOT_TOKEN=devtoken WORKER_HEADLESS=0 WHISPER_MODEL=tiny \
   ./bot_server/run_dev.sh
   ```
3. wscat で `/ws/topics/{code}` に購読。
4. `curl POST /bot/join`。bot Chrome が立ち上がり Meet に入場 → 数秒で transcript が流れ始める。
5. `curl POST /bot/leave/{code}` で bot 退室。

注意:
- Bot は **persistent Chrome profile** が無いと毎回 "ゲスト" 扱いで多くの Meet ルームは admission 待ち。`WORKER_PROFILE_DIR_TEMPLATE` を設定 + 初回は手動で Google サインインを済ませた profile dir を用意推奨。
- 1 Meet あたり 1 Chrome (heavy)。`MAX_CONCURRENT_MEETINGS=3` を超えると 503。
- `WHISPER_MODEL=tiny` は精度を犠牲に CPU 軽め (~75MB)。`small` 以上推奨。

## 内部プロトコル (worker subprocess 出力)

bot_server.worker は **stdout に 1 行 1 JSON object** で次を出力:

```json
{"type":"status","state":"joining","detail":"launching chromium","ts":"..."}
{"type":"status","state":"joining","detail":"navigating to https://meet.google.com/..."}
{"type":"status","state":"joined","detail":"bridge installed; awaiting audio"}
{"type":"status","state":"joined","detail":"loading transcription model"}
{"type":"status","state":"joined","detail":"transcribing"}
{"type":"transcript","source":"meet","speaker":"...","text":"...","ts":"...","language":"ja","duration_s":9.8}
{"type":"status","state":"left","detail":"worker exited"}
```

`stderr` はログ。BotManager が `worker[<topic_key>]: ...` プレフィックス付きで親ロガーに転送。

## 次 (Phase 3)

Chrome 拡張 (Manifest V3) で Meet タブ上に overlay 表示。`meet.google.com/<code>` の URL から自動 topic 購読。
