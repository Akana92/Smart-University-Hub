"""
Тесты админки наблюдаемости (TASK-031) — герметичные, без БД и без OpenAI.
Чтение/агрегация лога, обогащённая сводка ретривала, эндпоинты, токен-гейт и
graceful-ответ движка A при сбое (напр. БД документов недоступна).
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient  # noqa: E402

import api.main as main  # noqa: E402
from api.main import app, get_pipeline  # noqa: E402
from core import query_log  # noqa: E402
from generation.pipeline import _retrieved_summary  # noqa: E402

client = TestClient(app)


def test_read_recent_skips_bad_lines_and_orders_newest_first(tmp_path):
    p = tmp_path / "q.jsonl"
    p.write_text("\n".join([
        json.dumps({"engine": "A", "refused": False, "reason": "advisor", "latency_ms": 100, "tokens": {"total": 50}}),
        json.dumps({"engine": "B", "intent": "recommend", "latency_ms": 5}),
        json.dumps({"error": "boom", "reason": "engine_a_error"}),
        "   ", "{ not json",
    ]), encoding="utf-8")
    recs = query_log.read_recent(100, str(p))
    assert len(recs) == 3  # пустые/битые строки пропущены
    assert recs[0].get("error") == "boom"  # новейшая — первой


def test_aggregate_counts():
    recs = [
        {"engine": "A", "refused": False, "reason": "advisor", "latency_ms": 100, "tokens": {"total": 50}},
        {"engine": "A", "refused": True, "reason": "llm_refusal", "latency_ms": 80},
        {"engine": "B", "intent": "recommend", "latency_ms": 5},
        {"error": "boom", "reason": "engine_a_error"},
    ]
    agg = query_log.aggregate(recs)
    assert agg["total"] == 4
    assert agg["by_engine"]["A"] == 2 and agg["by_engine"]["B"] == 1 and agg["by_engine"]["chat"] == 1
    assert agg["refused"] == 1 and agg["errors"] == 1 and agg["answered"] == 2
    assert agg["tokens_total"] == 50 and agg["avg_latency_ms"] == round((100 + 80 + 5) / 3)


def test_retrieved_summary_has_rank_score_text():
    chunks = [{"text": "x" * 500, "_score": 0.5, "page_number": 3, "source": "doc",
               "standard_code": "KS-1", "tenant_id": "kbtu", "section_title": "S", "content_type": "text"}]
    s = _retrieved_summary(chunks)
    assert s[0]["rank"] == 1 and s[0]["score"] == 0.5
    assert s[0]["standard_code"] == "KS-1" and s[0]["university"] == "kbtu"
    assert len(s[0]["text"]) == 400  # сниппет обрезан


def test_admin_endpoints_smoke(monkeypatch):
    monkeypatch.setattr(main, "_db_ok", lambda: True)  # не ждать реальную БД
    st = client.get("/v1/admin/stats").json()
    assert {"total", "by_engine", "db_ok", "engine_b_ok"} <= set(st)
    lg = client.get("/v1/admin/logs", params={"limit": 3}).json()
    assert "records" in lg and lg["count"] <= 3


def test_admin_token_gate(monkeypatch):
    monkeypatch.setattr(main, "ADMIN_TOKEN", "secret")
    monkeypatch.setattr(main, "_db_ok", lambda: True)
    assert client.get("/v1/admin/stats").status_code == 401
    assert client.get("/v1/admin/logs").status_code == 401
    assert client.get("/v1/admin/stats", params={"key": "secret"}).status_code == 200


class _RaisingPipe:
    def answer(self, *a, **k):
        raise RuntimeError("db down")


def test_ask_graceful_engine_a_error():
    # движок A падает (напр. БД документов недоступна) → понятное сообщение + error, а не 500/зависание
    prev = app.dependency_overrides.get(get_pipeline)
    app.dependency_overrides[get_pipeline] = lambda: _RaisingPipe()
    try:
        j = client.post("/v1/ask", json={"question": "Как написать мотивационное эссе?"}).json()
        assert j["engine"] == "A" and j.get("error") is True and j["refused"] is False
        assert "недоступен" in j["answer"]  # ru soft-message
        assert j["citations"] == [] and j["chunks_used"] == 0
    finally:
        if prev is None:
            app.dependency_overrides.pop(get_pipeline, None)
        else:
            app.dependency_overrides[get_pipeline] = prev
