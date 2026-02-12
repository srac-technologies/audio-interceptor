# OpenClaw統合ガイド

audio-interceptorとOpenClawをinbox方式で統合し、リサーチ機能を強化します。

## 🎯 統合の概要

```
audio-interceptor (NER抽出)
    ↓
エンティティ: "OpenAI"
    ↓
inbox/task_research_xxx.json に書き込み
    ↓
OpenClaw (heartbeat)
    ├─ web_search: 最新情報取得
    ├─ memory_search: ナレッジベース検索
    └─ 結果を200字で要約
    ↓
inbox/result_research_xxx.json に書き込み
    ↓
audio-interceptor
    ├─ UI: リサーチパネルに表示
    ├─ Slack: スレッドに投稿
    └─ DB: advicesテーブルに保存
```

## 🔧 セットアップ

### 1. audio-interceptor側の設定

設定画面（右上の「設定」ボタン）で以下を設定：

```
[一般設定] タブ:

🔍 リサーチ機能
  ✅ リサーチ機能を有効化
  
  リサーチ方式: [OpenClaw統合] ← 選択
  
  OpenClaw統合（オプション）
    OpenClaw Workspace Path: ~/clawd/workspaces/experimentation
```

### 2. OpenClaw側の設定

#### HEARTBEAT.mdが自動処理

OpenClawの `HEARTBEAT.md` は既に更新済みです。heartbeatのたびに自動的に：

1. `inbox/task_*.json` をチェック
2. `action: "research"` のタスクを検出
3. `web_search` と `memory_search` を実行
4. 結果を `inbox/result_*.json` に書き込み

**追加作業は不要です！**

## 🚀 使い方

### 録音を開始

1. audio-interceptorを起動
2. 「文字起こし」を有効にして録音開始
3. スピーカー（相手）が固有名詞を話す

### 自動リサーチフロー

```
[相手] OpenAIのGPT-4について
[相手] Claudeも使ってます
    ↓ (2発言でNER実行)
🔍 NER抽出: OpenAI, GPT-4, Claude
    ↓
📚 並列リサーチ開始:
  ├─ [LLM] 即答（50ms） → UI表示
  └─ [OpenClawInbox] タスク作成
         ↓ (OpenClawが処理)
       web_search + memory_search
         ↓ (1-2秒後)
      結果受信 → UI追加表示
```

## 📊 ログ出力

### audio-interceptor側

```
🚀 並列リサーチ開始: OpenAI
📊 ソース数: 2
   - LLM (priority=1, timeout=5.0s)
   - OpenClawInbox (priority=3, timeout=10.0s)
------------------------------------------------------------
🤖 [LLM] リサーチ開始: OpenAI
📥 [OpenClawInbox] リサーチ開始: OpenAI
   📝 タスク作成: task_research_1707793200000.json
✅ [LLM] 完了: OpenAI (t=0.12s)
   OpenAIは2015年に設立された...
✅ [OpenClawInbox] 結果受信 (t=1.85s)
   [Web] OpenAIの最新情報 + [Knowledge] 関連知識
------------------------------------------------------------
🏁 リサーチ完了: OpenAI
📊 結果数: 2/2
⏱️  総時間: 1.85s
```

### OpenClaw側（heartbeat時）

```
📥 Heartbeat: Checking inbox
📂 Found task: task_research_1707793200000.json
🔍 Research task: OpenAI
   Instructions: OpenAIについて調べてください...

🌐 Executing web_search...
📚 Executing memory_search...
✅ Results combined

📝 Writing result to: result_research_1707793200000.json
✅ Task complete
```

## 🎛️ リサーチ方式の比較

| 方式 | ソース | 速度 | 情報量 | 用途 |
|------|--------|------|--------|------|
| **LLMのみ** | GPT-4o-mini | 50ms | ⭐ | 高速・簡易 |
| **OpenClaw統合** | LLM + OpenClaw | 1-2s | ⭐⭐⭐ | ナレッジ活用 |
| **ハイブリッド** | LLM + OpenClaw + Brave + ... | 1-2s | ⭐⭐⭐⭐ | 最大限の情報 |

### OpenClaw統合の利点

