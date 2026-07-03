"""
FastAPI — единый сервис ДВУХ движков (docs/03 §4.1):
  • движок B (рекомендатель грантов) — РАБОТАЕТ на реальных данных (SQLite/Postgres);
  • движок A (RAG по документам вуза) — заглушка (нужен ingestion-пайплайн, docs/00, этапы 1-3).

Запуск (из папки poc/grant-recommender):
    uvicorn api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
import os
import re
import sys

from fastapi import FastAPI, HTTPException, Query

# импорт логики движка B (recommend.py в родительской папке)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import recommend as engine_b  # noqa: E402
from api import db  # noqa: E402  (запуск как модуль: uvicorn api.main:app)

app = FastAPI(
    title="Smart University — Grant Recommender API (POC)",
    version="0.1.0",
    description="Единый вход к движку B (гранты) и движку A (RAG, заglушка). См. docs/03.",
)


@app.get("/healthz")
def healthz():
    rows = db.query("SELECT COUNT(*) AS n FROM passing_scores")
    unis = db.query("SELECT COUNT(*) AS n FROM universities")
    return {
        "status": "ok",
        "backend": db.backend_name(),
        "engine_b": "live",
        "engine_a": "stub (RAG не реализован)",
        "passing_scores_rows": rows[0]["n"],
        "universities": unis[0]["n"],
    }


@app.get("/v1/recommend")
def recommend_endpoint(
    score: int = Query(..., ge=1, le=140, description="балл ЕНТ (макс 140)"),
    profile: str = Query(..., description="пара профильных предметов через запятую, напр. 'математика,информатика'"),
    city: str | None = Query(None),
    budget: int | None = Query(None, description="макс. бюджет платного, тг/год"),
):
    """Движок B: балл + профиль -> корзины ✅/⚠️/❌ с провенансом (docs/03 §5)."""
    rec = engine_b.recommend(score, profile, city, budget)
    if "error" in rec:
        raise HTTPException(status_code=422, detail=rec["error"])
    # компактная сводка по корзинам для API-клиента
    buckets = {"pass": 0, "risk": 0, "fail": 0, "blocked": 0}
    for r in rec["results"]:
        buckets[r["bucket"]] += 1
    rec["summary"] = buckets
    rec["disclaimer"] = ("Исторические отсечки 2025 (источник — агрегатор univision, сверять с adilet). "
                         "Это НЕ гарантия: отсечка 2026 формируется по итогам конкурса.")
    return rec


@app.get("/v1/universities")
def universities():
    return db.query(
        "SELECT univ_id, name, city, univ_type, is_national FROM universities ORDER BY name"
    )


def _engine_a_stub(question: str, tenant_id):
    return {
        "engine": "A",
        "intent": "document_qa",
        "answer": ("RAG-движок по документам вуза не подключён к этому API: ingestion и retrieval "
                   "уже существуют (ingestion/, retrieval/ — pymupdf4llm→чанки→SQLite/pgvector, ADR-016/018), "
                   "но слой генерации (этап 3) и связка с API (этап 4) не реализованы — см. docs/00-foundation.md §15."),
        "tenant_id": tenant_id,
        "citations": [],
    }


@app.post("/v1/ask")
def ask(payload: dict):
    """Наивный роутер интентов (docs/03 §4.1): вопрос про баллы -> движок B, иначе -> движок A (RAG)."""
    q = (payload.get("question") or "").strip()
    tenant_id = payload.get("tenant_id")
    m = re.search(r"\b(\d{2,3})\b", q)
    looks_score = bool(m) and 1 <= int(m.group(1)) <= 140 and any(
        k in q.lower() for k in ["балл", "грант", "пройд", "поступ", "профил"]
    )
    if looks_score:
        return {
            "engine": "B",
            "intent": "recommend",
            "detected_score": int(m.group(1)),
            "note": "Вопрос про баллы -> движок B. Для точного расчёта вызовите /v1/recommend со score и profile.",
        }
    return _engine_a_stub(q, tenant_id)
