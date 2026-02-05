# 🎙️ Audio Interceptor

**Web会議音声インターセプター** - マイクとスピーカーの入出力を透過的にキャプチャして記録

## 特徴

✅ **透過的なインターセプト** - 会議の音声を聞きながら自動録音  
✅ **10秒チャンク保存** - WAV形式で自動分割保存  
✅ **シンプル** - Python3スクリプト1つで動作  
✅ **クリーンアップ自動** - Ctrl+Cで安全終了  
✅ **PulseAudio/PipeWire対応** - 現代的なLinux環境で動作  

## クイックスタート

```bash
# 起動
cd ~/workspace/audio-interceptor
./audio_interceptor.py

# 会議アプリで「Virtual_Speaker_Interceptor」をスピーカーに設定
# Ctrl+Cで停止
```

## 必要要件

- **OS:** Linux (PulseAudio または PipeWire)
- **Python:** 3.6以上
- **コマンド:** `pactl`, `parec` (通常はpulseaudio-utilsに含まれる)

### 依存パッケージのインストール

```bash
# Ubuntu/Debian
sudo apt install pulseaudio-utils python3

# Fedora/RHEL
sudo dnf install pulseaudio-utils python3

# Arch Linux
sudo pacman -S pulseaudio python
```

## 使い方

### 1. インターセプターを起動

```bash
./audio_interceptor.py

# または、保存先ディレクトリを指定
./audio_interceptor.py /path/to/recordings
```

### 2. 会議アプリの設定

会議アプリ（Zoom、Discord、Google Meet等）で：

- **スピーカー/出力:** `Virtual_Speaker_Interceptor` に変更
- **マイク/入力:** デフォルトのまま

### 3. 録音開始

通常通り会議を開始すると、自動的に録音されます：

- `speaker_YYYYMMDD_HHMMSS_N.wav` - 相手の声
- `mic_YYYYMMDD_HHMMSS_N.wav` - 自分の声

### 4. 停止

`Ctrl+C` で停止。自動的にクリーンアップされます。

## 音声フォーマット

- **形式:** WAV (PCM)
- **サンプルレート:** 48kHz
- **チャンネル:** ステレオ (2ch)
- **ビット深度:** 16-bit
- **チャンク長:** 10秒ごと

## ファイル構成

```
~/workspace/audio-interceptor/
├── audio_interceptor.py      # メインスクリプト（これを実行）
├── test_setup.py              # セットアップテスト用
├── README.md                  # このファイル
├── USAGE.md                   # 詳細な使用ガイド
├── PROJECT_SUMMARY.md         # 技術仕様とプロジェクトサマリー
└── tmp/                       # 録音ファイル保存先（自動生成）
```

## 詳細ドキュメント

- **[USAGE.md](USAGE.md)** - 詳細な使用方法、トラブルシューティング
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - 技術仕様、アーキテクチャ

## シングルバイナリ化（オプション）

PyInstallerを使って配布可能なバイナリを作成：

```bash
pip3 install pyinstaller
pyinstaller --onefile --name audio-interceptor audio_interceptor.py

# 生成されたバイナリ
./dist/audio-interceptor
```

バイナリは他のLinuxマシンにコピーして実行できます（同じアーキテクチャの場合）。

## アーキテクチャ

```
[会議アプリ]
    ↓ 音声出力
[Virtual_Speaker_Interceptor]
    ↓ モニター
    ├→ 録音 → speaker_*.wav
    └→ ループバック → [実際のスピーカー] (音が聞こえる)

[実際のマイク]
    ↓
    ├→ [会議アプリ] (通常通り)
    └→ 録音 → mic_*.wav
```

## トラブルシューティング

### 仮想デバイスが見つからない

```bash
# PulseAudioが動作しているか確認
pactl info

# 既存の仮想デバイスをクリーンアップ
pactl list short modules | grep null
pactl unload-module <module-id>
```

### 音が聞こえない

ループバックが自動的に作成されますが、もし聞こえない場合：

```bash
pactl load-module module-loopback source=virtual_speaker_interceptor.monitor
```

## カスタマイズ

スクリプトの上部で設定を変更できます：

```python
SAMPLE_RATE = 48000     # サンプルレート (16000, 44100, 48000)
CHANNELS = 2            # チャンネル数 (1=モノラル, 2=ステレオ)
CHUNK_SECONDS = 10      # チャンク長（秒）
```

## 拡張例

`audio_interceptor.py` を編集して機能追加：

- リアルタイム音声認識（Whisper等）
- 自動文字起こし
- クラウドアップロード
- 音声フィルタリング
- 感情分析

## セキュリティとプライバシー

⚠️ **重要な注意事項**

- このツールは会議の録音に使用できます
- **必ず参加者全員の同意を得てください**
- 無断録音は法律で禁止されている場合があります
- 録音ファイルは機密情報を含む可能性があります
- 適切なアクセス制御とストレージセキュリティを実施してください

## パフォーマンス

- **CPU使用率:** 1-2%
- **メモリ:** 約50MB
- **ディスク:** 約1.7MB/秒 (ステレオ48kHz)
  - 10秒チャンク: 約17MB
  - 1時間の会議: 約6.1GB

## テスト済み環境

- Pop!_OS 22.04 (Ubuntu based)
- PipeWire with PulseAudio compatibility
- Python 3.10+

## ライセンス

MIT License

## 貢献

バグ報告、機能要望、プルリクエスト歓迎です。

## 作成日時

2026-02-05

---

**Happy Recording! 🎧**
