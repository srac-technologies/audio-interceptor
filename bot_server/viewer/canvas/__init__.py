"""Lifted from /home/tan_t/workspace/canvas/canvas/ (same author).

Modules are reused verbatim modulo relative-import rewrites; the LLM client
is replaced by :mod:`bot_server.viewer.llm` so we can pick between Ollama,
OpenAI, and Anthropic at runtime.
"""
