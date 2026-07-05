"""
Тесты клик-слоя FAQ (TASK-019, ADR-021) — герметичные: читают собранный data/kbtu/faq.json,
без LLM и БД. Проверяют целостность карточек (вопрос/ответ/категория/кликабельный источник)
и эндпоинт /v1/faq (список + фильтр по категории).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from core import faq as faq_store  # noqa: E402

client = TestClient(app)


def test_faq_data_integrity():
    cards = faq_store.faq_cards("kbtu")
    assert len(cards) >= 15  # DoD TASK-019
    for c in cards:
        assert c["question"] and c["answer"] and c["category"] and c.get("category_label")
        assert c["source"] and str(c["source"].get("url", "")).startswith("http")  # кликабельный источник


def test_faq_endpoint():
    j = client.get("/v1/faq").json()
    assert j["count"] >= 15 and len(j["cards"]) == j["count"]
    assert any(cat["category"] == "student_life" for cat in j["categories"])


def test_faq_filter_by_category():
    j = client.get("/v1/faq", params={"category": "student_life"}).json()
    assert j["count"] >= 1 and all(c["category"] == "student_life" for c in j["cards"])
