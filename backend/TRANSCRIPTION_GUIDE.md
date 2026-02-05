# Transcription Service ガイド

## 概要

音声文字起こしサービス。APIモード（OpenAI Whisper API）とローカルモード（faster-whisper）の両方に対応。

## セットアップ

### 1. 依存関係インストール

```bash
cd backend
pip install -r requirements.txt
```

初回実行時、ローカルモードでは自動的にWhisperモデルがダウンロードされます（`~/.cache/whisper/`）。

### 2. 設定（.env）

```bash
# ローカルWhisper（推奨）
WHISPER_MODE=local
WHISPER_MODEL=small
WHISPER_LANGUAGE=ja

# OpenAI API（課金あり、高速）
WHISPER_MODE=api
WHISPER_MODEL=whisper-1
WHISPER_LANGUAGE=ja
OPENAI_API_KEY=sk-xxxx
```

## モデル選択

### ローカルモード

| モデル | サイズ | RAM | 処理速度* | 精度 | 推奨用途 |
|--------|--------|-----|----------|------|----------|
| tiny | 39MB | ~1GB | 5秒/分 | 低 | テスト・英語のみ |
| base | 74MB | ~1GB | 10秒/分 | 中 | 軽量 |
| **small** | 244MB | ~2GB | **30秒/分** | **高** | **推奨（バランス）** |
| medium | 1.5GB | ~5GB | 60秒/分 | 最高 | 高精度 |
| large-v3 | 2.9GB | ~10GB | 120秒/分 | 最高 | GPU推奨 |

*Intel Core i5-1335U（CPU）での目安

### APIモード

- モデル: `whisper-1`（固定）
- 処理速度: 数秒（ネットワーク依存）
- 課金: $0.006/分

## 使用方法

### Python スクリプトから

```python
from transcription import get_transcription_service
import asyncio

async def main():
    service = get_transcription_service()
    result = await service.transcribe("audio.wav")
    
    print(f"Text: {result['text']}")
    print(f"Language: {result['language']}")
    print(f"Duration: {result['duration']}s")
    
    # ローカルモードのみ：セグメント情報
    if result['segments']:
        for seg in result['segments']:
            print(f"[{seg['start']:.1f}s] {seg['text']}")

asyncio.run(main())
```

### CLI テスト

```bash
cd backend
python transcription.py ../tmp/audio_chunk_001.wav
```

## パフォーマンス最適化

### チャンクサイズ調整

```python
# audio_interceptor.py でチャンクサイズを変更
CHUNK_DURATION = 5  # 秒（5秒推奨：リアルタイム性UP）
```

### CPU最適化

`transcription.py` はすでにCPU最適化されています：
- **compute_type="int8"**: 量子化で高速化
- **vad_filter=True**: 無音区間スキップ

### GPU利用（オプション）

CUDAが利用可能な環境では：

```python
# transcription.py の _init_local_whisper() を変更
device = "cuda"
compute_type = "float16"  # GPU用
```

## トラブルシューティング

### モデルダウンロード失敗

```bash
# 手動ダウンロード
pip install huggingface_hub
python -c "from faster_whisper import download_model; download_model('small')"
```

### メモリ不足

- より小さいモデルを使用: `WHISPER_MODEL=base`
- チャンクサイズを短縮: `CHUNK_DURATION=5`

### 精度が低い

- より大きいモデル: `WHISPER_MODEL=medium`
- 言語明示: `WHISPER_LANGUAGE=ja`（autoは避ける）
- チャンクを長く: `CHUNK_DURATION=10`

## 配布時の考慮事項

### ローカルモード（推奨）

✅ メリット:
- オフライン動作
- プライバシー保護
- ランニングコスト無し

⚠️ デメリット:
- 初回起動時モデルダウンロード（244MB）
- CPU負荷

### APIモード

✅ メリット:
- 高速処理
- セットアップ不要

⚠️ デメリット:
- APIキー必要
- 課金（$0.006/分）
- ネットワーク必須

### ハイブリッド配布

```bash
# デフォルトはローカル、オプションでAPI
WHISPER_MODE=local
OPENAI_API_KEY=  # 空欄でもOK
```

ユーザーが後からAPIキーを設定すれば切り替え可能。
