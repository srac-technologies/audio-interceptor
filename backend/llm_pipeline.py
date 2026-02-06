import os
import asyncio
import logging
from typing import List, Dict, Optional, Callable
from openai import AsyncOpenAI
import database

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLM_Pipeline")

class LLMPipeline:
    def __init__(self, meeting_type_id: Optional[int] = None, on_advice: Optional[Callable] = None):
        self.meeting_type_id = meeting_type_id
        self.on_advice = on_advice
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None
        
        self.transcript_buffer: List[str] = []
        self.buffer_size = 5  # 判定を行う発言数の単位
        
        # マスタデータからプロンプトをロード
        self.prompts = []
        if self.meeting_type_id:
            self.prompts = database.get_prompts_for_type(self.meeting_type_id)
            logger.info(f"Loaded {len(self.prompts)} prompts for meeting type {self.meeting_type_id}")

    async def process_transcript(self, source: str, text: str):
        """文字起こしテキストを処理する"""
        if not self.client or not self.prompts:
            return

        # バッファに追加
        entry = f"[{source}]: {text}"
        self.transcript_buffer.append(entry)
        
        # バッファがいっぱいになったら判定を実行
        if len(self.transcript_buffer) >= self.buffer_size:
            context = "\n".join(self.transcript_buffer)
            self.transcript_buffer = []  # バッファをクリア（または一部残すスライディングウィンドウも検討可）
            
            # 非同期でアドバイス生成タスクを開始
            asyncio.create_task(self.analyze_context(context))

    async def analyze_context(self, context: str):
        """コンテキストを分析してアドバイスが必要か判定する"""
        logger.info("Analyzing context for advice...")
        
        for prompt_config in self.prompts:
            trigger_condition = prompt_config['trigger_condition']
            action_prompt = prompt_config['action_prompt']
            
            # トリガー判定プロンプト
            system_prompt = f"""
あなたは会議のアシスタントAIです。
以下の会話履歴が、指定された「トリガー条件」に合致するかどうかを判定してください。
合致する場合は "YES"、合致しない場合は "NO" とだけ答えてください。

# トリガー条件
{trigger_condition}

# 会話履歴
{context}
"""
            try:
                response = await self.client.chat.completions.create(
                    model="gpt-4o-mini", # 高速・安価なモデルで判定
                    messages=[{"role": "system", "content": system_prompt}],
                    temperature=0.0
                )
                result = response.choices[0].message.content.strip().upper()
                
                if "YES" in result:
                    logger.info(f"Trigger matched: {trigger_condition}")
                    await self.generate_advice(context, action_prompt, trigger_condition)
                    # 1回の分析で複数のアドバイスが出すぎないようにbreak（要件次第）
                    break 
                    
            except Exception as e:
                logger.error(f"Error in trigger analysis: {e}")

    async def generate_advice(self, context: str, action_prompt: str, trigger_condition: str):
        """アドバイスを生成する"""
        system_prompt = f"""
あなたはプロフェッショナルな会議アドバイザーです。
会話履歴に基づき、ユーザーに対する具体的なアドバイスや切り返しトークを提案してください。

# 状況
{trigger_condition}

# 指示
{action_prompt}

# 制約
- アドバイスは簡潔かつ具体的に
- 箇条書きで1〜3点
- 丁寧なトーンで

# 会話履歴
{context}
"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o", # 品質の高いモデルで生成
                messages=[{"role": "system", "content": system_prompt}],
                temperature=0.7
            )
            advice_text = response.choices[0].message.content.strip()
            
            logger.info(f"Advice generated: {advice_text[:50]}...")
            
            # コールバックで通知
            if self.on_advice:
                await self.on_advice({
                    "type": "advice",
                    "trigger": trigger_condition,
                    "text": advice_text,
                    "timestamp": datetime.now().isoformat()
                })
                
        except Exception as e:
            logger.error(f"Error in advice generation: {e}")

    async def generate_summary(self, transcripts: List[Dict], prompt_text: str = None) -> str:
        """会議全体のサマリーを生成する"""
        if not self.client:
            return "OpenAI API Key not set"
            
        full_text = "\n".join([f"[{t['source']}]: {t['text']}" for t in transcripts])
        
        default_prompt = """
以下の会議の議事録を作成してください。

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
