"""
Research Orchestrator
複数のリサーチソースを並列実行し、結果を段階的に配信
"""

import asyncio
import logging
import time
from typing import Optional, Dict, List, Callable
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger("ResearchOrchestrator")

class ResearchSource:
    """リサーチソースの基底クラス"""
    
    def __init__(self, name: str, priority: int = 5, timeout: float = 5.0):
        """
        Args:
            name: ソース名
            priority: 優先度（1=最高、10=最低）数値が小さいほど優先
            timeout: タイムアウト（秒）
        """
        self.name = name
        self.priority = priority
        self.timeout = timeout
    
    async def search(self, entity: str) -> Optional[Dict]:
        """
        エンティティをリサーチ
        
        Args:
            entity: リサーチ対象
            
        Returns:
            {"source": str, "content": str, "metadata": dict}
        """
        raise NotImplementedError


class LLMSource(ResearchSource):
    """LLMによる即答リサーチ（OpenAI直接）"""
    
    def __init__(self, client):
        super().__init__(name="LLM", priority=1, timeout=5.0)
        self.client = client
    
    async def search(self, entity: str) -> Optional[Dict]:
        if not self.client:
            return None
        
        logger.info(f"🤖 [{self.name}] リサーチ開始: {entity}")
        
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "system",
                        "content": f"{entity}について、簡潔に150字以内で説明してください。"
                    }],
                    temperature=0.3
                ),
                timeout=self.timeout
            )
            
            content = response.choices[0].message.content.strip()
            
            logger.info(f"✅ [{self.name}] 完了: {entity}")
            
            return {
                "source": self.name,
                "content": content,
                "metadata": {
                    "model": "gpt-4o-mini",
                    "type": "llm_knowledge"
                }
            }
            
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            return None


class BraveSearchSource(ResearchSource):
    """Brave Search APIによる最新情報取得"""
    
    def __init__(self, api_key: str = None):
        super().__init__(name="BraveSearch", priority=2, timeout=3.0)
        self.api_key = api_key
    
    async def search(self, entity: str) -> Optional[Dict]:
        if not self.api_key:
            logger.debug(f"⏭️  [{self.name}] API key not configured")
            return None
        
        logger.info(f"🔍 [{self.name}] リサーチ開始: {entity}")
        
        # TODO: Brave Search API実装
        # 現在はプレースホルダー
        
        return {
            "source": self.name,
            "content": f"[Brave Search] {entity}の最新情報（実装予定）",
            "metadata": {
                "type": "web_search",
                "count": 3
            }
        }


class OpenClawKnowledgeSource(ResearchSource):
    """OpenClawのナレッジファイル検索"""
    
    def __init__(self, gateway_url: str = None, token: str = None):
        super().__init__(name="OpenClawKnowledge", priority=3, timeout=2.0)
        self.gateway_url = gateway_url
        self.token = token
    
    async def search(self, entity: str) -> Optional[Dict]:
        if not self.gateway_url:
            logger.debug(f"⏭️  [{self.name}] Gateway not configured")
            return None
        
        logger.info(f"📚 [{self.name}] リサーチ開始: {entity}")
        
        # TODO: OpenClaw memory_search実装
        # memory_search tool経由でナレッジファイル検索
        
        return {
            "source": self.name,
            "content": f"[OpenClaw Knowledge] {entity}の関連情報（実装予定）",
            "metadata": {
                "type": "knowledge_base"
            }
        }


class LimitlessAPISource(ResearchSource):
    """Limitless APIによる文脈検索"""
    
    def __init__(self, api_key: str = None):
        super().__init__(name="LimitlessAPI", priority=4, timeout=5.0)
        self.api_key = api_key
    
    async def search(self, entity: str) -> Optional[Dict]:
        if not self.api_key:
            logger.debug(f"⏭️  [{self.name}] API key not configured")
            return None
        
        logger.info(f"🧠 [{self.name}] リサーチ開始: {entity}")
        
        # TODO: Limitless API実装
        
        return {
            "source": self.name,
            "content": f"[Limitless] {entity}の文脈情報（実装予定）",
            "metadata": {
                "type": "context_search"
            }
        }


class GogCLISource(ResearchSource):
    """gog CLIによる検索"""
    
    def __init__(self):
        super().__init__(name="gogCLI", priority=5, timeout=10.0)
    
    async def search(self, entity: str) -> Optional[Dict]:
        logger.info(f"🔎 [{self.name}] リサーチ開始: {entity}")
        
        # TODO: gog CLI実装（subprocess経由）
        
        return {
            "source": self.name,
            "content": f"[gog] {entity}の検索結果（実装予定）",
            "metadata": {
                "type": "cli_search"
            }
        }


