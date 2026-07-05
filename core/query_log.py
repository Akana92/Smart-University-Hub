"""
Структурное JSON-логирование запросов RAG (ТЗ §1 «логирование», foundation §12).
Каждый запрос → одна JSON-строка в logs/queries.jsonl: request_id, вопрос, категория,
retrieved (source/page/score), answer, citations, refused, latency_ms, tokens.
Позволяет диагностировать «missed-evidence vs ignored-evidence» и считать стоимость.
"""
import json
import logging
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_logger = logging.getLogger("smartuni.query")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    fh = logging.FileHandler(os.path.join(LOG_DIR, "queries.jsonl"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))  # чистый JSON без префиксов
    _logger.addHandler(fh)
    _logger.propagate = False


def log_query(record: dict) -> None:
    _logger.info(json.dumps(record, ensure_ascii=False))
