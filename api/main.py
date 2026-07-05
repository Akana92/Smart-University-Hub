"""
FastAPI-бэкенд движка A (RAG-ассистент, ТЗ §4). Тонкий слой над generation.RagPipeline.
Эндпоинты:
  GET  /healthz    — статус
  POST /v1/chat    — {question, category?, top_k?} → ответ + цитаты + логирование запроса

Запуск (из корня; нужен docker+ключ):
  uvicorn api.main:app --reload      →  http://127.0.0.1:8000/docs
"""
import os
import sys
import time
import uuid
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fastapi import Depends, FastAPI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from core.query_log import log_query  # noqa: E402
from generation.pipeline import RagPipeline  # noqa: E402
from providers.embedding import get_embedder  # noqa: E402
from providers.llm import get_llm  # noqa: E402
from retrieval.stores import PgVectorHybridStore, SqliteHybridStore  # noqa: E402

app = FastAPI(title="Smart University — RAG Assistant (движок A)", version="1.0.0",
              description="RAG-ассистент студенческого офиса. Ответы только из документов вуза, с цитатами.")

TENANT = "kbtu"


@lru_cache
def get_pipeline() -> RagPipeline:
    """Строится один раз (lru_cache). Тесты подменяют через dependency_overrides."""
    cfg = yaml.safe_load(open(os.path.join(ROOT, "configs", "kbtu.yaml"), encoding="utf-8"))
    store = (PgVectorHybridStore() if os.environ.get("DATABASE_URL", "").startswith("postgres")
             else SqliteHybridStore(os.path.join(ROOT, "data", cfg["tenant_id"], "index.db")))
    return RagPipeline(store, get_embedder("openai"), get_llm("openai"), tenant_id=cfg["tenant_id"])


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    category: str | None = Field(None, description="student | abiturient | calendar")
    top_k: int = Field(5, ge=1, le=20)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "engine": "A (RAG)", "tenant": TENANT}


@app.post("/v1/chat")
def chat(req: ChatRequest, pipe: RagPipeline = Depends(get_pipeline)):
    rid = uuid.uuid4().hex[:12]
    cats = [req.category] if req.category else None
    t0 = time.perf_counter()
    res = pipe.answer(req.question, categories=cats)
    latency_ms = round((time.perf_counter() - t0) * 1000)

    log_query({
        "request_id": rid, "tenant": TENANT, "question": req.question, "category": req.category,
        "refused": res["refused"], "reason": res.get("reason"), "chunks_used": res.get("chunks_used"),
        "retrieved": res.get("retrieved"), "answer": res["answer"], "citations": res["citations"],
        "latency_ms": latency_ms, "tokens": res.get("tokens"),
    })
    return {"request_id": rid, "answer": res["answer"], "citations": res["citations"],
            "refused": res["refused"], "chunks_used": res.get("chunks_used"),
            "latency_ms": latency_ms, "tokens": res.get("tokens")}