class OpenClawInboxSource(ResearchSource):
    """OpenClaw inbox経由でタスク実行（疎結合）"""
    
    def __init__(self, workspace_path: str = None):
        super().__init__(name="OpenClawInbox", priority=3, timeout=10.0)
        
        # ワークスペースパスの設定
        if workspace_path:
            self.workspace = Path(workspace_path).expanduser()
        else:
            # デフォルト: ~/clawd/workspaces/experimentation
            self.workspace = Path.home() / "clawd" / "workspaces" / "experimentation"
        
        self.inbox_dir = self.workspace / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"   📁 Inbox: {self.inbox_dir}")
    
    async def search(self, entity: str) -> Optional[Dict]:
        logger.info(f"📥 [{self.name}] リサーチ開始: {entity}")
        
        # タスクIDを生成（ユニーク）
        task_id = f"research_{int(time.time() * 1000)}"
        task_file = self.inbox_dir / f"task_{task_id}.json"
        result_file = self.inbox_dir / f"result_{task_id}.json"
        
        # タスクを作成
        task = {
            "task_id": task_id,
            "action": "research",
            "entity": entity,
            "instructions": f"{entity}について、以下を調べてください：\n1. Web検索で最新情報を取得\n2. ナレッジファイル（MEMORY.md等）から関連情報を検索\n3. 結果を200字以内で要約",
            "created_at": datetime.now().isoformat()
        }
        
        try:
            # タスクファイルを書き込み
            task_file.write_text(json.dumps(task, ensure_ascii=False, indent=2))
            logger.info(f"   📝 タスク作成: {task_file.name}")
            
            # 結果を待機（タイムアウト付き）
            start_time = time.time()
            poll_interval = 0.2  # 200ms
            max_polls = int(self.timeout / poll_interval)
            
            for i in range(max_polls):
                if result_file.exists():
                    # 結果を読み取り
                    result_data = json.loads(result_file.read_text())
                    elapsed = time.time() - start_time
                    
                    logger.info(f"✅ [{self.name}] 結果受信 (t={elapsed:.2f}s)")
                    
                    # ファイルをクリーンアップ
                    task_file.unlink(missing_ok=True)
                    result_file.unlink(missing_ok=True)
                    
                    # 結果を返却
                    content = result_data.get("content", result_data.get("result", "結果なし"))
                    
                    return {
                        "source": self.name,
                        "content": content,
                        "metadata": {
                            "type": "openclaw_inbox",
                            "task_id": task_id,
                            "elapsed": elapsed,
                            **result_data.get("metadata", {})
                        }
                    }
                
                await asyncio.sleep(poll_interval)
            
            # タイムアウト
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity} ({self.timeout}s)")
            task_file.unlink(missing_ok=True)
            return None
            
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            task_file.unlink(missing_ok=True)
            result_file.unlink(missing_ok=True)
            return None


class ResearchOrchestrator:
    """複数ソースを並列実行し、結果を段階的に配信"""
    
    def __init__(
        self,
        sources: List[ResearchSource],
        on_result: Optional[Callable] = None
    ):
        """
        Args:
            sources: リサーチソースのリスト
            on_result: 結果コールバック（結果が届くたびに呼ばれる）
        """
        self.sources = sorted(sources, key=lambda s: s.priority)  # 優先度順
        self.on_result = on_result
        
        logger.info(f"🎯 Research Orchestrator initialized with {len(self.sources)} sources")
        for source in self.sources:
            logger.info(f"   - {source.name} (priority={source.priority}, timeout={source.timeout}s)")
    
    async def research(self, entity: str):
        """
        エンティティを複数ソースで並列リサーチ
        
        Args:
            entity: リサーチ対象
        """
        logger.info("=" * 60)
        logger.info(f"🚀 並列リサーチ開始: {entity}")
        logger.info(f"📊 ソース数: {len(self.sources)}")
        logger.info("-" * 60)
        
        start_time = asyncio.get_event_loop().time()
        
        # 全ソースを並列実行（as_completed で完了順に処理）
        tasks = [
            self._search_with_timing(source, entity)
            for source in self.sources
        ]
        
        result_count = 0
        
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                
                if result:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    result_count += 1
                    
                    logger.info(f"✅ [{result['source']}] 結果受信 (t={elapsed:.2f}s)")
                    logger.info(f"   {result['content'][:100]}...")
                    
                    # 結果を即座にコールバック配信
                    if self.on_result:
                        await self.on_result({
                            "type": "research_partial",
                            "entity": entity,
                            "source": result["source"],
                            "content": result["content"],
                            "metadata": result.get("metadata", {}),
                            "elapsed": elapsed,
                            "timestamp": datetime.now().isoformat()
                        })
                    
            except Exception as e:
                logger.error(f"❌ リサーチエラー: {e}")
        
        total_elapsed = asyncio.get_event_loop().time() - start_time
        
        logger.info("-" * 60)
        logger.info(f"🏁 リサーチ完了: {entity}")
        logger.info(f"📊 結果数: {result_count}/{len(self.sources)}")
        logger.info(f"⏱️  総時間: {total_elapsed:.2f}s")
        logger.info("=" * 60)
        
        # 完了通知
        if self.on_result:
            await self.on_result({
                "type": "research_complete",
                "entity": entity,
                "result_count": result_count,
                "total_elapsed": total_elapsed,
                "timestamp": datetime.now().isoformat()
            })
    
    async def _search_with_timing(self, source: ResearchSource, entity: str) -> Optional[Dict]:
        """ソースごとのタイミング測定付き検索"""
        try:
            result = await source.search(entity)
            return result
        except Exception as e:
            logger.error(f"❌ [{source.name}] 例外: {e}")
            return None
