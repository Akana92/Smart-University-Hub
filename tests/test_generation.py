"""
Тесты слоя генерации (TASK-011) — БЕЗ вызовов OpenAI и БЕЗ Postgres (FakeLLM/FakeStore).
Проверяют три рубежа анти-галлюцинации и дословность шаблона отказа из ТЗ.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from generation.pipeline import RagPipeline, build_citations, format_context  # noqa: E402
from generation.prompts import REFUSAL  # noqa: E402


class FakeEmbedder:
    dim = 4
    def embed_query(self, text):
        return [1, 0, 0, 0]


class FakeStore:
    def __init__(self, chunks):
        self._chunks = chunks
    def search(self, qv, qt, tenant_id, top_k=5, categories=None):
        return self._chunks[:top_k]


class FakeLLM:
    """Возвращает заданный ответ; считает вызовы (проверяем, что при отказе LLM НЕ дёргается)."""
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0
    def chat(self, messages, **kw):
        self.calls += 1
        return SimpleNamespace(message=SimpleNamespace(content=self.reply))


def _chunk(cid, text, page=1, sec="Раздел 9", src="51-2-25_2025.pdf", std="КС ИСМ КБТУ 51-2-25"):
    return {"chunk_id": cid, "tenant_id": "kbtu", "source": src, "source_url": f"http://kbtu/{src}",
            "category": "student", "doc_type": "academic_policy", "standard_code": std,
            "doc_version": "2025", "language": "ru", "page_number": page, "section_title": sec,
            "content_type": "text", "token_count": 20, "text": text}


CHUNKS = [_chunk("c1", "GPA считается как средневзвешенная оценка.", page=20),
          _chunk("c2", "Пересдача при FX разрешена без повторного курса.", page=19)]


def test_refusal_verbatim_matches_spec():
    # ДОСЛОВНАЯ формулировка из ТЗ — не должна меняться
    assert REFUSAL == ("К сожалению, у меня нет точной информации по этому вопросу. "
                       "Пожалуйста, обратитесь в Студенческий офис (кабинет 101)")


def test_gate_refuses_without_llm_when_no_context():
    llm = FakeLLM("не должно вызваться")
    p = RagPipeline(FakeStore([]), FakeEmbedder(), llm, tenant_id="kbtu")
    r = p.answer("Есть ли в вузе бассейн?")
    assert r["refused"] is True
    assert r["answer"] == REFUSAL
    assert r["citations"] == []
    assert llm.calls == 0, "при пустом контексте LLM дёргаться НЕ должен (рубеж 1)"


def test_answer_builds_citations_from_metadata():
    llm = FakeLLM("GPA — это средневзвешенная оценка [1].")
    p = RagPipeline(FakeStore(CHUNKS), FakeEmbedder(), llm, tenant_id="kbtu")
    r = p.answer("Как считается GPA?")
    assert r["refused"] is False
    assert llm.calls == 1
    assert len(r["citations"]) == 1  # ответ сослался только на [1]
    c = r["citations"][0]
    assert c["page"] == 20 and c["label"] == "КС ИСМ КБТУ 51-2-25" and c["url"].startswith("http")


def test_llm_refusal_is_detected_and_drops_citations():
    llm = FakeLLM(REFUSAL)  # LLM решил, что в контексте нет ответа
    p = RagPipeline(FakeStore(CHUNKS), FakeEmbedder(), llm, tenant_id="kbtu")
    r = p.answer("Сколько стоит парковка?")
    assert r["refused"] is True
    assert r["citations"] == []
    assert r["reason"] == "llm_refusal"
    assert r["answer"] == REFUSAL  # даже если LLM перефразировал — отдаём ДОСЛОВНЫЙ шаблон


def test_context_is_numbered_with_sources():
    ctx = format_context(CHUNKS)
    assert "[1]" in ctx and "[2]" in ctx
    assert "стр. 20" in ctx and "КС ИСМ КБТУ 51-2-25" in ctx


def test_citations_fallback_all_when_no_refs():
    cites = build_citations(CHUNKS, "Ответ без квадратных ссылок.")
    assert len(cites) == 2  # нет [n] в ответе → показываем все источники
