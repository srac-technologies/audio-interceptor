"""
OpenClaw Gateway統合ブリッジ
Web検索・LLM問い合わせをOpenClaw経由で実行
"""

import os
import logging
import aiohttp
from typing import Optional, Dict, List

logger = logging.getLogger("OpenClawBridge")

class OpenClawBridge:
    def __init__(self, gateway_url: str = "http://localhost:18789", gateway_token: str = None):
        """
        OpenClaw Gateway統合ブリッジ
        
        Args:
            gateway_url: OpenClaw GatewayのURL
            gateway_token: 認証トークン
        """
        self.gateway_url = gateway_url
        self.gateway_token = gateway_token or os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
        
        logger.info(f"🌐 OpenClaw Gateway: {self.gateway_url}")
        logger.info(f"🔑 Token configured: {bool(self.gateway_token)}")
    
    async def search_web(self, query: str, count: int = 3) -> Optional[List[Dict]]:
        """
        OpenClaw経由でWeb検索を実行
        
        Args:
            query: 検索クエリ
            count: 結果数（デフォルト3件）
            
        Returns:
            検索結果のリスト（title, url, snippet）
        """
        logger.info(f"🔍 Web検索: {query}")
        
        # OpenClawのchat/completions経由でweb_searchを呼び出す
        endpoint = f"{self.gateway_url}/v1/chat/completions"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.gateway_token:
            headers["Authorization"] = f"Bearer {self.gateway_token}"
        
        payload = {
            "model": "gpt-4o-mini",  # 使用モデル
            "messages": [
                {
                    "role": "user",
                    "content": f"{query}について、最新の情報を3つ教えてください。簡潔に200字以内で要約してください。"
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "parameters": {
                            "query": query,
                            "count": count
                        }
                    }
                }
            ],
            "tool_choice": "auto"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # レスポンスから結果を抽出
                        if "choices" in data and len(data["choices"]) > 0:
                            message = data["choices"][0].get("message", {})
                            content = message.get("content", "")
                            
                            logger.info(f"✅ 検索結果取得成功")
                            return {
                                "summary": content,
                                "raw": data
                            }
                        else:
                            logger.warning("⚠️  レスポンスに結果がありません")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenClaw API error: {response.status} - {error_text}")
                        return None
                        
        except aiohttp.ClientTimeout:
            logger.error(f"❌ OpenClaw timeout: {query}")
            return None
        except Exception as e:
            logger.error(f"❌ OpenClaw request error: {e}")
            return None
    
    async def ask_llm(self, prompt: str, model: str = "gpt-4o-mini") -> Optional[str]:
        """
        OpenClaw経由でLLMに問い合わせ
        
        Args:
            prompt: プロンプト
            model: 使用モデル
            
        Returns:
            LLMの応答テキスト
        """
        endpoint = f"{self.gateway_url}/v1/chat/completions"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.gateway_token:
            headers["Authorization"] = f"Bearer {self.gateway_token}"
        
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if "choices" in data and len(data["choices"]) > 0:
                            message = data["choices"][0].get("message", {})
                            content = message.get("content", "")
                            return content
                        else:
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenClaw LLM error: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"❌ OpenClaw LLM request error: {e}")
            return None
