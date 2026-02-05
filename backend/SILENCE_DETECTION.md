# 無音検知とハルシネーション対策

## 問題

Whisper APIは無音または極端に小さい音声を文字起こしする際、以下のような定型文を返すことがあります（ハルシネーション）：

- 「ご視聴ありがとうございました」
- 「チャンネル登録お願いします」
- "Thanks for watching"
- "Subscribe"

## 実装した対策

### 1. 無音検知

音声ファイルのRMS（二乗平均平方根）を計算し、閾値以下の場合は文字起こしをスキップします。

```python
def is_silent(self, filename, threshold=500):
    # RMSを計算
    rms = (sum_squares / len(samples)) ** 0.5
    return rms < threshold
```

**閾値（threshold）:**
- デフォルト: 500
- 低すぎる → 実際の音声もスキップされる
- 高すぎる → 小さい音声が無音扱いされる

### 2. プロンプト追加

Whisper APIに以下のプロンプトを渡して精度を向上：

```
会議の音声です。無音の場合は空文字を返してください。
```

### 3. 定型文フィルタリング

返ってきたテキストが以下の条件を満たす場合、ハルシネーションとみなしてスキップ：

- 50文字以下
- 既知の定型文を含む

```python
hallucination_phrases = [
    'ご視聴ありがとうございました',
    'ご視聴ありがとうございます',
    'チャンネル登録',
    '高評価',
    'ご清聴ありがとうございました',
    'Thanks for watching',
    'Subscribe',
    'Like and subscribe'
]
```

## ログ出力

### 無音検知時

```
🔇 Skipping silent audio: speaker_20260205_160000_0.wav
```

### ハルシネーション検知時

```
🚫 Filtered hallucination: ご視聴ありがとうございました
```

## 調整方法

閾値を変更したい場合は、`audio_interceptor.py` の `is_silent` メソッドを編集：

```python
def is_silent(self, filename, threshold=500):  # ← この値を変更
```

- **より敏感にする（小さい音も検知）**: 閾値を下げる（例: 300）
- **より鈍感にする（大きい音のみ検知）**: 閾値を上げる（例: 1000）

## テスト

無音検知が正しく動作しているか確認：

1. 会議を開始（文字起こし有効）
2. 10秒間完全に無音にする
3. バックエンドログに `🔇 Skipping silent audio` と表示されることを確認

## 既知の制限

- RMSベースの検知は簡易的なもの
- 背景ノイズが大きい場合、無音と判定されない可能性あり
- より高度な検知にはVAD（Voice Activity Detection）アルゴリズムが必要
