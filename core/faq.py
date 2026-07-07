"""
Клик-слой FAQ (TASK-019, ADR-021 — Слой 1). Загрузка статических карточек Q→ответ+источник
из data/<tenant>/faq.json (собираются faq/build_faq.py). Рантайм — 0 токенов: клик по карточке
отдаёт готовый ответ и кликабельный источник без обращения к LLM.
"""
import json
import os
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache
def load_faq(tenant: str = "kbtu") -> dict:
    path = os.path.join(ROOT, "data", tenant, "faq.json")
    if not os.path.exists(path):
        return {"tenant": tenant, "count": 0, "cards": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _localize(card: dict, lang: str) -> dict:
    """Подставить перевод карточки (question/answer/category_label) для языка.
    Фолбэк на русский, если перевода нет (мультиязычность добавляется постепенно, TASK-030)."""
    if lang in (None, "ru"):
        return card
    out = dict(card)
    for base in ("question", "answer", "category_label"):
        val = card.get(f"{base}_{lang}")
        if val:
            out[base] = val
    return out


def faq_cards(tenant: str = "kbtu", category: str | None = None, lang: str = "ru") -> list[dict]:
    cards = load_faq(tenant).get("cards", [])
    if category:
        cards = [c for c in cards if c.get("category") == category]
    return [_localize(c, lang) for c in cards]


def faq_categories(tenant: str = "kbtu", lang: str = "ru") -> list[dict]:
    """Категории с числом карточек — для группировки в UI (подпись — на языке lang)."""
    counts: dict[str, dict] = {}
    for c in load_faq(tenant).get("cards", []):
        key = c.get("category")
        label = c.get(f"category_label_{lang}") or c.get("category_label", key)
        counts.setdefault(key, {"category": key, "label": label, "count": 0})
        counts[key]["count"] += 1
    return list(counts.values())
