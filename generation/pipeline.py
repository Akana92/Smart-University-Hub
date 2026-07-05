"""
RAG-пайплайн генерации (ТЗ §3.3, foundation §9).
Оркестрация LlamaIndex (ChatMessage/LLM-абстракция) поверх гибридного retrieval (движок A).

Защита от галлюцинаций — три рубежа:
  1) pre-LLM confidence gate: нет релевантных чанков → ДОСЛОВНЫЙ отказ БЕЗ вызова LLM (бережёт ключ);
  2) context-only системный промпт: LLM обязан ответить шаблоном отказа, если в контексте нет ответа;
  3) цитаты строятся ТОЛЬКО из метаданных найденных чанков (source_nodes), не из текста модели.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from llama_index.core.llms import ChatMessage, MessageRole  # noqa: E402

from generation.prompts import REFUSAL, REFUSAL_MARKER, SYSTEM_PROMPT, USER_TEMPLATE  # noqa: E402


def _label(ch: dict) -> str:
    return ch.get("standard_code") or ch.get("source") or "документ"


def format_context(chunks: list[dict]) -> str:
    """Нумерованные фрагменты [1..N] с указанием источника и страницы — вход для LLM."""
    lines = []
    for i, ch in enumerate(chunks, 1):
        src = f"{_label(ch)}, стр. {ch.get('page_number')}"
        sec = f" — {ch['section_title']}" if ch.get("section_title") else ""
        lines.append(f"[{i}] (источник: {src}{sec})\n{ch.get('text', '').strip()}")
    return "\n\n".join(lines)


def build_citations(chunks: list[dict], answer: str) -> list[dict]:
    """Цитаты из метаданных. Если ответ ссылается на [n] — берём только их, иначе все."""
    used = {int(n) for n in re.findall(r"\[(\d+)\]", answer) if 1 <= int(n) <= len(chunks)}
    idxs = sorted(used) if used else range(1, len(chunks) + 1)
    cites = []
    for n in idxs:
        ch = chunks[n - 1]
        cites.append({
            "n": n, "label": _label(ch), "page": ch.get("page_number"),
            "section": ch.get("section_title"), "source": ch.get("source"),
            "url": ch.get("source_url"), "content_type": ch.get("content_type"),
        })
    return cites


def _retrieved_summary(chunks: list[dict]) -> list[dict]:
    """Компактная сводка найденных чанков (для лога: запрос→чанки+скоры→ответ, §12)."""
    return [{"n": i + 1, "source": c.get("source"), "page": c.get("page_number"),
             "section": c.get("section_title"), "content_type": c.get("content_type"),
             "score": round(float(c.get("_score") or 0), 5)} for i, c in enumerate(chunks)]


def _usage(resp) -> dict | None:
    """Извлекает токены из ответа LLM (LlamaIndex .raw.usage), если есть."""
    raw = getattr(resp, "raw", None)
    u = getattr(raw, "usage", None)
    if u is None and isinstance(raw, dict):
        u = raw.get("usage")
    if u is None:
        return None
    get = (lambda o, k: o.get(k)) if isinstance(u, dict) else (lambda o, k: getattr(o, k, None))
    return {"prompt": get(u, "prompt_tokens"), "completion": get(u, "completion_tokens"),
            "total": get(u, "total_tokens")}


class RagPipeline:
    def __init__(self, store, embedder, llm, tenant_id: str, top_k: int = 5, min_results: int = 1):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.tenant_id = tenant_id
        self.top_k = top_k
        self.min_results = min_results

    def answer(self, question: str, categories: list[str] | None = None) -> dict:
        qv = self.embedder.embed_query(question)
        chunks = self.store.search(qv, question, tenant_id=self.tenant_id,
                                   top_k=self.top_k, categories=categories)
        # Рубеж 1: pre-LLM gate — нет контекста → отказ без обращения к LLM
        if len(chunks) < self.min_results:
            return {"refused": True, "answer": REFUSAL, "citations": [], "contexts": [],
                    "chunks_used": 0, "retrieved": [], "tokens": None, "reason": "no_context"}

        # Рубеж 2: context-only генерация через LlamaIndex-LLM
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.USER,
                        content=USER_TEMPLATE.format(context=format_context(chunks), question=question)),
        ]
        resp = self.llm.chat(messages)
        answer = str(resp.message.content).strip()

        # Детекция отказа, сгенерированного LLM (в контексте не нашлось ответа)
        refused = REFUSAL_MARKER in answer
        if refused:
            answer = REFUSAL  # гарантируем ДОСЛОВНЫЙ шаблон ТЗ (LLM мог перефразировать/добавить точку)
        # Рубеж 3: цитаты только из метаданных чанков; при отказе — без цитат
        citations = [] if refused else build_citations(chunks, answer)
        return {"refused": refused, "answer": answer, "citations": citations,
                "contexts": [c.get("text", "") for c in chunks],
                "chunks_used": len(chunks), "retrieved": _retrieved_summary(chunks),
                "tokens": _usage(resp), "reason": "llm_refusal" if refused else "answered"}
