# 文字起こし機能の使い方

## 事前準備

### 1. OpenAI APIキーを取得

https://platform.openai.com/api-keys からAPIキーを作成。

### 2. 環境変数を設定

**一時的に設定（現在のセッションのみ）:**
```bash
export OPENAI_API_KEY="sk-proj-..."
```

**永続的に設定（推奨）:**
```bash
# bashの場合
echo 'export OPENAI_API_KEY="sk-proj-..."' >> ~/.bashrc
source ~/.bashrc

# zshの場合
echo 'export OPENAI_API_KEY="sk-proj-..."' >> ~/.zshrc
source ~/.zshrc
```

### 3. バックエンドを再起動

環境変数が反映されるように、バックエンドを再起動：
```bash
cd ~/workspace/audio-interceptor/backend
# 既存のプロセスを停止（Ctrl+C）
./start_server.sh
```

## 使い方

### ステップ1: Electronを起動

```bash
cd ~/workspace/audio-interceptor/frontend
export PATH="/home/tan_t/.nix-profile/bin:$PATH"
npm start
```

### ステップ2: 文字起こしを有効化

UIで「**文字起こしを有効にする（Whisper API）**」にチェックを入れる。

### ステップ3: 会議を開始

「会議を開始」ボタンをクリック。

### ステップ4: 確認

- ステータスバッジが「録音中 (Active)」になる
- バックエンドのログに以下が表示される：
  ```
  🎙️  Recording started
  📝 Transcription: ENABLED (Whisper API)
  ```

### ステップ5: 文字起こし結果の確認

現在の実装では、文字起こし結果は**バックエンドのログ**に出力されます：

```
[Speaker 🔊] こんにちは、本日はよろしくお願いします。
[Mic 🎤] よろしくお願いします。
```

将来的には、Electronの画面にリアルタイムで表示される予定です。

## 動作の仕組み

1. 音声が10秒ごとにチャンクとして保存される
2. 各チャンクがOpenAI Whisper APIに送信される
3. APIから返ってきたテキストがログに出力される
4. WAVファイルも `tmp/` ディレクトリに保存される

## コスト

Whisper APIの料金（2026年2月時点）:
- $0.006 / 分

例: 1時間の会議 = 60分 × $0.006 = **$0.36**

## トラブルシューティング

### エラー: "Transcription failed: HTTP 401"

**原因:** APIキーが無効、または設定されていない

**解決策:**
1. APIキーが正しいか確認
2. 環境変数を再設定
3. バックエンドを再起動

### 文字起こしが日本語にならない

**原因:** 言語の自動検出が失敗している

**解決策:** コードは既に `language: "ja"` を指定しているので、通常は問題ないはずです。

### 文字起こしが遅い

**原因:** 10秒チャンクごとにAPIを呼んでいるため、若干の遅延があります

**対策:** 
- チャンク時間を短くする（`CHUNK_SECONDS` を変更）
- ただし、短すぎるとAPI呼び出し回数が増えてコストが上がります

## 次の実装予定

- [ ] リアルタイム文字起こしのUI表示（WebSocket経由）
- [ ] 文字起こし結果のファイル保存
- [ ] 会議サマリー自動生成
- [ ] 話者認識（誰が喋ったか）
