"""Backend-agnostic LLM client for the graphic-recording viewer.

Three backends are supported; pick via ``LLM_BACKEND`` env:

  - ``ollama`` (default): local Ollama HTTP API. Mirrors canvas/llm.py:
    /api/chat, format="json", think=False, /no_think system prefix.
  - ``openai``: chat.completions with response_format=json_object.
  - ``anthropic``: messages API. JSON is enforced via the system prompt and
    parsed out of the first ``{...}`` block.

Every backend returns the same shape:
    {"nodes": [{"label": ..., "kind": ..., "parent_label": ...}, ...],
     "edges": [{"from_label": ..., "to_label": ..., "rel": ...}, ...]}
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Lifted from canvas/llm.py:16-35. Kept verbatim so the LLM behaviour is
# identical across the two projects; the only thing this module changes is
# the transport.
SYSTEM_PROMPT = (
    "/no_think\n"
    "あなたは議事録から構造を抽出するJSONエディタです。"
    "出力は必ずJSONのみ。説明文・前置き・コードフェンス・思考過程は禁止。\n\n"
    "出力スキーマ:\n"
    '{"nodes":[{"label":"短いキーワード(8-15字)","kind":"topic|decision|action|question|fact","parent_label":"既存ノードのlabel もしくは root"}],\n'
    ' "edges":[{"from_label":"...","to_label":"...","rel":"supports|contradicts|leads_to|related"}]}\n\n'
    "kind の選択基準:\n"
    "- topic: 議題・テーマそのもの\n"
    "- decision: 確定した決定事項\n"
    "- action: TODO・実行すべきタスク\n"
    "- question: 未解決の疑問・確認事項\n"
    "- fact: 報告された事実・現状\n\n"
    "厳守ルール:\n"
    "1. 既存IRが渡された場合、parent_labelは可能な限り既存ノードのlabelを再利用する（新規に作り直さない）\n"
    "2. 同じ意味のトピックは新規追加せず既存labelをそのまま使う\n"
    "3. labelは短く要約 (8-15文字)。長い文や説明は禁止\n"
    "4. edgesは構造的親子ではなく、意味的なつながり（対立・促進など）に限る\n"
    "5. 抽出する価値がない（雑談・あいさつ等）チャンクは {\"nodes\":[],\"edges\":[]} を返す"
)


def _build_user_prompt(transcript_chunk: str, existing_ir_summary: str) -> str:
    return (
        f"既存IR:\n{existing_ir_summary or '(まだなし)'}\n\n"
        f"新しい発話チャンク:\n{transcript_chunk}\n\n"
        "上記から新規ノードと意味的エッジを抽出してJSONで返してください。"
    )


def _lenient_parse(text: str) -> dict[str, Any]:
    """Pull the first ``{...}`` block and json.loads it. Returns empty IR on failure."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {"nodes": [], "edges": []}


@dataclass(frozen=True, slots=True)
class LLMConfig:
    backend: str          # "ollama" | "openai" | "anthropic"
    model: str
    ollama_url: str       # used iff backend == "ollama"
    openai_api_key: str   # used iff backend == "openai"
    openai_base_url: str
    anthropic_api_key: str
    timeout_seconds: float
    temperature: float
    num_predict: int


def load_llm_config() -> LLMConfig:
    backend = os.environ.get("LLM_BACKEND", "ollama").strip().lower()
    if backend not in {"ollama", "openai", "anthropic"}:
        raise ValueError(
            f"unsupported LLM_BACKEND={backend!r} (expected ollama/openai/anthropic)"
        )
    defaults_by_backend = {
        "ollama": ("qwen3.5:9b", "OLLAMA_MODEL"),
        "openai": ("gpt-4o-mini", "OPENAI_MODEL"),
        "anthropic": ("claude-haiku-4-5-20251001", "ANTHROPIC_MODEL"),
    }
    default_model, env_var = defaults_by_backend[backend]
    return LLMConfig(
        backend=backend,
        model=os.environ.get(env_var, default_model),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "180")),
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0.1")),
        num_predict=int(os.environ.get("LLM_NUM_PREDICT", "512")),
    )


class LLMError(RuntimeError):
    pass


async def call_llm(
    config: LLMConfig,
    transcript_chunk: str,
    existing_ir_summary: str = "",
) -> dict[str, Any]:
    """Run one extraction request against the configured backend."""
    user = _build_user_prompt(transcript_chunk, existing_ir_summary)
    if config.backend == "ollama":
        return await _call_ollama(config, user)
    if config.backend == "openai":
        if not config.openai_api_key:
            raise LLMError("OPENAI_API_KEY is required for LLM_BACKEND=openai")
        return await _call_openai(config, user)
    if config.backend == "anthropic":
        if not config.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for LLM_BACKEND=anthropic")
        return await _call_anthropic(config, user)
    raise LLMError(f"unknown backend {config.backend!r}")


async def _call_ollama(config: LLMConfig, user: str) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {
            "temperature": config.temperature,
            "top_p": 0.9,
            "num_ctx": 4096,
            "num_predict": config.num_predict,
        },
    }
    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        try:
            resp = await client.post(config.ollama_url, json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc
    if resp.status_code != 200:
        raise LLMError(
            f"ollama returned {resp.status_code}: {resp.text[:200]}"
        )
    obj = resp.json()
    try:
        content = obj["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise LLMError(f"ollama response missing message.content: {obj!r}") from exc
    return _lenient_parse(content)


async def _call_openai(config: LLMConfig, user: str) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": config.temperature,
        "max_tokens": config.num_predict,
    }
    headers = {
        "Authorization": f"Bearer {config.openai_api_key}",
        "Content-Type": "application/json",
    }
    url = config.openai_base_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"openai request failed: {exc}") from exc
    if resp.status_code != 200:
        raise LLMError(
            f"openai returned {resp.status_code}: {resp.text[:200]}"
        )
    obj = resp.json()
    try:
        content = obj["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"openai response shape: {obj!r}") from exc
    return _lenient_parse(content)


async def _call_anthropic(config: LLMConfig, user: str) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": config.num_predict,
        "temperature": config.temperature,
    }
    headers = {
        "x-api-key": config.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    url = "https://api.anthropic.com/v1/messages"
    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic request failed: {exc}") from exc
    if resp.status_code != 200:
        raise LLMError(
            f"anthropic returned {resp.status_code}: {resp.text[:200]}"
        )
    obj = resp.json()
    try:
        # Anthropic returns content as a list of blocks; we expect one text block.
        parts = obj["content"]
        text = "".join(b.get("text", "") for b in parts if b.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise LLMError(f"anthropic response shape: {obj!r}") from exc
    return _lenient_parse(text)
