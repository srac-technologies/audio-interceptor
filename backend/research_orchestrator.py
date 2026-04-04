"""
Research Orchestrator
複数のリサーチソースを並列実行し、結果を段階的に配信
"""

import asyncio
import logging
import time
import subprocess
from typing import Optional, Dict, List, Callable
from datetime import datetime
from pathlib import Path
import json

try:
    import aiohttp
except ImportError:
    aiohttp = None

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



class TavilySource(ResearchSource):
    """Tavily AI検索APIによる構造化された検索結果"""

    def __init__(self, api_key: str = None):
        super().__init__(name="Tavily", priority=2, timeout=5.0)
        self.api_key = api_key

    async def search(self, entity: str) -> Optional[Dict]:
        if not self.api_key or not aiohttp:
            logger.debug(f"⏭️  [{self.name}] API key or aiohttp not available")
            return None

        logger.info(f"🔍 [{self.name}] リサーチ開始: {entity}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.api_key,
                        "query": entity,
                        "search_depth": "basic",
                        "max_results": 3,
                        "include_answer": True
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️  [{self.name}] HTTP {resp.status}")
                        return None
                    data = await resp.json()

            answer = data.get("answer", "")
            results = data.get("results", [])
            urls = [r.get("url", "") for r in results[:3]]

            content = answer if answer else " | ".join(
                r.get("content", "")[:100] for r in results[:3]
            )

            logger.info(f"✅ [{self.name}] 完了: {entity}")
            return {
                "source": self.name,
                "content": content,
                "metadata": {"type": "ai_search", "urls": urls}
            }
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            return None


class PerplexitySource(ResearchSource):
    """Perplexity APIによるAI検索"""

    def __init__(self, api_key: str = None):
        super().__init__(name="Perplexity", priority=2, timeout=8.0)
        self.api_key = api_key

    async def search(self, entity: str) -> Optional[Dict]:
        if not self.api_key or not aiohttp:
            logger.debug(f"⏭️  [{self.name}] API key or aiohttp not available")
            return None

        logger.info(f"🔍 [{self.name}] リサーチ開始: {entity}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "sonar",
                        "messages": [
                            {"role": "system", "content": "簡潔に150字以内で回答してください。"},
                            {"role": "user", "content": f"{entity}について教えてください"}
                        ]
                    },
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️  [{self.name}] HTTP {resp.status}")
                        return None
                    data = await resp.json()

            content = data["choices"][0]["message"]["content"].strip()
            citations = data.get("citations", [])

            logger.info(f"✅ [{self.name}] 完了: {entity}")
            return {
                "source": self.name,
                "content": content,
                "metadata": {"type": "ai_search", "citations": citations}
            }
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            return None


class GoogleCustomSearchSource(ResearchSource):
    """Google Custom Search APIによるWeb検索"""

    def __init__(self, api_key: str = None, cx: str = None):
        super().__init__(name="GoogleSearch", priority=3, timeout=5.0)
        self.api_key = api_key
        self.cx = cx  # カスタム検索エンジンID

    async def search(self, entity: str) -> Optional[Dict]:
        if not self.api_key or not self.cx or not aiohttp:
            logger.debug(f"⏭️  [{self.name}] API key, CX, or aiohttp not available")
            return None

        logger.info(f"🔍 [{self.name}] リサーチ開始: {entity}")

        try:
            params = {
                "key": self.api_key,
                "cx": self.cx,
                "q": entity,
                "num": 3
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️  [{self.name}] HTTP {resp.status}")
                        return None
                    data = await resp.json()

            items = data.get("items", [])
            snippets = [item.get("snippet", "") for item in items[:3]]
            urls = [item.get("link", "") for item in items[:3]]
            content = " | ".join(snippets) if snippets else "検索結果なし"

            logger.info(f"✅ [{self.name}] 完了: {entity}")
            return {
                "source": self.name,
                "content": content,
                "metadata": {"type": "web_search", "urls": urls, "count": len(items)}
            }
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            return None


class LightPandaSource(ResearchSource):
    """LightPanda (agentic browser) によるJSレンダリング対応のWeb取得"""

    def __init__(self, api_key: str = None, endpoint: str = "https://api.lightpanda.io/v1"):
        super().__init__(name="LightPanda", priority=3, timeout=10.0)
        self.api_key = api_key
        self.endpoint = endpoint

    async def search(self, entity: str) -> Optional[Dict]:
        if not self.api_key or not aiohttp:
            logger.debug(f"⏭️  [{self.name}] API key or aiohttp not available")
            return None

        logger.info(f"🌐 [{self.name}] リサーチ開始: {entity}")

        try:
            search_url = f"https://www.google.com/search?q={entity}"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.endpoint}/fetch",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={"url": search_url, "render_js": True},
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️  [{self.name}] HTTP {resp.status}")
                        return None
                    data = await resp.json()

            content = data.get("text", data.get("content", ""))[:500]

            logger.info(f"✅ [{self.name}] 完了: {entity}")
            return {
                "source": self.name,
                "content": content,
                "metadata": {"type": "browser_fetch", "url": search_url}
            }
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            return None


class CustomAPISource(ResearchSource):
    """ユーザー定義のカスタムAPIエンドポイント"""

    def __init__(self, name: str, endpoint: str, headers: Dict = None,
                 method: str = "GET", body_template: str = None,
                 response_mapping: str = "content",
                 priority: int = 5, timeout: float = 5.0):
        super().__init__(name=name, priority=priority, timeout=timeout)
        self.endpoint = endpoint
        self.headers = headers or {}
        self.method = method.upper()
        self.body_template = body_template  # {entity} をプレースホルダとして使用
        self.response_mapping = response_mapping  # JSONパスのドット区切り (e.g. "data.result")

    async def search(self, entity: str) -> Optional[Dict]:
        if not aiohttp:
            logger.debug(f"⏭️  [{self.name}] aiohttp not available")
            return None

        logger.info(f"🔌 [{self.name}] リサーチ開始: {entity}")

        try:
            url = self.endpoint.replace("{entity}", entity)
            kwargs = {
                "headers": self.headers,
                "timeout": aiohttp.ClientTimeout(total=self.timeout)
            }

            if self.method == "POST" and self.body_template:
                body_str = self.body_template.replace("{entity}", entity)
                try:
                    kwargs["json"] = json.loads(body_str)
                except json.JSONDecodeError:
                    kwargs["data"] = body_str

            async with aiohttp.ClientSession() as session:
                request_method = getattr(session, self.method.lower())
                async with request_method(url, **kwargs) as resp:
                    if resp.status != 200:
                        logger.warning(f"⚠️  [{self.name}] HTTP {resp.status}")
                        return None

                    content_type = resp.headers.get("Content-Type", "")
                    if "json" in content_type:
                        data = await resp.json()
                        content = self._extract_field(data, self.response_mapping)
                    else:
                        content = await resp.text()
                        content = content[:500]

            logger.info(f"✅ [{self.name}] 完了: {entity}")
            return {
                "source": self.name,
                "content": str(content),
                "metadata": {"type": "custom_api", "endpoint": self.endpoint}
            }
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
            return None

    def _extract_field(self, data, path: str):
        """ドット区切りパスでJSONから値を抽出"""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key, current)
            else:
                break
        if isinstance(current, (dict, list)):
            return json.dumps(current, ensure_ascii=False)[:500]
        return str(current)[:500]


