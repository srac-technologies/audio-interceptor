# 使用方法ガイド

## クイックスタート

### 1. インターセプターを起動

```bash
cd ~/workspace/audio-interceptor
./audio_interceptor.py
```

起動すると以下が表示されます：
```
✅ Created virtual speaker: virtual_speaker_interceptor (module 536870913)
✅ Created loopback to real speaker (module 536870914)
```

### 2. 会議アプリの設定

会議アプリ（Zoom、Discord、Google Meet等）で：

**スピーカー/出力デバイス:**
- `Virtual_Speaker_Interceptor` を選択

**マイク/入力デバイス:**
- デフォルトのマイクのまま（通常通り）

### 3. 会議を開始

通常通り会議を開始します。音声は自動的に録音されます：
- `speaker_YYYYMMDD_HHMMSS_N.wav` - 相手の声
- `mic_YYYYMMDD_HHMMSS_N.wav` - 自分の声

### 4. 停止

`Ctrl+C` で停止します。自動的にクリーンアップされます。

## 録音ファイルの場所

デフォルト: `./tmp/`

カスタムディレクトリを指定：
```bash
./audio_interceptor.py /path/to/recordings
```

## ファイル形式

- **形式:** WAV (PCM)
- **サンプルレート:** 48kHz
- **チャンネル:** ステレオ (2ch)
- **ビット深度:** 16-bit
- **チャンク長:** 10秒

## トラブルシューティング

### 仮想デバイスが見つからない

1. PulseAudioが動作しているか確認：
```bash
pactl info
```

2. 既存の仮想デバイスをクリーンアップ：
```bash
pactl list short modules | grep null
pactl unload-module <module-id>
```

### 音が聞こえない

インターセプターは自動的に仮想スピーカーから実際のスピーカーにループバックします。
もし音が聞こえない場合：

```bash
pactl list short modules | grep loopback
```

手動でループバックを作成：
```bash
pactl load-module module-loopback source=virtual_speaker_interceptor.monitor
```

### マイクが録音されない

デフォルトのマイクを確認：
```bash
pactl get-default-source
```

特定のマイクを録音したい場合は、スクリプト内の `default_source` を変更してください。

### 録音ファイルが空

- 会議アプリの音声設定を確認
- `parec` コマンドが動作するか確認：
```bash
parec --device virtual_speaker_interceptor.monitor --raw | head -c 10000 > test.raw
```

## 高度な使用法

### カスタムフックの追加

`record_audio_stream` メソッドを編集して、以下を追加できます：

- リアルタイム音声認識
- 自動文字起こし（Whisper等）
- クラウドアップロード
- 音声フィルタリング

例：
```python
def record_audio_stream(self, source, label):
    # ... 既存のコード ...
    
    if audio_data:
        # カスタムフック
        self.process_audio(audio_data, label)
        
        # WAVに保存
        self.write_wav(filename, audio_data)

def process_audio(self, audio_data, label):
    """カスタム処理"""
    # ここに独自の処理を追加
    pass
```

### サンプルレート・チャンク長の変更

スクリプトの上部で定数を変更：

```python
SAMPLE_RATE = 48000  # 16000, 44100, 48000 など
CHUNK_SECONDS = 10   # 5, 10, 30 など
```

## 他のアプリでの使用例

### Discord
1. ユーザー設定 → 音声・ビデオ
2. 出力デバイス: `Virtual_Speaker_Interceptor`
3. 入力デバイス: デフォルトのまま

### Zoom
1. 設定 → オーディオ
2. スピーカー: `Virtual_Speaker_Interceptor`
3. マイク: デフォルトのまま

### Google Meet
1. 設定（歯車アイコン）→ オーディオ
2. スピーカー: `Virtual_Speaker_Interceptor`
3. マイク: デフォルトのまま

## 注意事項

⚠️ **法的・倫理的な使用について**

- 録音する際は必ず参加者の同意を得てください
- 無断録音は法律で禁止されている場合があります
- プライバシーを尊重してください
- 録音ファイルの取り扱いには十分注意してください

## パフォーマンス

- CPU使用率: 低（1-2%）
- メモリ使用量: 約30-50MB
- ディスク使用量: 約1.7MB/秒（ステレオ、48kHz、16-bit）
  - 10秒チャンク: 約17MB
  - 1時間の会議: 約6.1GB
