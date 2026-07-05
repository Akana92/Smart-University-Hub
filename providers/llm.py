"""
Провайдеро-агностичный слой LLM (ТЗ §4, ADR-008): OpenAI gpt-4o-mini по умолчанию,
Ollama (llama3/qwen) для полной приватности. Оркестрация — LlamaIndex (LLM-абстракция).
Смена провайдера = env LLM_PROFILE, без изменения кода генерации.
"""
from __future__ import annotations

import os


def get_llm(profile: str = "openai", model: str | None = None, temperature: float = 0.0):
    """Возвращает LlamaIndex-LLM. temp=0 — детерминизм для анти-галлюцинации."""
    profile = (os.environ.get("LLM_PROFILE") or profile).lower()
    if profile in ("ollama", "local"):
        # pip install llama-index-llms-ollama ; ollama pull qwen2.5:7b
        from llama_index.llms.ollama import Ollama
        return Ollama(model=model or "qwen2.5:7b-instruct", temperature=temperature, request_timeout=120.0)
    from llama_index.llms.openai import OpenAI  # ключ из OPENAI_API_KEY
    return OpenAI(model=model or "gpt-4o-mini", temperature=temperature)