class ShellCommandSource(ResearchSource):
    """シェルコマンド実行型リサーチソース"""

    def __init__(self, name: str, command_template: str,
                 priority: int = 5, timeout: float = 10.0):
        """
        Args:
            name: ソース名
            command_template: コマンドテンプレート（{entity} をプレースホルダとして使用）
            priority: 優先度
            timeout: タイムアウト（秒）
        """
        super().__init__(name=name, priority=priority, timeout=timeout)
        self.command_template = command_template

    async def search(self, entity: str) -> Optional[Dict]:
        logger.info(f"🖥️  [{self.name}] リサーチ開始: {entity}")

        try:
            # シェルインジェクション対策: エンティティ内の危険な文字をエスケープ
            safe_entity = entity.replace("'", "'\\''")
            command = self.command_template.replace("{entity}", safe_entity)

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )

            output = stdout.decode("utf-8", errors="replace").strip()

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                logger.warning(f"⚠️  [{self.name}] 終了コード {process.returncode}: {error_msg[:100]}")
                if not output:
                    return None

            content = output[:500]

            logger.info(f"✅ [{self.name}] 完了: {entity}")
            return {
                "source": self.name,
                "content": content,
                "metadata": {"type": "shell_command", "command": self.command_template}
            }
        except asyncio.TimeoutError:
            logger.warning(f"⏱️  [{self.name}] タイムアウト: {entity}")
            try:
                process.kill()
            except:
                pass
            return None
        except Exception as e:
            logger.error(f"❌ [{self.name}] エラー: {e}")
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
