"""
Смоук-тесты RAG-API движка A (TASK-012) — БЕЗ Postgres и БЕЗ OpenAI.
Пайплайн подменяется FakePipeline через dependency_overrides.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app, get_pipeline  # noqa: E402
from generation.prompts import REFUSAL  # noqa: E402


class FakePipeline:
    def answer(self, question, categories=None):
        if "бассейн" in question.lower():
            return {"refused": True, "answer": REFUSAL, "citations": [], "chunks_used": 0,
                    "retrieved": [], "tokens": None, "reason": "no_context"}
        return {"refused": False, "answer": "GPA считается так [1].",
                "citations": [{"n": 1, "label": "КС ИСМ КБТУ 51-2-25", "page": 20, "section": "9.23",
                               "source": "51-2-25_2025.pdf", "url": "http://kbtu/x.pdf", "content_type": "text"}],
                "chunks_used": 2, "retrieved": [{"n": 1, "source": "x.pdf", "page": 20, "score": 0.03}],
                "tokens": {"prompt": 100, "completion": 20, "total": 120}, "reason": "answered"}


app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
client = TestClient(app)


def test_healthz():
    r = client.get("/healthz").json()
    assert r["status"] == "ok" and r["engine"].startswith("A")


def test_chat_answer_with_citations():
    r = client.post("/v1/chat", json={"question": "Как считается GPA?", "category": "student"}).json()
    assert r["refused"] is False
    assert r["answer"] and r["citations"] and r["citations"][0]["url"].startswith("http")
    assert "request_id" in r and r["latency_ms"] >= 0 and r["tokens"]["total"] == 120


def test_chat_refusal():
    r = client.post("/v1/chat", json={"question": "Есть ли бассейн?"}).json()
    assert r["refused"] is True and r["citations"] == [] and r["answer"] == REFUSAL


def test_chat_validation_rejects_empty():
    assert client.post("/v1/chat", json={"question": ""}).status_code == 422
