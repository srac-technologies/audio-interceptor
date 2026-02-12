# リサーチ機能セットアップガイド

## 概要

音声インターセプターにリサーチ機能を追加しました。会話から固有名詞（人名、企業名、製品名、技術名など）を自動抽出し、リアルタイムでリサーチ結果を表示します。

### 主な機能

1. **NER（Named Entity Recognition）**: 会話からエンティティを抽出
2. **自動リサーチ**: 抽出したエンティティについてLLMでリサーチ
3. **結果表示**: 
   - UI上の「AIリサーチ」パネル（旧アドバイス欄を再利用）
   - Slackスレッド（オプション）

### アドバイス機能の削除

- 旧「AIアドバイス」機能は削除されました
- DBテーブル`advices`はリサーチ結果の保存に再利用されます

## セットアップ手順

### 1. 依存関係のインストール

```bash
cd ~/workspace/audio-interceptor/backend
pip install -r requirements.txt
```

新しく追加された依存関係:
- `aiohttp>=3.9.0` (Slack統合用)

### 2. 設定の追加

設定は「設定」画面から追加できます（または直接DBを編集）。

#### 必須設定

| キー | 説明 | デフォルト値 |
|------|------|--------------|
| `research_enabled` | リサーチ機能の有効/無効 | `false` |
| `ner_prompt` | NER用のプロンプト | デフォルトプロンプトが設定済み |

#### Slack統合（オプション）

| キー | 説明 | 例 |
|------|------|-----|
| `slack_webhook_url` | Slack Incoming Webhook URL | `https://hooks.slack.com/services/...` |
| `slack_channel` | 投稿先チャンネル（オプション） | `#meeting-research` |

### 3. リサーチ機能の有効化

#### 方法1: UI経由（推奨）

1. アプリを起動
2. 右上の「設定」ボタンをクリック
3. `research_enabled` を `true` に変更
4. 必要に応じて `ner_prompt` をカスタマイズ
5. 保存

#### 方法2: SQLiteを直接編集

```bash
cd ~/workspace/audio-interceptor/backend
sqlite3 meeting_assistant.db

-- リサーチ機能を有効化
UPDATE app_settings SET value = 'true' WHERE key = 'research_enabled';

-- NERプロンプトをカスタマイズ（オプション）
UPDATE app_settings SET value = 'あなたのプロンプト' WHERE key = 'ner_prompt';
```

### 4. Slack統合の設定（オプション）

#### 4.1 Incoming Webhookの作成

