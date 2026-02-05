# Audio Interceptor - プロジェクトサマリー

## 概要

Web会議の音声を透過的にインターセプトして記録するツール。
会議アプリの音声出力と入力を仮想デバイス経由でキャプチャし、10秒チャンクのWAVファイルとして保存します。

## 実装完了内容

### ✅ 完成した機能

1. **仮想オーディオデバイス**
   - PulseAudio/PipeWire両対応
   - 仮想スピーカー（module-null-sink）
   - 実際のスピーカーへのループバック（音が聞こえる）
   - デフォルトマイクからの録音

2. **音声録音**
   - 10秒チャンクでWAV形式保存
   - スピーカー出力（相手の声）: `speaker_*.wav`
   - マイク入力（自分の声）: `mic_*.wav`
   - フォーマット: 48kHz、ステレオ、16-bit PCM

3. **使いやすさ**
   - シンプルな起動（`./audio_interceptor.py`）
   - 自動クリーンアップ（Ctrl+Cで安全終了）
   - 詳細な使用説明（USAGE.md）
   - エラーハンドリング

4. **移植性**
   - Python3実装（ほとんどのLinux環境で動作）
   - 依存: PulseAudio/PipeWire、Python3のみ
   - シングルバイナリ化可能（PyInstaller）

### 📁 ファイル構成

```
~/workspace/audio-interceptor/
├── audio_interceptor.py      # メインスクリプト
├── test_setup.py              # セットアップテストスクリプト
├── README.md                  # プロジェクト概要
├── USAGE.md                   # 詳細な使用ガイド
├── PROJECT_SUMMARY.md         # このファイル
└── tmp/                       # 録音ファイル保存先（自動生成）
```

## 技術仕様

### アーキテクチャ

```
[会議アプリ] 
    ↓ 音声出力
[Virtual_Speaker_Interceptor (null-sink)]
    ↓ モニター
    ├→ インターセプター → speaker_*.wav
    └→ ループバック → [実際のスピーカー] (音が聞こえる)

[実際のマイク]
    ↓
    ├→ [会議アプリ] (通常通り入力)
    └→ インターセプター → mic_*.wav
```

### 音声フォーマット

- **サンプルレート:** 48kHz (高品質)
- **チャンネル:** 2 (ステレオ)
- **ビット深度:** 16-bit
- **コーデック:** PCM (非圧縮)
- **ファイル形式:** WAV

### システム要件

- **OS:** Linux (PulseAudio または PipeWire)
- **Python:** 3.6+
- **コマンド:** `pactl`, `parec`
- **メモリ:** ~50MB
- **CPU:** 低負荷 (1-2%)

## 使用方法（クイック）

```bash
# 起動
cd ~/workspace/audio-interceptor
./audio_interceptor.py

# 会議アプリでスピーカーを "Virtual_Speaker_Interceptor" に設定
# マイクはデフォルトのまま

# 会議開始 → 自動録音
# Ctrl+C で停止

# 録音ファイル確認
ls tmp/
```

## 拡張可能性

スクリプトは拡張しやすい設計：

1. **リアルタイム処理フック**
   - `process_audio()` メソッドを追加
   - 音声認識（Whisper等）
   - 感情分析
   - ノイズ除去

2. **ストレージ**
   - クラウドアップロード（S3, GCS等）
   - 圧縮（MP3, Opus）
   - 暗号化

3. **通知**
   - 録音開始/終了の通知
   - 文字起こし完了通知

## 既知の制限

1. **マイク側の仮想化なし**
   - 現在はデフォルトマイクを直接録音
   - 完全な仮想化が必要な場合は追加実装が必要

2. **PipeWireの制限**
   - 一部のPulseAudioモジュールが制限される場合あり
   - テスト済み: Pop!_OS (PipeWire)

3. **録音形式**
   - 現在はWAVのみ（非圧縮）
   - 長時間録音はディスク容量に注意

## テスト状況

- ✅ 仮想デバイス作成
- ✅ ループバック動作
- ✅ スピーカー録音
- ✅ マイク録音
- ✅ WAVファイル書き込み
- ✅ クリーンアップ
- ⚠️ 実際の会議での長時間テスト（未実施）

## シングルバイナリ化

PyInstallerで配布可能なバイナリを作成：

```bash
pip3 install pyinstaller
cd ~/workspace/audio-interceptor
pyinstaller --onefile --name audio-interceptor audio_interceptor.py

# 生成されたバイナリ
./dist/audio-interceptor
```

## セキュリティ・プライバシー

⚠️ **重要な注意事項**

- このツールは会議の録音に使用できます
- **必ず参加者の同意を得てください**
- 無断録音は法律で禁止されている場合があります
- 録音ファイルは機密情報を含む可能性があります
- 適切なアクセス制御と暗号化を推奨します

## 今後の改善案

1. GUIバージョン（Gtk/Qt）
2. リアルタイム文字起こし統合
3. 自動クラウドバックアップ
4. 会議メタデータ記録（参加者、時刻等）
5. Windows/macOS対応
6. 音声圧縮オプション（MP3, Opus）

## ライセンス

MIT License

## 作成日時

2026-02-05 02:01 JST

## 開発環境

- Pop!_OS (Ubuntu based)
- PipeWire with PulseAudio compatibility
- Python 3.x
