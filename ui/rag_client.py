"""
Чистая логика Streamlit-клиента (без импорта streamlit — тестируемо):
вызов бэкенда /v1/chat и рендер кликабельных цитат (ТЗ §3.3 — обязательны).
"""
from __future__ import annotations

import os

import requests

API_URL = os.environ.get("RAG_API_URL", "http://127.0.0.1:8000")

# подпись в UI -> значение category для API
CATEGORIES = {"Все документы": None, "Абитуриент": "abiturient",
              "Студент": "student", "Календарь": "calendar",
              "Студенческая жизнь": "student_life"}


def ask_api(question: str, category: str | None, api_url: str = API_URL, timeout: int = 90) -> dict:
    r = requests.post(f"{api_url}/v1/chat",
                      json={"question": question, "category": category}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def citations_md(citations: list[dict]) -> str:
    """Markdown-список кликабельных источников: [название документа · стр. N · раздел](url)."""
    if not citations:
        return ""
    lines = ["", "**📚 Источники:**"]
    for c in citations:
        pg = f" · стр. {c['page']}" if c.get("page") else ""  # веб-страницы (student_life) без номера
        sec = f" · {c['section']}" if c.get("section") else ""
        lines.append(f"- [{c['label']}{pg}{sec}]({c['url']})")
    return "\n".join(lines)
