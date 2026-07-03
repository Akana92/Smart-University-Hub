# Smart University Knowledge Hub

RAG-ассистент по официальным документам вуза (движок A) + POC-рекомендатель грантов по баллу ЕНТ (движок B, расширение). Русскоязычный контент, эталонный вуз — KBTU, мультитенантная архитектура.

> **Опорные документы:** архитектура и решения — [docs/00-foundation.md](docs/00-foundation.md) (конституция, ADR-лог) · состояние по аудиту — [docs/00_Current_State_Inventory.md](docs/00_Current_State_Inventory.md) и [docs/01_Audit_Original_Spec_vs_Implementation.md](docs/01_Audit_Original_Spec_vs_Implementation.md) · стратегия платформы — [docs/03-multi-university-recommender-strategy.md](docs/03-multi-university-recommender-strategy.md).

## Статус (2026-07-03, по независимому аудиту)

| Слой | Статус |
|---|---|
| Этап 1 · Ingestion (PDF→чанки, таблицы, OCR) | ✅ работает (535 чанков KBTU), с известными оговорками |
| Этап 2 · Retrieval (гибрид dense+BM25+RRF, цитаты) | ✅ работает как демо (MiniLM-384 + SQLite); утечка тенанта исправлена, закрыта тестами |
| Этап 3 · Generation (LLM + guardrails + отказ) | ❌ не реализован |
| Этап 4 · UI (Streamlit) + API движка A | ❌ не реализован (в POC-API движок A — заглушка) |
| Этап 5 · Eval (Ragas) + логирование | ❌ не реализованы |
| Движок B · Рекомендатель грантов (POC) | ✅ 87 вузов / 5632 строки 2025, тесты PASS; источник — агрегатор univision, сверка с adilet ещё НЕ выполнена |

## Быстрый старт

```bash
pip install -r requirements.txt          # Python 3.12+ (проверено на 3.13)
cp .env.example .env                     # ключи нужны только для прод-профилей

# Движок A (RAG по документам KBTU) — работает локально, без ключей:
python ingestion/download_kbtu.py --config configs/kbtu.yaml   # 8 PDF → data/kbtu/raw
python ingestion/ingest.py        --config configs/kbtu.yaml   # → chunks.jsonl (531)
python ingestion/ocr_calendars.py --config configs/kbtu.yaml   # сканы → chunks_ocr.jsonl (4)
python retrieval/index_chunks.py  --config configs/kbtu.yaml --profile local  # → index.db
python retrieval/search.py --config configs/kbtu.yaml -q "Как рассчитывается GPA?" --category student

# Движок B (рекомендатель грантов, POC):
cd poc/grant-recommender
python recommend.py --score 100 --profile "математика,информатика"
uvicorn api.main:app --reload            # http://127.0.0.1:8000/docs

# Тесты (изоляция тенантов + POC-смоук):
python -m pytest tests -q
```

Интерактивный питч движка B: `poc/grant-recommender/pitch/grant-navigator.html`.

## Структура

```
configs/        # YAML-конфиг на вуз (новый вуз = новый YAML, без кода)
ingestion/      # PDF → Markdown → structure-aware чанки с метаданными; OCR сканов
providers/      # провайдеро-агностичные эмбеддинги (local MiniLM / OpenAI)
retrieval/      # гибридный поиск: SQLite FTS5+косинус+RRF (демо) / pgvector (прод, не прогонялся)
data/<tenant>/  # артефакты пайплайна: raw PDF, chunks.jsonl, index.db, отчёты
poc/grant-recommender/  # движок B: скрейперы, SQLite, rules-рекомендатель, FastAPI, питч
docs/           # 00-foundation (конституция) + аудит + стратегия
tests/          # pytest: инвариант изоляции тенантов + POC-смоук
```

## Честность данных (инварианты)

- Ответы движка A — только из документов, цитаты (`документ · стр. · раздел · URL`) строятся из метаданных чанков, не из текста модели.
- Числа движка B — только из БД (LLM в пайплайне нет); проходные баллы показываются как **исторические (2025) + источник + «не гарантия»**. Источник — агрегатор univision (`confidence=medium`); независимая сверка с adilet — запланирована, не выполнена.
- Мультитенантная изоляция (`tenant_id`) — обязательный фильтр, защищён `tests/test_tenant_isolation.py`.

## Известные ограничения (см. docs/01)

MiniLM-384 — демо-эмбеддер (прод: OpenAI-3072/BGE-M3, переиндексация); OCR календарей шумный, табличная структура дат повреждена (P1); 42% чанков <300 токенов (мёржинг мелких секций — P1); pgvector/OpenAI-пути написаны, но не прогонялись; логирования и eval пока нет.

## Переезд из кириллического пути (рекомендовано)

Кириллица в пути уже ломала инструменты (OpenCV/EasyOCR). Git не хранит абсолютных путей — просто перенесите папку целиком, например в `D:\projects\smart-university`, и откройте проект там. История и всё остальное сохранится.
