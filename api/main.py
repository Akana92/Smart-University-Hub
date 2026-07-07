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
from fastapi import Depends, FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from core import faq as faq_store  # noqa: E402  (клик-слой FAQ, Слой 1)
from core import lang as lang_util  # noqa: E402  (детект языка сообщения, 0 токенов, TASK-030)
from core import recommender  # noqa: E402  (движок B: адаптер + детерминированный парсер интента)
from core import universities as uni_registry  # noqa: E402  (реестр вузов, раздел «Университеты»)
from core import query_log  # noqa: E402  (чтение/агрегация лога для админки, TASK-031)
from core.query_log import log_query  # noqa: E402
from generation.pipeline import RagPipeline  # noqa: E402
from providers.embedding import get_embedder  # noqa: E402
from providers.llm import get_llm  # noqa: E402
from retrieval.stores import PgVectorHybridStore, SqliteHybridStore  # noqa: E402

app = FastAPI(title="Smart University — единый бэкенд (движки A+B)", version="1.1.0",
              description="Единый вход (TASK-018, ADR-021): /v1/ask роутит интент «балл→куда» в движок B "
                          "(навигатор грантов, 0 LLM), остальное — в движок A (RAG с цитатами и отказом).")

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


UI_INDEX = os.path.join(ROOT, "ui", "web", "index.html")


@app.get("/", include_in_schema=False)
def index():
    """Интегрированный веб-UI (TASK-021): навигатор + клик-FAQ (Слой 1) + ассистент (Слой 2)."""
    return FileResponse(UI_INDEX)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "engine": "A+B (RAG + навигатор грантов)", "tenant": TENANT,
            "engine_a": "RAG live", "engine_b": "live" if recommender.available() else "unavailable"}


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


DISCLAIMER_B = ("Исторические отсечки на грант 2025 (источник — агрегатор univision, сверять с adilet). "
                "Это НЕ гарантия: проходной 2026 формируется по итогам конкурса (число грантов × сила заявителей).")

# Мягкое сообщение, если движок A недоступен (напр. БД документов не поднята) — вместо зависания/500
_ADVISOR_DOWN = {
    "ru": "Ассистент сейчас недоступен — нет связи с базой документов. Навигатор грантов и частые вопросы "
          "работают как обычно; попробуй чуть позже.",
    "kk": "Көмекші қазір қолжетімсіз — құжаттар базасымен байланыс жоқ. Грант навигаторы мен жиі қойылатын "
          "сұрақтар әдеттегідей жұмыс істейді; сәл кейінірек қайталап көр.",
    "en": "The assistant is temporarily unavailable — no connection to the document database. The grant "
          "navigator and FAQ work as usual; please try again shortly.",
}

# ─────────── Админка наблюдаемости (TASK-031): история запросов LLM «только мне» ───────────
# Защита: если задан ADMIN_TOKEN в окружении — требуем ?key=<token>; иначе (локальная разработка) открыто.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_INDEX = os.path.join(ROOT, "ui", "web", "admin.html")


def _admin_guard(key: str) -> None:
    if ADMIN_TOKEN and key != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Нужен админ-токен: добавь ?key=<ADMIN_TOKEN>")


def _db_ok() -> bool:
    """Быстрая проверка доступности БД документов (для плашки здоровья админки)."""
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn.startswith("postgres"):
        return True  # sqlite/локальный стор — всегда «доступен»
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=2) as c, c.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def _buckets(results: list[dict]) -> dict:
    b = {"pass": 0, "risk": 0, "fail": 0, "blocked": 0}
    for r in results:
        b[r["bucket"]] = b.get(r["bucket"], 0) + 1
    return b


