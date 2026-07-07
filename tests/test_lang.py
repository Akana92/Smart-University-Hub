"""
Тесты мультиязычности (TASK-030) — герметичные, без LLM и БД.
Детектор языка (0 токенов) + фолбэк локализации FAQ/вузов на русский, пока переводов нет.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from core import lang as lang_util  # noqa: E402

client = TestClient(app)


# ── детектор языка (детерминированный, 0 токенов) ──
def test_detect_russian():
    assert lang_util.detect_lang("Какие документы нужны для поступления?") == "ru"


def test_detect_kazakh_special_chars():
    # спец-буквы ә/қ/ң/ө/ұ/ү/һ/і есть только в казахском
    assert lang_util.detect_lang("Грантқа қалай түсуге болады?") == "kk"
    assert lang_util.detect_lang("Университетке қалай түсемін?") == "kk"


def test_detect_english():
    assert lang_util.detect_lang("How do I apply for a grant?") == "en"


def test_detect_russian_with_acronym_stays_ru():
    # латинский акроним в русском вопросе не должен переключать на en
    assert lang_util.detect_lang("Нужен ли IELTS для поступления?") == "ru"


def test_detect_empty_defaults_ru():
    assert lang_util.detect_lang("") == "ru"
    assert lang_util.detect_lang(None) == "ru"


def test_normalize_lang():
    assert lang_util.normalize_lang("kk") == "kk"
    assert lang_util.normalize_lang("EN") == "en"
    assert lang_util.normalize_lang("fr") == "ru"  # неподдерживаемый → ru
    assert lang_util.normalize_lang(None) == "ru"
    # 3-буквенные коды (ISO 639-2 / прямой вызов API)
    assert lang_util.normalize_lang("kaz") == "kk"
    assert lang_util.normalize_lang("rus") == "ru"
    assert lang_util.normalize_lang("eng") == "en"


# ── эндпоинты с ?lang= : форма ответа не меняется, фолбэк на RU ──
def test_faq_lang_param_keeps_shape():
    base = client.get("/v1/faq").json()
    kk = client.get("/v1/faq", params={"lang": "kk"}).json()
    assert kk["count"] == base["count"]  # число карточек то же
    for c in kk["cards"]:
        assert c["question"] and c["answer"]  # есть текст (перевод или RU-фолбэк)


def test_universities_lang_param_keeps_shape():
    base = client.get("/v1/universities").json()
    en = client.get("/v1/universities", params={"lang": "en"}).json()
    assert len(en["universities"]) == len(base["universities"])
    assert len(en["compare_dims"]) == len(base["compare_dims"])
    for u in en["universities"]:
        assert u["tagline"] and u["highlights"]  # перевод или RU-фолбэк
