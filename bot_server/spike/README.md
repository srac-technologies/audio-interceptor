# Phase 0 spike: Web Audio API capture from Google Meet

これは **plan の Phase 0** に対応するスパイクスクリプトです。目的は1つ:

> stealth 無し(通常 Playwright + 通常 Chromium + autoplay flag) で
> `RTCPeerConnection.prototype` を patch して in-page Web Audio API 経路で
> PCM を取得できるか、Meet が anti-bot で蹴らないかを実測する。

結果でその後の bot_server の音声ソース実装方針が分岐します。

## セットアップ

posture-feedback の venv に Playwright が既に入っているので流用します:

```bash
POSTURE_VENV=/home/tan_t/workspace/posture-feedback/.venv
$POSTURE_VENV/bin/python -m playwright install chromium  # 初回のみ
```

「Google Chrome そのもの」を使いたい場合は別途 `google-chrome` (system Chrome) を
インストールしておく。`--channel chrome` でそちらを起動します(Patchright 推奨と同じ)。
スパイクではこれを優先。`--channel chromium` で Playwright バンドル版にもできます。

## 検証手順

1. 別の Google アカウントで自分用テスト Meet ルームを作る。  
   `https://meet.google.com/xxx-yyyy-zzz`
2. ルームに入って、誰かに発話してもらうか OS のスピーカーで音楽等を出しておく
   (bot が「聞こえる」状態にする)。
3. 別端末/別ユーザーで以下を実行:

   ```bash
   cd /home/tan_t/workspace/audio-interceptor/bot_server/spike
   $POSTURE_VENV/bin/python spike_audio.py \
     --meet-url https://meet.google.com/xxx-yyyy-zzz \
     --duration 60
   ```

4. 初回はサインインしていない素のプロファイル。ブラウザが開いたら手動で
   Google にサインインしておくと次回以降は自動入室がスムーズ。

## 観測ポイント

スパイクスクリプトは終了時に JSON レポートを stdout に吐きます。重要な項目:

| 値 | 意味 |
|---|---|
| `notes: "anti-bot wall detected ..."` | **NG**: Meet が画面遷移段階で "You can't join" を出した = stealth 無し+早期 patch ルートは死。 |
| `join_admitted: false` + `notes: "admission_timeout"` | 画面遷移はしたが入場できず。要観察(host 不在 / 待機室で放置されただけの可能性も)。 |
| `js_stats.pcs_constructed > 0` & `audio_tracks_seen > 0` & `chunks_received > 0` | **OK**: RTCPeerConnection 経由で音声トラックが取れて PCM が来ている。 |
| `pcs_constructed > 0` だが `audio_tracks_seen == 0` | PC は作られているが音声 track が来ていない。Meet が静まり返っているか、Meet 仕様変更の可能性。 |
| `audio_context_state: "suspended"` のまま | autoplay 許可が効いていない。flag を見直す。 |
| `wav_out` に書かれた WAV を再生して人間の声が聞こえる | 完全 OK。Phase 2 で `bot_server/bootstrap_audio.js` として正式化。 |

## 結果による分岐

- **OK** (PCM が継続的に届く、wall 出ない) → Plan の **Phase 1 Web Audio パス**へ。
- **NG** (wall または admission_timeout 多発) → 速やかに Patchright stealth + PulseAudio
  sink パスへ切替。`bot_server/spike/spike_pulseaudio.py` を Phase 0b として追加で書く。

## 既知の制約

- `ScriptProcessorNode` は deprecated。spike では簡便さを優先。本実装では
  AudioWorklet に置換予定。
- サンプルレートはブラウザ依存(大抵 48000Hz)。Python 側で resample する前提。
- `--use-fake-ui-for-media-stream` は意図的に**渡していない**。bot は consume 側で
  mic/cam を grant しないため不要、かつ余計な指紋を残す。
