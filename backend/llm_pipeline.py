import os
import asyncio
import logging
import json
from typing import List, Dict, Optional, Callable
from openai import AsyncOpenAI
import database

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLM_Pipeline")

class LLMPipeline:
    def __init__(self, on_research: Optional[Callable] = None):
        """
        LLMパイプライン（リサーチ機能）
        
        Args:
            on_research: リサーチ結果のコールバック関数
        """
        self.on_research = on_research
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None
        
        logger.info(f"🔑 OpenAI API Key configured: {bool(self.api_key)}")
        logger.info(f"🤖 OpenAI Client initialized: {bool(self.client)}")
        
        self.transcript_buffer: List[str] = []
        self.buffer_size = 2  # NER実行を行う発言数の単位（スピーカー発言のみカウント）
        
        # 設定からNERプロンプトをロード
        settings = database.get_settings()
        self.ner_prompt = settings.get('ner_prompt', '')
        self.research_enabled = settings.get('research_enabled', 'false') == 'true'
        
        logger.info(f"🔍 Research enabled: {self.research_enabled}")
        logger.info(f"📝 NER prompt configured: {bool(self.ner_prompt)}")
        logger.info(f"📊 Buffer size: {self.buffer_size}")

    async def process_transcript(self, source: str, text: str):
        """文字起こしテキストを処理する（リサーチ用）- スピーカーのみ対象"""
        if not self.client:
            logger.warning(f"⚠️  OpenAI client not initialized")
            return
        
        if not self.research_enabled:
            logger.warning(f"⚠️  Research not enabled (setting)")
            return
        
        # スピーカー（相手側）の発言のみ対象
        if source.lower() != "speaker":
            logger.debug(f"⏭️  Skipping non-speaker: [{source}] {text[:30]}...")
            return

        # バッファに追加
        entry = f"[{source}]: {text}"
        self.transcript_buffer.append(entry)
        logger.info(f"🔊 スピーカー発言をバッファに追加: {len(self.transcript_buffer)}/{self.buffer_size}")
        
        # バッファがいっぱいになったらNER実行
        if len(self.transcript_buffer) >= self.buffer_size:
            logger.info(f"✨ バッファ満タン（{self.buffer_size}発言）→ NER実行")
            context = "\n".join(self.transcript_buffer)
            self.transcript_buffer = []  # バッファをクリア
            
            # 非同期でNER + リサーチタスクを開始
            asyncio.create_task(self.extract_and_research(context))

    async def extract_and_research(self, context: str):
        """NERでエンティティ抽出 → リサーチ実行"""
        logger.info("=" * 60)
        logger.info("🔍 NER実行開始")
        logger.info(f"対象文言:\n{context}")
        logger.info("-" * 60)
        
        # 1. NER実行
        entities = await self.extract_entities(context)
        
        if not entities:
            logger.info("❌ エンティティ抽出なし")
            logger.info("=" * 60)
            return
        
        logger.info(f"✅ 抽出されたエンティティ: {', '.join(entities)}")
        logger.info("=" * 60)
        
        # 2. 各エンティティをリサーチ
        for entity in entities:
            await self.research_entity(entity)
    
    async def extract_entities(self, context: str) -> List[str]:
        """
        NERでエンティティを抽出
        
        Args:
            context: 会話履歴
            
        Returns:
            抽出されたエンティティのリスト
        """
        if not self.ner_prompt:
            logger.warning("NER prompt not configured")
            return []
        
        system_prompt = f"""
{self.ner_prompt}

# 会話履歴
{context}
"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            result = response.choices[0].message.content.strip()
            logger.info(f"NER応答: {result}")
            
            data = json.loads(result)
            entities = data.get("entities", [])
            
            # 重複を除去して返す
            return list(set(entities))
            
        except Exception as e:
            logger.error(f"❌ NERエラー: {e}")
            return []
    
    async def research_entity(self, entity: str):
        """
        エンティティをリサーチ
        
        Args:
            entity: リサーチ対象のエンティティ
        """
        logger.info("")
        logger.info("📚 リサーチ開始")
        logger.info(f"対象: {entity}")
        
        research_prompt = f"""
以下のトピックについて、簡潔に説明してください（200字以内）：

{entity}

# 制約
- 最新の情報に基づいて説明
- 専門用語は分かりやすく
- 簡潔に要点のみ
"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": research_prompt}],
                temperature=0.3
            )
            research_text = response.choices[0].message.content.strip()
            
            logger.info(f"結果:\n{research_text}")
            logger.info("-" * 60)
            
            # コールバックで通知
            if self.on_research:
                await self.on_research({
                    "type": "research",
                    "entity": entity,
                    "text": research_text,
                    "timestamp": datetime.now().isoformat()
                })
                
        except Exception as e:
            logger.error(f"❌ リサーチエラー ({entity}): {e}")
            logger.info("-" * 60)

    async def generate_summary(self, transcripts: List[Dict], start_time: str = None, prompt_text: str = None) -> str:
        """会議全体のサマリーを生成する
        
        Args:
            transcripts: 文字起こしのリスト
            start_time: 会議開始日時（ISO形式）
            prompt_text: カスタムプロンプト（省略時はデフォルト）
        """
        if not self.client:
            return "OpenAI API Key not set"
            
        full_text = "\n".join([f"[{t['source']}]: {t['text']}" for t in transcripts])
        
        # 日時情報をプロンプトに追加
        date_info = ""
        if start_time:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                date_info = f"\n# 会議日時\n{dt.strftime('%Y年%m月%d日 %H:%M')} 開始\n"
            except:
                pass
        
        default_prompt = f"""
以下の会議の議事録を作成してください。
{date_info}
# 要件
- 重要な決定事項
- 次のアクションアイテム
- 議論の要約
をMarkdown形式でまとめてください。
"""
        
        system_prompt = prompt_text if prompt_text else default_prompt
        
        try:
            logger.info("Generating meeting summary...")
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"# 会議ログ\n{full_text}"}
                ],
                temperature=0.5
            )
            summary = response.choices[0].message.content.strip()
            logger.info("Summary generated successfully")
            return summary
            
        except Exception as e:
            logger.error(f"Error in summary generation: {e}")
            return f"Error generating summary: {str(e)}"

from datetime import datetime