@app.get("/v1/universities")
def universities_endpoint(lang: str = Query("ru", description="язык интерфейса: ru | kk | en")):
    """Реестр вузов платформы + живой счётчик чанков (раздел «Университеты»)."""
    lang = lang_util.normalize_lang(lang)
    counts: dict[str, int] = {}
    try:
        dsn = os.environ.get("DATABASE_URL", "")
        if dsn.startswith("postgres"):
            import psycopg
            # connect_timeout — чтобы раздел «Университеты» не висел, если БД временно недоступна:
            # счётчик чанков некритичен, реестр рендерится и без него (chunks=0)
            with psycopg.connect(dsn, connect_timeout=2) as c:
                for tid, n in c.execute("SELECT tenant_id, count(*) FROM chunks GROUP BY tenant_id").fetchall():
                    counts[tid] = n
    except Exception:
        pass
    return {"universities": uni_registry.universities(counts, lang),
            "compare_dims": uni_registry.compare_dims(lang)}


@app.get("/v1/faq")
def faq(category: str | None = Query(None, description="student | abiturient | calendar | student_life"),
        lang: str = Query("ru", description="язык карточек: ru | kk | en")):
    """Клик-слой (Слой 1, 0 LLM): статические карточки частых вопросов Q→ответ+источник."""
    lang = lang_util.normalize_lang(lang)
    cards = faq_store.faq_cards(TENANT, category, lang)
    return {"count": len(cards), "categories": faq_store.faq_categories(TENANT, lang), "cards": cards}


@app.get("/v1/recommend")
def recommend_endpoint(
    score: int = Query(..., ge=1, le=140, description="балл ЕНТ (макс 140)"),
    profile: str = Query(..., description="пара профильных предметов, напр. 'математика,физика'"),
    city: str | None = Query(None),
    budget: int | None = Query(None, description="макс. бюджет платного, тг/год"),
):
    """Движок B (Слой 1, 0 LLM): балл + профиль → программы по корзинам ✅/⚠️/❌ с провенансом (docs/03 §5)."""
    rec = recommender.recommend(score, profile, city, budget)
    if "error" in rec:
        raise HTTPException(status_code=422, detail=rec["error"])
    rec["summary"] = _buckets(rec["results"])
    rec["disclaimer"] = DISCLAIMER_B
    return rec


