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

## 💡 重要: 録音中の設定変更

**リサーチ機能の設定は録音中でもリアルタイムで反映されます！**

録音を停止する必要はありません：
- リサーチON/OFF
- バッファサイズ変更
- 対象ソース変更（speaker/mic/both）
- 文字起こし精度向上のON/OFF
- リサーチ方式変更（llm/hybrid）

**仕組み:**
- 各文字起こしのたびに設定を再読み込み
- バッファサイズや対象変更時は自動的にバッファクリア
- リサーチ方式変更時はOrchestratorを再初期化

**ログ出力例:**
```
🔄 Buffer size changed: 2 → 3
   🗑️  Clearing buffer (1 items)
🔄 Research method changed: llm → hybrid
   ✅ Orchestrator re-initialized
```

---

## セットアップ手順

### 1. 依存関係のインストール

```bash
cd ~/workspace/audio-interceptor/backend
pip install -r requirements.txt
```

新しく追加された依存関係:
- `aiohttp>=3.9.0` (Slack統合用)
- `slack-sdk>=3.23.0` (Slack App統合)

### 1.5. 環境変数の設定（リサーチソース）

`.env`ファイルまたはシェルで設定：

```bash
# 必須
export OPENAI_API_KEY="sk-..."

# オプション（並列リサーチを使う場合）
export BRAVE_API_KEY="BSA..."           # Brave Search API
export LIMITLESS_API_KEY="..."          # Limitless API
```

**APIキーの取得方法:**
- **Brave Search**: https://brave.com/search/api/
- **Limitless**: https://limitless.ai/api

### 2. 設定の追加

設定は「設定」画面から追加できます（または直接DBを編集）。

#### 必須設定

| キー | 説明 | デフォルト値 |
|------|------|--------------|
| `research_enabled` | リサーチ機能の有効/無効 | `false` |
| `research_buffer_size` | バッファサイズ（発言数） | `2` |
| `research_target_sources` | 対象ソース（speaker/mic/both） | `speaker` |
| `research_transcription_refinement` | 文字起こし精度向上 | `false` |
| `ner_prompt` | NER用のプロンプト | デフォルトプロンプトが設定済み |

#### Slack統合（オプション）

| キー | 説明 | 例 |
|------|------|-----|
| `slack_bot_token` | Slack Bot Token | `xoxb-1234567890-...` |
| `slack_channel` | 投稿先チャンネルID or 名前 | `#meeting-research` または `C01234567` |

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

### 4. リサーチ方式の選択

設定画面で「リサーチ方式」を選択できます：

#### **LLMのみ**（デフォルト）
- OpenAI APIのみ使用
- 高速・シンプル
- APIキー: OpenAI のみ

#### **ハイブリッド**
- 全ソースを並列実行
- LLM + Brave + Limitless + gog
- 最も多くの情報を取得（遅延は最大2秒程度）
- 各ソースのAPIキーが必要

### 5. Slack統合の設定（オプション）

#### 4.1 Slack Appの作成

