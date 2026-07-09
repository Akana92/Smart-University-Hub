"""
Тесты сравнения вузов советником (TASK-032) — герметичные, без БД и без OpenAI.
Детектор запроса-сравнения, справка о вузах, сбалансированный ретривал по вузам и
инъекция справки в промпт. Плюс: промпт советника больше не отфутболивает «на сайт вуза».
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import universities as U  # noqa: E402
from generation.pipeline import RagPipeline  # noqa: E402
from generation.prompts import ADVISOR_SYSTEM_PROMPT  # noqa: E402


# ── детектор сравнения (0 токенов) ──
def test_is_compare_query_keywords():
    assert U.is_compare_query("Сравни студенческую жизнь в университетах")
    assert U.is_compare_query("какой вуз лучше выбрать?")
    assert U.is_compare_query("плюсы и минусы вузов")
    assert not U.is_compare_query("Какие документы нужны для поступления?")
    assert not U.is_compare_query("Как рассчитывается GPA?")


def test_is_compare_query_two_universities():
    assert U.is_compare_query("KBTU или Назарбаев — куда идти")  # ≥2 вуза → сравнение
    assert not U.is_compare_query("расскажи про KBTU")  # один вуз — не сравнение


def test_compare_brief_covers_all_universities():
    brief = U.compare_brief()
    for name in ("KBTU", "КазНУ", "Nazarbayev University"):
        assert name in brief
    assert "Модель" in brief and U.tenant_ids() == ["kbtu", "kaznu", "nu"]


# ── вуз-фокус диалога (TASK-033): follow-up не перескакивает на другой вуз ──
def test_universities_in_text_word_boundary():
    assert U.universities_in_text("Выбираю NU") == {"nu"}
    assert U.universities_in_text("нужно подумать") == set()   # «nu» латиница ≠ «нужно» кириллица
    assert U.universities_in_text("расскажи про kaznu") == {"kaznu"}  # не ловим «nu» внутри «kaznu»
    assert U.universities_in_text("КазНУ или KBTU") == {"kaznu", "kbtu"}


def test_detect_focus_from_question():
    assert U.detect_focus_uni("какие условия в KBTU?") == "kbtu"


def test_detect_focus_from_history():
    hist = [{"role": "user", "content": "Выбираю NU, какие условия?"},
            {"role": "assistant", "content": "Nazarbayev University предлагает Foundation Year..."}]
    # текущий вопрос без вуза → берём вуз из недавней истории (NU), не перескакиваем на KBTU
    assert U.detect_focus_uni("есть информация по студенческой жизни?", hist) == "nu"


def test_detect_focus_ambiguous_is_none():
    assert U.detect_focus_uni("сравни KBTU и КазНУ") is None       # два вуза → не сужаем
    assert U.detect_focus_uni("как готовиться к ЕНТ?") is None     # ни одного → по всем


def test_uni_brief_single():
    b = U.uni_brief("nu")
    assert b and "Nazarbayev" in b and "NUET" in b
    assert U.uni_brief("nope") is None


# ── промпт советника: удержание вместо отфутболивания ──
def test_advisor_prompt_no_deflection():
    p = ADVISOR_SYSTEM_PROMPT.lower()
    assert "запрещено" in p and "на сайте" in p  # явный запрет советовать внешние сайты вузов
    assert "на платформе" in p  # вместо этого — следующий шаг на платформе
    assert "сравнение вузов" in p or "сравни" in p  # есть блок про сравнение


# ── сбалансированный ретривал + инъекция справки ──
class _Msg:
    def __init__(self, c): self.content = c


class _Resp:
    def __init__(self, c): self.message = _Msg(c); self.raw = None


class FakeLLM:
    def __init__(self): self.captured = None
    # ссылки [1][4][7] — при чередовании ретривала это чанки разных вузов (kbtu/kaznu/nu)
    def chat(self, messages): self.captured = messages; return _Resp("сравнение вузов [1] [4] [7]")


class FakeEmbedder:
    def embed_query(self, q): return [0.0]


class FakeStore:
    def search(self, qv, q, tenant_id=None, top_k=5, categories=None):
        return [{"chunk_id": f"{tenant_id}-{i}", "tenant_id": tenant_id,
                 "text": f"{tenant_id} chunk {i}", "_score": 0.5, "page_number": i,
                 "source": tenant_id} for i in range(top_k)]


def _pipe():
    return RagPipeline(FakeStore(), FakeEmbedder(), FakeLLM(), tenant_id="kbtu")


def test_balanced_retrieval_covers_all_tenants():
    p = _pipe()
    res = p.answer("сравни вузы", mode="advisor",
                   balance_tenants=["kbtu", "kaznu", "nu"], brief="СПРАВКА О ВУЗАХ: тест-справка")
    user = p.llm.captured[-1].content
    # в контексте есть материалы по ВСЕМ трём вузам (не однобоко)
    for tid in ("kbtu", "kaznu", "nu"):
        assert f"{tid} chunk" in user
    # справка инъектирована в промпт
    assert "СПРАВКА О ВУЗАХ: тест-справка" in user
    # цитаты собрались из разных вузов
    unis = {c["university"] for c in res["citations"]}
    assert unis == {"kbtu", "kaznu", "nu"}


def test_no_balance_single_search():
    p = _pipe()
    p.answer("обычный вопрос", mode="advisor", university="kbtu")  # без balance → обычный поиск
    user = p.llm.captured[-1].content
    assert "kbtu chunk" in user and "kaznu chunk" not in user  # только выбранный вуз
