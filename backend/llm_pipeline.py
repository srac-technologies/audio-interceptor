import os
import asyncio
import logging
import json
from typing import List, Dict, Optional, Callable
from openai import AsyncOpenAI
import database
from research_orchestrator import (
    ResearchOrchestrator,
    LLMSource,
    BraveSearchSource,
    TavilySource,
    PerplexitySource,
    GoogleCustomSearchSource,
    LightPandaSource,
    LimitlessAPISource,
    GogCLISource,
    CustomAPISource,
    ShellCommandSource,
)
from refinement_providers import create_refinement_provider, RefinementProvider

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
        
        # リサーチ済みエンティティのキャッシュ（セッション内で重複防止）
        self.researched_entities: set = set()
        
        # 設定からリサーチ設定をロード
        settings = database.get_settings()
        self.ner_prompt = settings.get('ner_prompt', '')
        self.research_enabled = settings.get('research_enabled', 'false') == 'true'
        self.research_method = settings.get('research_method', 'llm')
        self.buffer_size = int(settings.get('research_buffer_size', '2'))
        self.target_sources = settings.get('research_target_sources', 'speaker')  # speaker, mic, both
        self.transcription_refinement = settings.get('research_transcription_refinement', 'false') == 'true'

        # 精度向上プロバイダの設定
        self.refinement_provider_id = settings.get('refinement_provider', 'openai')
        self.refinement_model = settings.get('refinement_model', '')
        self.custom_dictionary = settings.get('custom_dictionary', '')
        self.refinement_provider: Optional[RefinementProvider] = None
        if self.transcription_refinement:
            self.refinement_provider = self._init_refinement_provider(settings)

        # Research Orchestratorの初期化
        self.orchestrator = None
        if self.research_enabled:
            self.orchestrator = self._init_orchestrator(settings)
        
        logger.info(f"🔍 Research enabled: {self.research_enabled}")
        logger.info(f"📝 NER prompt configured: {bool(self.ner_prompt)}")
        logger.info(f"🎯 Research method: {self.research_method}")
        logger.info(f"📊 Buffer size: {self.buffer_size} 発言")
        logger.info(f"🎙️  Target sources: {self.target_sources}")
        logger.info(f"✨ Transcription refinement: {self.transcription_refinement}")
        logger.info(f"🔧 Refinement provider: {self.refinement_provider_id}")
        logger.info(f"📖 Custom dictionary: {'configured' if self.custom_dictionary else 'none'}")
        logger.info(f"💾 Research cache initialized")
    
    def _init_refinement_provider(self, settings: Dict) -> Optional[RefinementProvider]:
        """精度向上プロバイダを初期化"""
        provider_id = settings.get('refinement_provider', 'openai')
        model = settings.get('refinement_model', '')
        kwargs = {}
        if model:
            kwargs['model'] = model
        try:
            provider = create_refinement_provider(provider_id, **kwargs)
            logger.info(f"  ✅ Refinement provider: {provider_id}" + (f" ({model})" if model else ""))
            return provider
        except Exception as e:
            logger.warning(f"  ⚠️  Failed to init refinement provider '{provider_id}': {e}")
            # フォールバック: OpenAI
            if provider_id != "openai":
                try:
                    return create_refinement_provider("openai")
                except Exception:
                    pass
            return None

    def _reload_settings(self):
        """設定を動的に再読み込み（録音中の設定変更に対応）"""
        settings = database.get_settings()
        
        # 変更検知用の古い値を保存
        old_enabled = self.research_enabled
        old_buffer_size = self.buffer_size
        old_target_sources = self.target_sources
        old_refinement = self.transcription_refinement
        old_method = self.research_method
        
        # 設定を更新
        self.research_enabled = settings.get('research_enabled', 'false') == 'true'
        self.buffer_size = int(settings.get('research_buffer_size', '2'))
        self.target_sources = settings.get('research_target_sources', 'speaker')
        self.transcription_refinement = settings.get('research_transcription_refinement', 'false') == 'true'
        self.ner_prompt = settings.get('ner_prompt', '')
        self.research_method = settings.get('research_method', 'llm')
        
        # 変更があればログ出力
        if old_enabled != self.research_enabled:
            logger.info(f"🔄 Research enabled changed: {old_enabled} → {self.research_enabled}")
            # 有効化された場合はOrchestratorを初期化
            if self.research_enabled and not self.orchestrator:
                self.orchestrator = self._init_orchestrator(settings)
                logger.info("   ✅ Orchestrator initialized")
        
        if old_buffer_size != self.buffer_size:
            logger.info(f"🔄 Buffer size changed: {old_buffer_size} → {self.buffer_size}")
            # バッファサイズ変更時はバッファをクリア
            if len(self.transcript_buffer) > 0:
                logger.info(f"   🗑️  Clearing buffer ({len(self.transcript_buffer)} items)")
                self.transcript_buffer = []
        
        if old_target_sources != self.target_sources:
            logger.info(f"🔄 Target sources changed: {old_target_sources} → {self.target_sources}")
            # 対象変更時もバッファをクリア
            if len(self.transcript_buffer) > 0:
                logger.info(f"   🗑️  Clearing buffer ({len(self.transcript_buffer)} items)")
                self.transcript_buffer = []
        
        if old_refinement != self.transcription_refinement:
            logger.info(f"🔄 Transcription refinement changed: {old_refinement} → {self.transcription_refinement}")
            if self.transcription_refinement and not self.refinement_provider:
                self.refinement_provider = self._init_refinement_provider(settings)

        # 精度向上プロバイダの変更検知
        new_provider_id = settings.get('refinement_provider', 'openai')
        new_refinement_model = settings.get('refinement_model', '')
        if new_provider_id != self.refinement_provider_id or new_refinement_model != self.refinement_model:
            logger.info(f"🔄 Refinement provider changed: {self.refinement_provider_id} → {new_provider_id}")
            self.refinement_provider_id = new_provider_id
            self.refinement_model = new_refinement_model
            if self.transcription_refinement:
                self.refinement_provider = self._init_refinement_provider(settings)

        self.custom_dictionary = settings.get('custom_dictionary', '')

        if old_method != self.research_method:
            logger.info(f"🔄 Research method changed: {old_method} → {self.research_method}")
            # メソッド変更時はOrchestratorを再初期化
            if self.research_enabled:
                self.orchestrator = self._init_orchestrator(settings)
                logger.info("   ✅ Orchestrator re-initialized")
    
    def _init_orchestrator(self, settings: Dict) -> ResearchOrchestrator:
        """Research OrchestratorをDBのソース設定に基づいて初期化"""
        sources = []

        # DBから有効なソース一覧を取得
        db_sources = database.get_research_sources(enabled_only=True)

        # 組み込みソースのファクトリマップ
        builtin_factory = {
            "LLM": lambda s: LLMSource(self.client),
            "BraveSearch": lambda s: BraveSearchSource(
                api_key=os.environ.get(json.loads(s['config']).get('env_key', 'BRAVE_API_KEY'))
            ),
            "Tavily": lambda s: TavilySource(
                api_key=os.environ.get(json.loads(s['config']).get('env_key', 'TAVILY_API_KEY'))
            ),
            "Perplexity": lambda s: PerplexitySource(
                api_key=os.environ.get(json.loads(s['config']).get('env_key', 'PERPLEXITY_API_KEY'))
            ),
            "GoogleSearch": lambda s: GoogleCustomSearchSource(
                api_key=os.environ.get(json.loads(s['config']).get('env_key', 'GOOGLE_CSE_API_KEY')),
                cx=os.environ.get(json.loads(s['config']).get('cx_env_key', 'GOOGLE_CSE_CX'))
            ),
            "LightPanda": lambda s: LightPandaSource(
                api_key=os.environ.get(json.loads(s['config']).get('env_key', 'LIGHTPANDA_API_KEY'))
            ),
            "LimitlessAPI": lambda s: LimitlessAPISource(
                api_key=os.environ.get(json.loads(s['config']).get('env_key', 'LIMITLESS_API_KEY'))
            ),
            "gogCLI": lambda s: GogCLISource(),
        }

        for db_src in db_sources:
            try:
                src_name = db_src['name']
                src_type = db_src['source_type']
                config = json.loads(db_src.get('config', '{}'))

                if src_type == 'builtin':
                    factory = builtin_factory.get(src_name)
                    if factory:
                        source = factory(db_src)
                        source.priority = db_src['priority']
                        source.timeout = db_src['timeout']
                        sources.append(source)
                        logger.info(f"  ✅ {src_name} enabled (priority={db_src['priority']})")

                elif src_type == 'custom_api':
                    source = CustomAPISource(
                        name=src_name,
                        endpoint=config.get('endpoint', ''),
                        headers=config.get('headers', {}),
                        method=config.get('method', 'GET'),
                        body_template=config.get('body_template'),
                        response_mapping=config.get('response_mapping', 'content'),
                        priority=db_src['priority'],
                        timeout=db_src['timeout']
                    )
                    sources.append(source)
                    logger.info(f"  ✅ [Custom API] {src_name} enabled (priority={db_src['priority']})")

                elif src_type == 'shell_command':
                    source = ShellCommandSource(
                        name=src_name,
                        command_template=config.get('command', ''),
                        priority=db_src['priority'],
                        timeout=db_src['timeout']
                    )
                    sources.append(source)
                    logger.info(f"  ✅ [Shell] {src_name} enabled (priority={db_src['priority']})")

            except Exception as e:
                logger.error(f"  ❌ ソース初期化エラー ({db_src.get('name', '?')}): {e}")

        if not sources:
            # フォールバック: LLMソースのみ
            sources.append(LLMSource(self.client))
            logger.info("  ⚠️  有効なソースなし → LLMフォールバック")

        return ResearchOrchestrator(sources, on_result=self._on_orchestrator_result)
    
    async def _on_orchestrator_result(self, result_data: Dict):
        """Orchestratorからの結果を受信してコールバック"""
        if result_data["type"] == "research_partial":
            # 部分的な結果を配信
            if self.on_research:
                await self.on_research({
                    "type": "research",
                    "entity": result_data["entity"],
                    "text": f"[{result_data['source']}] {result_data['content']}",
                    "source": result_data["source"],
                    "timestamp": result_data["timestamp"]
                })

    async def process_transcript(self, source: str, text: str):
        """文字起こしテキストを処理する（リサーチ用）"""
        if not self.client:
            logger.warning(f"⚠️  OpenAI client not initialized")
            return
        
        # 最新の設定を動的に読み込み（録音中の設定変更に対応）
        self._reload_settings()
        
        if not self.research_enabled:
            logger.debug(f"⏭️  Research disabled")
            return
        
        # ソース判定（target_sourcesの設定に基づく）
        source_lower = source.lower()
        should_process = False
        
        if self.target_sources == "speaker" and source_lower == "speaker":
            should_process = True
        elif self.target_sources == "mic" and source_lower == "mic":
            should_process = True
        elif self.target_sources == "both":
            should_process = True
        
        if not should_process:
            logger.debug(f"⏭️  Skipping [{source}] (target: {self.target_sources})")
            return

        # バッファに追加
        entry = f"[{source}]: {text}"
        self.transcript_buffer.append(entry)
        
        icon = "🔊" if source_lower == "speaker" else "🎤"
        logger.info(f"{icon} [{source}] バッファに追加: {len(self.transcript_buffer)}/{self.buffer_size}")
        
        # バッファがいっぱいになったらNER実行
        if len(self.transcript_buffer) >= self.buffer_size:
            logger.info(f"✨ バッファ満タン（{self.buffer_size}発言）→ NER実行")
            context = "\n".join(self.transcript_buffer)
            self.transcript_buffer = []  # バッファをクリア
            
            # 非同期でNER + リサーチタスクを開始
            asyncio.create_task(self.extract_and_research(context))

    async def extract_and_research(self, context: str):
        """NERでエンティティ抽出 → リサーチ実行（重複スキップ）"""
        logger.info("=" * 60)
        logger.info("🔍 NER実行開始")
        logger.info(f"対象文言（元）:\n{context}")
        logger.info("-" * 60)
        
        # 0. 文字起こし精度向上（オプション）
        if self.transcription_refinement:
            context = await self.refine_transcription(context)
            logger.info(f"対象文言（精度向上後）:\n{context}")
            logger.info("-" * 60)
        
        # 1. NER実行
        entities = await self.extract_entities(context)
        
        if not entities:
            logger.info("❌ エンティティ抽出なし")
            logger.info("=" * 60)
            return
        
        logger.info(f"✅ 抽出されたエンティティ: {', '.join(entities)}")
        
        # 2. 未リサーチのエンティティのみフィルタリング
        new_entities = [e for e in entities if e not in self.researched_entities]
        cached_entities = [e for e in entities if e in self.researched_entities]
        
        if cached_entities:
            logger.info(f"💾 キャッシュ済み（スキップ）: {', '.join(cached_entities)}")
        
        if not new_entities:
            logger.info("⏭️  全てリサーチ済み → スキップ")
            logger.info("=" * 60)
            return
        
        logger.info(f"🆕 新規リサーチ対象: {', '.join(new_entities)}")
        logger.info("=" * 60)
        
        # 3. 新規エンティティのみリサーチ
        for entity in new_entities:
            await self.research_entity(entity)
            # リサーチ完了後、キャッシュに追加
            self.researched_entities.add(entity)
        
        logger.info(f"📊 キャッシュ状態: {len(self.researched_entities)}件のエンティティをリサーチ済み")
    
    async def refine_transcription(self, context: str) -> str:
        """
        文字起こしの精度向上（設定されたLLMプロバイダで修正）

        Args:
            context: 元の文字起こしテキスト

        Returns:
            精度向上後のテキスト
        """
        logger.info(f"✨ 文字起こし精度向上を実行中... (provider: {self.refinement_provider_id})")

        if self.refinement_provider:
            try:
                custom_dict = self.custom_dictionary if self.custom_dictionary else None
                refined = await self.refinement_provider.refine(context, custom_dict=custom_dict)
                logger.info("✅ 文字起こし精度向上完了")
                return refined
            except Exception as e:
                logger.error(f"❌ 精度向上エラー ({self.refinement_provider_id}): {e}")
                return context

        # フォールバック: 直接OpenAI APIを使用
        logger.info("⚠️  Refinement provider not available, using OpenAI fallback")
        refinement_prompt = """
以下の音声文字起こしテキストを、より正確で読みやすい形に修正してください。

# 修正方針
- 誤変換を修正（例: 「人工無能」→「人工知能」）
- 句読点を適切に追加
- 固有名詞を正しい表記に修正（企業名、製品名、人名など）
- 発話の意図を保ちつつ、自然な日本語に整形
- 形式は元のまま維持（[source]: text）

# 元のテキスト
{context}

# 修正後のテキスト（形式を維持）
"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": refinement_prompt.format(context=context)}],
                temperature=0.1,
            )
            refined = response.choices[0].message.content.strip()
            logger.info("✅ 文字起こし精度向上完了 (fallback)")
            return refined
        except Exception as e:
            logger.error(f"❌ 文字起こし精度向上エラー: {e}")
            return context
    
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
        エンティティをリサーチ（Orchestrator経由で並列実行）
        
        Args:
            entity: リサーチ対象のエンティティ
        """
        if self.orchestrator:
            # Orchestrator経由で並列リサーチ
            await self.orchestrator.research(entity)
        else:
            # フォールバック: LLMのみ
            logger.info("")
            logger.info("📚 リサーチ開始（LLMのみ）")
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
