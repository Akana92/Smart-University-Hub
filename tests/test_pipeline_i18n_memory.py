"""
Тесты сборки промпта советника (TASK-030) — БЕЗ БД и БЕЗ OpenAI.
Проверяют, что до LLM реально доходят: (1) языковая директива по языку сообщения,
(2) прошлые ходы диалога настоящими репликами (память сессии), (3) русский — без директивы.
FakeLLM перехватывает messages; FakeStore/FakeEmbedder заглушают retrieval.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from llama_index.core.llms import MessageRole  # noqa: E402

from generation.pipeline import RagPipeline  # noqa: E402
from generation.prompts import ADVISOR_SYSTEM_PROMPT, advisor_directive  # noqa: E402


class _Msg:
    def __init__(self, content):
        self.content = content


class _Resp:
    def __init__(self, content):
        self.message = _Msg(content)
        self.raw = None


class FakeLLM:
    def __init__(self):
        self.captured = None

    def chat(self, messages):
        self.captured = messages
        return _Resp("Жауап (қазақша).")


class FakeEmbedder:
    def embed_query(self, q):
        return [0.0]


class FakeStore:
    def search(self, qv, q, tenant_id=None, top_k=5, categories=None):
        return []  # нет контекста → советник даёт общий совет (уровень 2/3)


def _pipe():
    return RagPipeline(FakeStore(), FakeEmbedder(), FakeLLM(), tenant_id="kbtu")


def test_advisor_injects_kazakh_directive():
    p = _pipe()
    p.answer("Грантқа қалай түсуге болады?", mode="advisor", lang="kk")
    msgs = p.llm.captured
    assert msgs[0].role == MessageRole.SYSTEM and msgs[0].content == ADVISOR_SYSTEM_PROMPT
    user = msgs[-1]
    assert user.role == MessageRole.USER
    assert advisor_directive("kk") in user.content  # казахская директива дошла до модели
    assert "Грантқа" in user.content


def test_advisor_english_directive():
    p = _pipe()
    p.answer("How do I apply for a grant?", mode="advisor", lang="en")
    user = p.llm.captured[-1]
    assert advisor_directive("en") in user.content
    assert "Reply ENTIRELY in English" in user.content


def test_advisor_russian_has_no_directive():
    p = _pipe()
    p.answer("Как поступить на грант?", mode="advisor", lang="ru")
    user = p.llm.captured[-1]
    # для русского директивы нет — начинается сразу с КОНТЕКСТ
    assert advisor_directive("ru") == ""
    assert user.content.lstrip().startswith("КОНТЕКСТ")


def test_advisor_history_becomes_real_turns():
    p = _pipe()
    hist = [{"role": "user", "content": "Как считается GPA?"},
            {"role": "assistant", "content": "GPA — средневзвешенная оценка."}]
    p.answer("подскажи далее", mode="advisor", history=hist, lang="ru")
    msgs = p.llm.captured
    # system, user(hist), assistant(hist), user(current) = 4 сообщения
    assert len(msgs) == 4
    assert msgs[1].role == MessageRole.USER and "GPA" in msgs[1].content
    assert msgs[2].role == MessageRole.ASSISTANT and "средневзвешенная" in msgs[2].content
    assert msgs[3].role == MessageRole.USER and "подскажи далее" in msgs[3].content


def test_advisor_history_window_caps_at_4():
    p = _pipe()
    hist = [{"role": "user", "content": f"вопрос {i}"} for i in range(10)]
    p.answer("ещё", mode="advisor", history=hist, lang="ru")
    # system + не более 4 исторических + текущий user
    assert len(p.llm.captured) <= 1 + 4 + 1


def test_strict_mode_ignores_history_and_lang():
    # строгий режим (ТЗ) не трогаем: без контекста — дословный отказ, без вызова LLM
    p = _pipe()
    res = p.answer("вопрос вне базы", mode="strict", history=[{"role": "user", "content": "x"}], lang="kk")
    assert res["refused"] is True
    assert p.llm.captured is None  # LLM не вызывался (pre-LLM gate)
