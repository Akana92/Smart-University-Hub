"""
Тесты единого роутера /v1/ask (TASK-018, ADR-021) — БЕЗ LLM и БЕЗ БД баллов.
parse_admission_query — детерминированный (грузит только profile_map движка B).
Движок B (recommend) подменяется monkeypatch'ем; движок A — FakePipeline через dependency_overrides.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app, get_pipeline  # noqa: E402
from core import recommender  # noqa: E402


class FakePipeline:
    last = {}

    def answer(self, question, categories=None, mode="strict", university=None,
               history=None, lang="ru", balance_tenants=None, brief=None):
        FakePipeline.last = {"question": question, "mode": mode, "university": university,
                             "history": history, "lang": lang,
                             "balance_tenants": balance_tenants, "brief": brief}
        return {"refused": False, "answer": "GPA — средневзвешенная оценка [1].",
                "citations": [{"n": 1, "label": "51-2-25", "page": 20, "section": "GPA", "url": "http://x"}],
                "contexts": ["..."], "chunks_used": 1, "retrieved": [], "tokens": None, "reason": "answered"}


client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_pipeline():
    # Override только на время тестов ЭТОГО модуля (app общий с test_rag_api — не перетирать чужой).
    prev = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    yield
    if prev is None:
        app.dependency_overrides.pop(get_pipeline, None)
    else:
        app.dependency_overrides[get_pipeline] = prev


# ── parse_admission_query (Слой 1, 0 токенов) ──
def test_parse_score_and_valid_profile():
    p = recommender.parse_admission_query("Куда поступить со 104 баллами, физика и математика?")
    assert p["is_admission_intent"] is True
    assert p["score"] == 104
    assert p["profile"] == "математика+физика"


def test_parse_single_subject_no_pair():
    # «физики» (родит. падеж) должно распознаться как предмет «физика» (стемминг)
    p = recommender.parse_admission_query("Подскажи куда я могу поступить с 104 баллами, с профильным предметом физики")
    assert p["is_admission_intent"] is True
    assert p["score"] == 104
    assert p["subjects"] == ["физика"]
    assert p["profile"] is None  # одного предмета мало для пары-профиля


def test_parse_field_it():
    # «хочу в it» → профиль по области (математика+информатика), ассистент ответит, а не перенаправит
    p = recommender.parse_admission_query("Куда я могу пройти со 104 баллами, хочу в it")
    assert p["is_admission_intent"] is True and p["score"] == 104
    assert p["profile"] == "математика+информатика"


def test_parse_field_medicine():
    p = recommender.parse_admission_query("100 баллов, хочу в медицину")
    assert p["profile"] == "химия+биология"


def test_resolve_profile_from_subjects():
    assert recommender.resolve_profile(["математика", "физика"]) == "математика+физика"
    assert recommender.resolve_profile(["физика"]) is None


def test_parse_non_admission():
    assert recommender.parse_admission_query("Как рассчитывается GPA?")["is_admission_intent"] is False


# ── роутинг /v1/ask ──
def test_ask_routes_to_engine_b(monkeypatch):
    monkeypatch.setattr(recommender, "recommend",
                        lambda s, pr, c=None, b=None: {"results": [{"bucket": "pass"}, {"bucket": "risk"}]})
    j = client.post("/v1/ask", json={"question": "куда со 104 баллами, физика и математика"}).json()
    assert j["engine"] == "B" and j["intent"] == "recommend"
    assert j["score"] == 104 and j["profile"] == "математика+физика"
    assert j["summary"]["pass"] == 1 and j["summary"]["risk"] == 1
    assert j["refused"] is False


def test_ask_uses_client_subjects(monkeypatch):
    # предметы уже выбраны в навигаторе → ассистент использует их (не перенаправляет)
    monkeypatch.setattr(recommender, "recommend", lambda s, pr, c=None, b=None: {"results": [{"bucket": "pass"}]})
    j = client.post("/v1/ask", json={"question": "куда со 104 баллами",
                                      "subjects": ["математика", "физика"]}).json()
    assert j["engine"] == "B" and j["intent"] == "recommend" and j["profile"] == "математика+физика"


def test_ask_field_it_recommends(monkeypatch):
    monkeypatch.setattr(recommender, "recommend", lambda s, pr, c=None, b=None: {"results": [{"bucket": "pass"}]})
    j = client.post("/v1/ask", json={"question": "куда со 104 баллами хочу в it"}).json()
    assert j["engine"] == "B" and j["intent"] == "recommend" and j["profile"] == "математика+информатика"


def test_ask_need_profile():
    j = client.post("/v1/ask", json={"question": "куда я могу поступить с 104 баллами, физика"}).json()
    assert j["engine"] == "B" and j["intent"] == "need_profile"
    assert j["score"] == 104 and "available_profiles" in j


def test_ask_routes_to_engine_a():
    j = client.post("/v1/ask", json={"question": "Как рассчитывается GPA?"}).json()
    assert j["engine"] == "A" and j["intent"] == "document_qa"
    assert j["refused"] is False and "[1]" in j["answer"]


def test_ask_carries_profile_on_followup(monkeypatch):
    # follow-up «а если 100 баллов?» без предметов в тексте, но с запомненным профилем клиента → движок B
    monkeypatch.setattr(recommender, "recommend", lambda s, pr, c=None, b=None: {"results": [{"bucket": "pass"}]})
    j = client.post("/v1/ask", json={"question": "а если 100 баллов?",
                                      "profile": "математика+физика"}).json()
    assert j["engine"] == "B" and j["intent"] == "recommend"
    assert j["score"] == 100 and j["profile"] == "математика+физика"


def test_ask_advisor_receives_history_and_lang():
    # память сессии + язык: советник получает историю и определённый по сообщению язык
    hist = [{"role": "user", "content": "Как считается GPA?"},
            {"role": "assistant", "content": "GPA — это средневзвешенная оценка."}]
    client.post("/v1/ask", json={"question": "подскажи далее", "history": hist})
    assert FakePipeline.last["mode"] == "advisor"
    assert FakePipeline.last["history"] == hist
    assert FakePipeline.last["lang"] == "ru"


def test_ask_advisor_detects_kazakh():
    # казахские спец-буквы в вопросе → язык ответа kk (детектор, 0 токенов)
    client.post("/v1/ask", json={"question": "Университетке қалай түсуге болады?"})
    assert FakePipeline.last["lang"] == "kk"


def test_ask_advisor_detects_english():
    client.post("/v1/ask", json={"question": "What documents do I need to apply?"})
    assert FakePipeline.last["lang"] == "en"


def test_ask_compare_uses_balanced_retrieval_and_brief():
    # запрос-сравнение → советник получает сбалансированный ретривал по всем вузам + справку (TASK-032)
    client.post("/v1/ask", json={"question": "Сравни студенческую жизнь в вузах", "university": "kbtu"})
    assert FakePipeline.last["mode"] == "advisor"
    assert FakePipeline.last["balance_tenants"] == ["kbtu", "kaznu", "nu"]
    assert FakePipeline.last["brief"] and "KBTU" in FakePipeline.last["brief"]
    assert FakePipeline.last["university"] is None  # для сравнения фильтр по одному вузу снимаем


def test_ask_non_compare_no_balance():
    client.post("/v1/ask", json={"question": "Какие документы нужны для поступления?"})
    assert FakePipeline.last["balance_tenants"] is None and FakePipeline.last["brief"] is None


def test_ask_focus_from_history_scopes_retrieval():
    # follow-up про NU (вуз в истории) → поиск сужается на NU, ответ не перескакивает на KBTU (TASK-033)
    hist = [{"role": "user", "content": "Выбираю NU, какие условия?"},
            {"role": "assistant", "content": "Nazarbayev University предлагает Foundation Year..."}]
    client.post("/v1/ask", json={"question": "есть информация по студенческой жизни?", "history": hist})
    assert FakePipeline.last["university"] == "nu"
    assert FakePipeline.last["balance_tenants"] is None  # это не сравнение
    assert FakePipeline.last["brief"] and "Nazarbayev" in FakePipeline.last["brief"]


def test_recommend_endpoint(monkeypatch):
    monkeypatch.setattr(recommender, "recommend",
                        lambda s, pr, c=None, b=None: {"score": s, "results": [{"bucket": "pass"}]})
    j = client.get("/v1/recommend", params={"score": 100, "profile": "математика,физика"}).json()
    assert j["summary"]["pass"] == 1 and "disclaimer" in j
