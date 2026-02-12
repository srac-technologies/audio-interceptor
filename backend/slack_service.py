"""
Slack統合モジュール
リサーチ結果をSlackスレッドに投稿
"""

import os
import logging
import json
from typing import Optional, Dict
import asyncio
import aiohttp

logger = logging.getLogger("SlackService")

class SlackService:
    def __init__(self, webhook_url: str = None, channel: str = None):
        """
        Slack統合サービス
        
        Args:
            webhook_url: Slack Incoming Webhook URL
            channel: 投稿先チャンネル（オプション、webhook URLで指定されていない場合）
        """
        self.webhook_url = webhook_url
        self.channel = channel
        self.thread_ts: Optional[str] = None  # スレッドのタイムスタンプ
        
    async def create_thread(self, session_title: str) -> bool:
        """
        新しいスレッドを作成（録音開始時）
        
        Args:
            session_title: セッションのタイトル
            
        Returns:
            成功したらTrue
        """
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False
            
        try:
            message = {
                "text": f"🎙️ リサーチセッション開始: {session_title}",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"🎙️ {session_title}"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "リサーチ結果をこのスレッドに投稿します"
                            }
                        ]
                    }
                ]
            }
            
            if self.channel:
                message["channel"] = self.channel
                
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=message) as response:
                    if response.status == 200:
                        # Note: Incoming Webhookはthread_tsを返さないので、
                        # メッセージIDベースのスレッディングは使えない
                        # 代わりに、連続投稿でスレッド風に見せる
                        logger.info("Slack thread initialized")
                        return True
                    else:
                        logger.error(f"Slack API error: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Failed to create Slack thread: {e}")
            return False
    
    async def post_research_result(self, entity: str, result: str) -> bool:
        """
        リサーチ結果をスレッドに投稿
        
        Args:
            entity: 抽出されたエンティティ
            result: リサーチ結果
            
        Returns:
            成功したらTrue
        """
        if not self.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False
            
        try:
            message = {
                "text": f"🔍 {entity}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*🔍 {entity}*\n\n{result}"
                        }
                    }
                ]
            }
            
            if self.channel:
                message["channel"] = self.channel
                
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=message) as response:
                    if response.status == 200:
                        logger.info(f"Posted research result for: {entity}")
                        return True
                    else:
                        logger.error(f"Slack API error: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Failed to post research result: {e}")
            return False