- ✅ **ナレッジベース検索**: MEMORY.md, memory/*.md から関連情報
- ✅ **Web検索**: Brave Search APIで最新情報（設定済みの場合）
- ✅ **柔軟性**: OpenClawの全ツールが使える
- ✅ **段階的配信**: LLM即答 → OpenClaw結果（待たされない）

## 🔍 タスクフォーマット

### タスクファイル（audio-interceptor → OpenClaw）

`inbox/task_research_xxx.json`:

```json
{
  "task_id": "research_1707793200000",
  "action": "research",
  "entity": "OpenAI",
  "instructions": "OpenAIについて、以下を調べてください：\n1. Web検索で最新情報を取得\n2. ナレッジファイル（MEMORY.md等）から関連情報を検索\n3. 結果を200字以内で要約",
  "created_at": "2026-02-13T08:30:00Z"
}
```

### 結果ファイル（OpenClaw → audio-interceptor）

`inbox/result_research_xxx.json`:

```json
{
  "task_id": "research_1707793200000",
  "content": "OpenAIは2015年に設立されたAI研究所で、ChatGPTやGPTシリーズを開発。最新のGPT-4は...",
  "metadata": {
    "sources": ["web_search", "memory_search"],
    "timestamp": "2026-02-13T08:30:02Z",
    "search_results": 3,
    "knowledge_hits": 2
  }
}
```

## 🛠️ トラブルシューティング

### OpenClawからの結果が来ない

1. **OpenClawが起動しているか確認**:
   ```bash
   ps aux | grep openclaw
   ```

2. **inboxディレクトリを確認**:
   ```bash
   ls -la ~/clawd/workspaces/experimentation/inbox/
   ```
   
   - `task_*.json` が残っている → OpenClawが処理していない
   - `result_*.json` がない → 処理中または失敗

3. **手動でタスクをテスト**:
   ```bash
   cd ~/clawd/workspaces/experimentation
   # OpenClawセッションで
   openclaw chat
   > Check inbox for research tasks
   ```

4. **HEARTBEAT.mdを確認**:
   ```bash
   cat ~/clawd/workspaces/experimentation/HEARTBEAT.md
   ```
   Research Tasksのセクションがあるか確認

### タイムアウトが発生する

デフォルトタイムアウト: 10秒

OpenClawの処理が遅い場合、`research_orchestrator.py` で調整：

```python
super().__init__(name="OpenClawInbox", priority=3, timeout=15.0)  # 15秒に延長
```

### 結果が重複する

- audio-interceptorは同じエンティティを1セッション内で1回のみリサーチ
- キャッシュが正しく動作しているかログで確認：
  ```
  💾 キャッシュ済み（スキップ）: OpenAI
  ```

## 🎨 カスタマイズ

### タスクのinstructions変更

`research_orchestrator.py` の `OpenClawInboxSource.search()`:

```python
task = {
    "task_id": task_id,
    "action": "research",
    "entity": entity,
    "instructions": f"""
{entity}について以下を実行してください：
1. web_searchで最新情報（3件）
2. memory_searchでナレッジベース検索
3. 技術的な詳細を含めて300字で要約
4. 参考URLを含める
""",
    "created_at": datetime.now().isoformat()
}
```

### OpenClaw側のカスタム処理

`HEARTBEAT.md` を編集してロジックを変更：

```markdown
### 2. Research Tasks (audio-interceptor)

**Processing:**
1. web_searchで情報収集（5件まで）
2. memory_searchで関連知識
3. 企業情報ならLinkedIn検索も追加
4. 技術トピックならGitHub検索
5. 結果を統合して300字で要約
```

## 📈 今後の拡張

- [ ] Brave Search API直接統合（OpenClaw経由でなく）
- [ ] Limitless API統合
- [ ] 結果のキャッシュ永続化（複数セッション間で共有）
- [ ] リサーチ優先度のユーザー指定
- [ ] リアルタイムストリーミング（結果を段階的に配信）

## 🔗 関連ファイル

| ファイル | 説明 |
|---------|------|
| `backend/research_orchestrator.py` | OpenClawInboxSourceの実装 |
| `backend/llm_pipeline.py` | Research Orchestratorの初期化 |
| `~/clawd/workspaces/experimentation/HEARTBEAT.md` | OpenClaw側のタスク処理ロジック |
| `~/clawd/workspaces/experimentation/inbox/` | タスク・結果ファイルの格納場所 |

## 📝 ライセンス

元のプロジェクトのライセンスに準拠します。