class Turn(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str = Field("", description="текст реплики")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    category: str | None = Field(None, description="student | abiturient | calendar | student_life (для движка A)")
    subjects: list[str] | None = Field(None, description="выбранные в навигаторе профильные предметы (fallback профиля)")
    profile: str | None = Field(None, description="запомненная клиентом пара-профиль (follow-up движка B, напр. 'математика+физика')")
    university: str | None = Field(None, description="вуз для поиска: None=по всем вузам, иначе kbtu|kaznu|nu")
    city: str | None = None
    budget: int | None = None
    history: list[Turn] | None = Field(None, description="прошлые ходы диалога (память сессии, только движок A/советник)")
    lang: str | None = Field(None, description="язык ответа; если пусто — определяется по языку вопроса")


@app.post("/v1/ask")
def ask(req: AskRequest, pipe: RagPipeline = Depends(get_pipeline)):
    """Единый вход (ADR-021): интент «балл→куда» → движок B (0 LLM); иначе → движок A (RAG, LLM-fallback)."""
    rid = uuid.uuid4().hex[:12]
    p = recommender.parse_admission_query(req.question)

    if p["is_admission_intent"]:
        # профиль: из текста вопроса (предметы/область) ИЛИ из выбранных в навигаторе предметов
        # ИЛИ из запомненного клиентом профиля (follow-up «а если 100 баллов?» — память сессии, TASK-030)
        carried = req.profile if req.profile in recommender.available_profiles() else None
        profile = p["profile"] or recommender.resolve_profile(req.subjects) or carried
        if profile:  # балл + профиль → движок B, без токенов
            rec = recommender.recommend(p["score"], profile, req.city, req.budget)
            results = rec.get("results", [])
            log_query({"request_id": rid, "tenant": TENANT, "engine": "B", "intent": "recommend",
                       "question": req.question, "score": p["score"], "profile": profile,
                       "summary": _buckets(results) if results else None, "tokens": None})
            return {"request_id": rid, "engine": "B", "intent": "recommend", "refused": False,
                    "score": p["score"], "profile": profile, "summary": _buckets(results),
                    "results": results, "disclaimer": DISCLAIMER_B}
        # балл есть, но пары предметов нет → просим уточнить (UI откроет навигатор), тоже 0 токенов
        log_query({"request_id": rid, "tenant": TENANT, "engine": "B", "intent": "need_profile",
                   "question": req.question, "score": p["score"], "tokens": None})
        return {"request_id": rid, "engine": "B", "intent": "need_profile", "refused": False,
                "score": p["score"], "subjects": p["subjects"],
                "available_profiles": recommender.available_profiles(),
                "message": "Укажите пару профильных предметов ЕНТ, чтобы подобрать программы на грант."}

    # длинный хвост → движок A (RAG, LLM) в режиме СОВЕТНИКА (продукт, docs/07 §5)
    # язык ответа — по языку сообщения (TASK-030); память сессии — прошлые ходы диалога
    cats = [req.category] if req.category else None
    lang = lang_util.normalize_lang(req.lang) if req.lang else lang_util.detect_lang(req.question)
    history = [{"role": t.role, "content": t.content} for t in (req.history or [])]
    t0 = time.perf_counter()
    try:
        res = pipe.answer(req.question, categories=cats, mode="advisor", university=req.university,
                          history=history, lang=lang)
    except Exception as e:  # напр. БД документов недоступна — не вешаем UI, отдаём понятное сообщение
        latency_ms = round((time.perf_counter() - t0) * 1000)
        log_query({"request_id": rid, "tenant": TENANT, "engine": "A", "intent": "document_qa",
                   "question": req.question, "category": req.category, "lang": lang, "refused": False,
                   "reason": "engine_a_error", "error": str(e)[:300], "latency_ms": latency_ms})
        return {"request_id": rid, "engine": "A", "intent": "document_qa", "refused": False, "error": True,
                "answer": _ADVISOR_DOWN.get(lang, _ADVISOR_DOWN["ru"]), "citations": [], "chunks_used": 0,
                "lang": lang, "latency_ms": latency_ms, "tokens": None}
    latency_ms = round((time.perf_counter() - t0) * 1000)
    log_query({"request_id": rid, "tenant": TENANT, "engine": "A", "intent": "document_qa",
               "question": req.question, "category": req.category, "lang": lang, "refused": res["refused"],
               "reason": res.get("reason"), "chunks_used": res.get("chunks_used"),
               "retrieved": res.get("retrieved"), "answer": res["answer"], "citations": res["citations"],
               "latency_ms": latency_ms, "tokens": res.get("tokens")})
    return {"request_id": rid, "engine": "A", "intent": "document_qa", "refused": res["refused"],
            "answer": res["answer"], "citations": res["citations"], "chunks_used": res.get("chunks_used"),
            "lang": lang, "latency_ms": latency_ms, "tokens": res.get("tokens")}


@app.get("/admin", include_in_schema=False)
def admin_page(key: str = Query("")):
    """Приватная админка наблюдаемости (TASK-031): история запросов LLM, чанки+скоры, здоровье."""
    _admin_guard(key)
    return FileResponse(ADMIN_INDEX)


@app.get("/v1/admin/logs")
def admin_logs(key: str = Query(""),
               limit: int = Query(200, ge=1, le=2000),
               engine: str | None = Query(None, description="A | B | chat — фильтр по движку"),
               only_issues: bool = Query(False, description="только отказы и ошибки")):
    """Последние запросы из лога (новейшие первыми): вопрос → retrieved(чанки+скоры+сниппет) → ответ."""
    _admin_guard(key)
    recs = query_log.read_recent(limit)
    if engine:
        recs = [r for r in recs if (r.get("engine") or "chat") == engine]
    if only_issues:
        recs = [r for r in recs if r.get("error") or r.get("refused")]
    return {"count": len(recs), "protected": bool(ADMIN_TOKEN), "records": recs}


@app.get("/v1/admin/stats")
def admin_stats(key: str = Query("")):
    """Сводка + плашка здоровья (БД документов, движок B) для верхней панели админки."""
    _admin_guard(key)
    agg = query_log.aggregate(query_log.read_recent(2000))
    agg["db_ok"] = _db_ok()
    agg["engine_b_ok"] = recommender.available()
    agg["protected"] = bool(ADMIN_TOKEN)
    return agg
