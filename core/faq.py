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


def faq_cards(tenant: str = "kbtu", category: str | None = None) -> list[dict]:
    cards = load_faq(tenant).get("cards", [])
    return [c for c in cards if c.get("category") == category] if category else cards


def faq_categories(tenant: str = "kbtu") -> list[dict]:
    """Категории с числом карточек — для группировки в UI."""
    counts: dict[str, dict] = {}
    for c in load_faq(tenant).get("cards", []):
        key = c.get("category")
        counts.setdefault(key, {"category": key, "label": c.get("category_label", key), "count": 0})
        counts[key]["count"] += 1
    return list(counts.values())
