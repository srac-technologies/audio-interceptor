#!/usr/bin/env python3
"""
Refinement Providers - 文字起こし精度向上用LLMプロバイダ

複数のLLMプロバイダを統一インターフェースで切り替え可能にする。
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

REFINEMENT_PROMPT = """
以下の音声文字起こしテキストを、より正確で読みやすい形に修正してください。

# 修正方針
- 誤変換を修正（例: 「人工無能」→「人工知能」）
- 句読点を適切に追加
- 固有名詞を正しい表記に修正（企業名、製品名、人名など）
- 発話の意図を保ちつつ、自然な日本語に整形
- 形式は元のまま維持（[source]: text）
{custom_dict_section}
# 元のテキスト
{context}

# 修正後のテキスト（形式を維持）
"""


class RefinementProvider(ABC):
    """精度向上LLMプロバイダの基底クラス"""

    name: str = "base"
    description: str = ""

    @abstractmethod
    async def refine(self, context: str, custom_dict: Optional[str] = None) -> str:
        """テキストを精度向上する"""
        pass

    @classmethod
    def is_available(cls) -> bool:
        return True

    def _build_prompt(self, context: str, custom_dict: Optional[str] = None) -> str:
        dict_section = ""
        if custom_dict:
            dict_section = f"\n# 専門用語辞書（優先的に使用）\n{custom_dict}\n"
        return REFINEMENT_PROMPT.format(context=context, custom_dict_section=dict_section)


class OpenAIRefinementProvider(RefinementProvider):
    """OpenAI (GPT-4o-mini / GPT-4o)"""

    name = "openai"
    description = "OpenAI GPT-4o-mini - 高速・低コスト"

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        self.model = model
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    async def refine(self, context: str, custom_dict: Optional[str] = None) -> str:
        prompt = self._build_prompt(context, custom_dict)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()

    @classmethod
    def is_available(cls) -> bool:
        try:
            import openai  # noqa: F401
            return bool(os.getenv("OPENAI_API_KEY"))
        except ImportError:
            return False


class ClaudeRefinementProvider(RefinementProvider):
    """Anthropic Claude (Haiku / Sonnet)"""

    name = "claude"
    description = "Claude Haiku - 高速・低コスト・日本語に強い"

    def __init__(self, model: str = "claude-haiku-4-5-20251001", api_key: Optional[str] = None):
        self.model = model
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    async def refine(self, context: str, custom_dict: Optional[str] = None) -> str:
        prompt = self._build_prompt(context, custom_dict)
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    @classmethod
    def is_available(cls) -> bool:
        try:
            import anthropic  # noqa: F401
            return bool(os.getenv("ANTHROPIC_API_KEY"))
        except ImportError:
            return False


class GeminiRefinementProvider(RefinementProvider):
    """Google Gemini (Flash / Pro)"""

    name = "gemini"
    description = "Gemini Flash - 超高速・低コスト"

    def __init__(self, model: str = "gemini-2.0-flash", api_key: Optional[str] = None):
        self.model = model
        import google.generativeai as genai
        genai.configure(api_key=api_key or os.getenv("GOOGLE_AI_API_KEY"))
        self.genai_model = genai.GenerativeModel(self.model)

    async def refine(self, context: str, custom_dict: Optional[str] = None) -> str:
        import asyncio
        prompt = self._build_prompt(context, custom_dict)
        response = await asyncio.to_thread(
            self.genai_model.generate_content, prompt
        )
        return response.text.strip()

    @classmethod
    def is_available(cls) -> bool:
        try:
            import google.generativeai  # noqa: F401
            return bool(os.getenv("GOOGLE_AI_API_KEY"))
        except ImportError:
            return False


class OllamaRefinementProvider(RefinementProvider):
    """Ollama（ローカルLLM）"""

    name = "ollama"
    description = "Ollama (ローカルLLM) - オフライン対応・無料"

    def __init__(self, model: str = "gemma2:9b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    async def refine(self, context: str, custom_dict: Optional[str] = None) -> str:
        import aiohttp

        prompt = self._build_prompt(context, custom_dict)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/generate", json=payload, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ollama error: {resp.status}")
                data = await resp.json()
                return data["response"].strip()

    @classmethod
    def is_available(cls) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            return False


# プロバイダレジストリ
PROVIDER_REGISTRY: Dict[str, type] = {
    "openai": OpenAIRefinementProvider,
    "claude": ClaudeRefinementProvider,
    "gemini": GeminiRefinementProvider,
    "ollama": OllamaRefinementProvider,
}


def get_available_providers() -> List[Dict[str, Any]]:
    """利用可能なプロバイダ一覧を返す"""
    providers = []
    for key, cls in PROVIDER_REGISTRY.items():
        providers.append({
            "id": key,
            "name": cls.name,
            "description": cls.description,
            "available": cls.is_available(),
        })
    return providers


def create_refinement_provider(provider_id: str, **kwargs) -> RefinementProvider:
    """プロバイダIDからインスタンスを生成"""
    if provider_id not in PROVIDER_REGISTRY:
        raise ValueError(f"Unknown provider: {provider_id}. Available: {list(PROVIDER_REGISTRY.keys())}")
    return PROVIDER_REGISTRY[provider_id](**kwargs)
