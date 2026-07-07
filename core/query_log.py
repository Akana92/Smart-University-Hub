"""
Структурное JSON-логирование запросов RAG (ТЗ §1 «логирование», foundation §12).
Каждый запрос → одна JSON-строка в logs/queries.jsonl: ts, request_id, вопрос, категория,
retrieved (source/page/section/score/text), answer, citations, refused/error, latency_ms, tokens.
Позволяет диагностировать «missed-evidence vs ignored-evidence», считать стоимость и смотреть
историю в админке (TASK-031): какой чанк читала LLM, из какого документа, с каким скором.
"""
import json
import logging
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "queries.jsonl")

_logger = logging.getLogger("smartuni.query")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))  # чистый JSON без префиксов
    _logger.addHandler(fh)
    _logger.propagate = False


def log_query(record: dict) -> None:
    record.setdefault("ts", round(time.time(), 3))  # серверное время запроса (для истории в админке)
    _logger.info(json.dumps(record, ensure_ascii=False))


def read_recent(limit: int = 200, path: str | None = None) -> list[dict]:
    """Последние `limit` записей лога, новейшие первыми. Битые строки пропускаются."""
    path = path or LOG_PATH
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    out.reverse()  # новейшие первыми
    return out


def aggregate(records: list[dict]) -> dict:
    """Сводка по набору записей (для верхней панели админки)."""
    by_engine: dict[str, int] = {}
    lat, tok_total, refused, errors, answered = [], 0, 0, 0, 0
    for r in records:
        eng = r.get("engine") or "chat"  # /v1/chat (строгий) пишет без поля engine
        by_engine[eng] = by_engine.get(eng, 0) + 1
        if isinstance(r.get("latency_ms"), (int, float)):
            lat.append(r["latency_ms"])
        t = (r.get("tokens") or {}).get("total") if isinstance(r.get("tokens"), dict) else None
        if isinstance(t, (int, float)):
            tok_total += t
        if r.get("error"):
            errors += 1
        elif r.get("refused"):
            refused += 1
        elif r.get("reason") in ("answered", "advisor") or r.get("engine") == "B":
            answered += 1
    return {
        "total": len(records),
        "by_engine": by_engine,
        "answered": answered,
        "refused": refused,
        "errors": errors,
        "avg_latency_ms": round(sum(lat) / len(lat)) if lat else None,
        "tokens_total": tok_total,
    }