1. [Slack API](https://api.slack.com/apps) にアクセス
2. "Create New App" → "From scratch"
3. App名とワークスペースを選択
4. "OAuth & Permissions" に移動
5. "Bot Token Scopes" に以下を追加:
   - `chat:write` (メッセージ投稿)
   - `chat:write.public` (パブリックチャンネルへの投稿)
6. "Install to Workspace" でインストール
7. "Bot User OAuth Token" (`xoxb-...`) をコピー

#### 4.2 設定の追加

UIまたはSQLiteで以下を設定:

```sql
UPDATE app_settings SET value = 'xoxb-YOUR-BOT-TOKEN' 
WHERE key = 'slack_bot_token';

UPDATE app_settings SET value = '#your-channel' 
WHERE key = 'slack_channel';
```

**チャンネルIDの確認方法**:
- Slackでチャンネルを開く → 右上の "..." → "View channel details"
- 一番下にチャンネルIDが表示されます（例: `C01234567`）
- チャンネル名（`#meeting-research`）でも可

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

設定画面から変更可能：

```
設定 → リサーチ機能 →
  リサーチバッファサイズ: [2]  ← 1-20の範囲で設定
```

**推奨値:**
- `1`: 即座にリサーチ（ノイズが多い）
- `2-3`: バランス（デフォルト: 2）
- `5-10`: 文脈が多く必要な場合
- `10+`: 長い会話のまとめ

### 対象ソースの選択

設定画面から選択可能：

```
設定 → リサーチ機能 →
  リサーチ対象: [スピーカーのみ]  ← 選択
```

**オプション:**
- **スピーカーのみ**: 相手の発言のみリサーチ（デフォルト）
- **マイクのみ**: 自分の発言のみリサーチ
- **両方**: 全ての発言をリサーチ

**ユースケース:**
- 商談・インタビュー → スピーカーのみ
- 自分のプレゼン練習 → マイクのみ
- 会議全体の記録 → 両方

### 文字起こし精度向上

設定画面で有効化：

```
設定 → リサーチ機能 →
  ✅ 文字起こし精度向上（NER前にLLMで修正）
```

**動作:**
1. バッファが満タンになる
2. LLMで文字起こしを修正（誤変換、固有名詞など）
3. 精度向上後のテキストでNER実行

**効果:**
- 誤変換の修正（例: 「人工無能」→「人工知能」）
- 固有名詞の正確化（例: 「おーぷんえーあい」→「OpenAI」）
- 句読点の追加
- 自然な日本語への整形

**注意:**
- 処理時間 +1-2秒
- OpenAI APIの追加コスト

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

1. **Bot Tokenとチャンネルを確認**:
   ```sql
   SELECT * FROM app_settings WHERE key IN ('slack_bot_token', 'slack_channel');
   ```

2. **Bot権限を確認**:
   - Slack Appの "OAuth & Permissions" で `chat:write`, `chat:write.public` が追加されているか
   - Botがチャンネルに招待されているか（`/invite @your-bot`）

3. **手動テスト**:
   ```bash
   curl -X POST https://slack.com/api/chat.postMessage \
     -H 'Content-Type: application/json; charset=utf-8' \
     -H 'Authorization: Bearer YOUR_BOT_TOKEN' \
     -d '{"channel":"#your-channel","text":"テスト投稿"}'
   ```

4. **ログを確認**:
   バックエンドのログに `Slack thread created` または `Posted research result` が出力されているか確認

### UIに表示されない

1. **WebSocket接続を確認**: ブラウザのDevToolsでWebSocketエラーがないか確認
2. **ログを確認**: `broadcast_research` が呼ばれているか確認

## 技術詳細

### アーキテクチャ

#### リサーチ方式: LLMのみ（デフォルト）

```
音声インターセプト
  ↓
文字起こし (Whisper)
  ↓
バッファ蓄積 (2発言・スピーカーのみ)
  ↓
NER実行 (GPT-4o-mini) ←── ner_prompt
  ↓
エンティティ抽出
  ↓
キャッシュチェック（重複スキップ）
  ↓
リサーチ実行 (GPT-4o-mini)
  ↓
結果配信:
  ├─ WebSocket → UI表示
  ├─ Slack → スレッド投稿
  └─ DB保存 (advices テーブル)
```

#### リサーチ方式: ハイブリッド（並列実行）

```
音声インターセプト → 文字起こし → NER抽出
  ↓
エンティティ: "OpenAI"
  ↓
┌─────────────────────────────────────────────┐
│   Research Orchestrator                     │
│   - 複数ソースを並列実行                      │
│   - 結果が届いた順に配信（ストリーミング）      │
│   - 優先度・タイムアウト制御                   │
└─────────────────────────────────────────────┘
    ↓ (asyncio.gather - 並列実行)
┌──────┬──────┬──────────┬──────┐
│ LLM  │Brave │Limitless │ gog  │
│即答  │Search│   API    │ CLI  │
│ 50ms │500ms │   1s     │  2s  │
└──────┴──────┴──────────┴──────┘
    ↓ (結果が届いた順に配信)
┌─────────────────────────────────────────────┐
│   Progressive Result Delivery               │
│   t=0.05s: LLM即答 → 即表示                  │
│   t=0.5s:  Brave検索結果 → 追加              │
│   t=1.0s:  Limitless文脈 → 追加              │
│   t=2.0s:  gog CLI結果 → 追加                │
└─────────────────────────────────────────────┘
    ↓
UI: リアルタイム更新（カード追加）
Slack: スレッド内に順次投稿
DB: 各ソースの結果を保存
```

### リサーチソース

| ソース | 優先度 | タイムアウト | 内容 | 必要なもの |
|--------|--------|-------------|------|-----------|
| **LLM** | 1 | 5s | GPT-4o-miniの知識 | OpenAI API Key |
| **Brave Search** | 2 | 3s | 最新のWeb検索結果 | Brave API Key |
| **Limitless API** | 4 | 5s | 文脈・履歴情報 | Limitless API Key |
| **gog CLI** | 5 | 10s | CLI検索結果 | gog インストール |

**優先度の仕組み**:
- 数値が小さいほど優先度が高い
- 並列実行されるが、結果は届いた順に配信
- 高速なソース（LLM）は即座に表示、遅いソース（gog）は後から追加

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