1. Slackワークスペースにログイン
2. [Incoming Webhooks](https://api.slack.com/messaging/webhooks) アプリを追加
3. Webhook URLをコピー

#### 4.2 設定の追加

UIまたはSQLiteで以下を設定:

```sql
UPDATE app_settings SET value = 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL' 
WHERE key = 'slack_webhook_url';

UPDATE app_settings SET value = '#your-channel' 
WHERE key = 'slack_channel';
```

## 使い方

### 基本的な流れ

1. **録音開始**: 「文字起こし」を有効にして録音開始
2. **自動抽出**: 5発言ごとにNERが実行され、エンティティを抽出
3. **リサーチ実行**: 抽出されたエンティティについてLLMがリサーチ
4. **結果表示**: 
   - UI右側の「AIリサーチ」パネルにリアルタイム表示
   - Slack設定済みの場合、スレッドにも投稿

### UIでの確認

- **リサーチパネル**: 画面右側に表示
- **エンティティ名**: 見出しに表示（例: `🔍 OpenAI`）
- **リサーチ結果**: 200字以内の簡潔な説明

### Slackでの確認

- **スレッド作成**: 録音開始時に自動作成
- **投稿形式**: エンティティごとに個別投稿
- **スレッド管理**: 1セッション = 1スレッド

## カスタマイズ

### NERプロンプトの変更

デフォルト:
```
会話から固有名詞（人名、企業名、製品名、技術名など）を抽出してください。

JSON形式で以下のように出力してください：
{"entities": ["entity1", "entity2", ...]}
```

カスタマイズ例:
```
会話から以下を抽出してください：
- 企業名
- 製品名
- 技術スタック（プログラミング言語、フレームワーク）

JSON形式: {"entities": [...]}
```

### リサーチ内容の変更

`backend/llm_pipeline.py` の `research_entity` メソッドを編集:

```python
research_prompt = f"""
以下のトピックについて、詳しく説明してください（300字以内）：

{entity}

# 制約
- 最新の情報に基づいて説明
- ビジネスユースケースを含める
- 簡潔に要点のみ
"""
```

### バッファサイズの調整

`backend/llm_pipeline.py` の `buffer_size` を変更:

```python
self.buffer_size = 5  # 5発言ごと → 好きな数値に変更
```

## トラブルシューティング

### リサーチが実行されない

1. **設定を確認**:
   ```bash
   sqlite3 backend/meeting_assistant.db
   SELECT * FROM app_settings WHERE key = 'research_enabled';
   ```
   `value` が `true` であることを確認

2. **OpenAI APIキーを確認**:
   ```bash
   echo $OPENAI_API_KEY
   ```

3. **ログを確認**:
   ```bash
   # バックエンドのログ
   cd ~/workspace/audio-interceptor/backend
   ./server.py
   ```

### Slackに投稿されない

1. **Webhook URLを確認**:
   ```sql
   SELECT * FROM app_settings WHERE key = 'slack_webhook_url';
   ```

2. **手動テスト**:
   ```bash
   curl -X POST \
     -H 'Content-Type: application/json' \
     -d '{"text":"テスト投稿"}' \
     YOUR_WEBHOOK_URL
   ```

3. **ログを確認**:
   バックエンドのログに `Slack thread created` または `Posted research result` が出力されているか確認

### UIに表示されない

1. **WebSocket接続を確認**: ブラウザのDevToolsでWebSocketエラーがないか確認
2. **ログを確認**: `broadcast_research` が呼ばれているか確認

## 技術詳細

### アーキテクチャ

```
音声インターセプト
  ↓
文字起こし (Whisper)
  ↓
バッファ蓄積 (5発言)
  ↓
NER実行 (GPT-4o-mini) ←── ner_prompt
  ↓
エンティティ抽出
  ↓
リサーチ実行 (GPT-4o-mini)
  ↓
結果配信:
  ├─ WebSocket → UI表示
  ├─ Slack → スレッド投稿
  └─ DB保存 (advices テーブル)
```

### データフロー

1. **llm_pipeline.py**:
   - `process_transcript()`: バッファ管理
   - `extract_and_research()`: NER + リサーチ
   - `extract_entities()`: エンティティ抽出
   - `research_entity()`: リサーチ実行

2. **server.py**:
   - `on_research_callback()`: 結果受信
   - `broadcast_research()`: UI配信
   - `slack_service.post_research_result()`: Slack投稿

3. **slack_service.py**:
   - `create_thread()`: セッション開始時
   - `post_research_result()`: リサーチ結果投稿

## 今後の拡張案

- [ ] Web検索統合（Brave Search API など）
- [ ] リサーチ結果のキャッシュ（重複抽出を防ぐ）
- [ ] エンティティの優先度付け
- [ ] リアルタイムフィードバック（ユーザーが興味あるエンティティを指定）
- [ ] リサーチ結果のエクスポート（PDF/Markdown）

## 関連ファイル

| ファイル | 説明 |
|---------|------|
| `backend/llm_pipeline.py` | NER + リサーチロジック |
| `backend/slack_service.py` | Slack統合 |
| `backend/server.py` | API + WebSocket配信 |
| `backend/database.py` | 設定 + DB管理 |
| `frontend/renderer/index.html` | UI表示 |

## ライセンス

元のプロジェクトのライセンスに準拠します。
