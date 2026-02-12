"""
Slack App統合モジュール
リサーチ結果をSlackスレッドに投稿（Slack Web API使用）
"""

import os
import logging
from typing import Optional, Dict
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger("SlackService")

class SlackService:
    def __init__(self, bot_token: str = None, channel: str = None):
        """
        Slack App統合サービス
        
        Args:
            bot_token: Slack Bot Token (xoxb-...)
            channel: 投稿先チャンネルID or 名前（例: #meeting-research, C01234567）
        """
        self.bot_token = bot_token
        self.channel = channel
        self.client = WebClient(token=bot_token) if bot_token else None
        self.thread_ts: Optional[str] = None  # スレッドのタイムスタンプ
        
    def create_thread(self, session_title: str) -> bool:
        """
        新しいスレッドを作成（録音開始時）
        
        Args:
            session_title: セッションのタイトル
            
        Returns:
            成功したらTrue
        """
        if not self.client or not self.channel:
            logger.warning("Slack client not configured")
            return False
            
        try:
            response = self.client.chat_postMessage(
                channel=self.channel,
                text=f"🎙️ リサーチセッション開始: {session_title}",
                blocks=[
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
            )
            
            # スレッドのタイムスタンプを保存
            self.thread_ts = response['ts']
            logger.info(f"Slack thread created: ts={self.thread_ts}")
            return True
                        
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            return False
        except Exception as e:
            logger.error(f"Failed to create Slack thread: {e}")
            return False
    
    def post_research_result(self, entity: str, result: str) -> bool:
        """
        リサーチ結果をスレッドに投稿
        
        Args:
            entity: 抽出されたエンティティ
            result: リサーチ結果
            
        Returns:
            成功したらTrue
        """
        if not self.client or not self.channel or not self.thread_ts:
            logger.warning("Slack client or thread not initialized")
            return False
            
        try:
            self.client.chat_postMessage(
                channel=self.channel,
                thread_ts=self.thread_ts,  # スレッドに返信
                text=f"🔍 {entity}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*🔍 {entity}*\n\n{result}"
                        }
                    }
                ]
            )
            
            logger.info(f"Posted research result for: {entity}")
            return True
                        
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            return False
        except Exception as e:
            logger.error(f"Failed to post research result: {e}")
            return False
