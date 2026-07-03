# Retrieval движка A (Этап 2) — эмбеддинги + гибридный поиск

Реализует [docs/00-foundation.md](../docs/00-foundation.md) §8. Один интерфейс, два стора:
**локальный прогон здесь** (SQLite) и **прод** (Postgres+pgvector, ADR-016) — код общий.

## Запуск (локально, без ключа/docker)
```bash
pip install sentence-transformers easyocr tiktoken pyyaml numpy

python ingestion/ocr_calendars.py --config configs/kbtu.yaml   # OCR сканов → chunks_ocr.jsonl
python retrieval/index_chunks.py  --config configs/kbtu.yaml --profile local   # эмбеддинги → data/kbtu/index.db
python retrieval/search.py        --config configs/kbtu.yaml --demo            # гибридный поиск + цитаты
# свой вопрос:
python retrieval/search.py --config configs/kbtu.yaml -q "Как рассчитывается GPA?" --category student
```

## Что внутри
- **providers/embedding.py** — `EmbeddingProvider` (Protocol) + `LocalEmbedder` (sentence-transformers) + `OpenAIEmbedder` (прод) + `get_embedder(profile)`.
- **retrieval/stores.py** — `VectorStore` + `SqliteHybridStore` (FTS5 BM25 + numpy-косинус + RRF) + `PgVectorHybridStore` (pgvector `<=>` + `tsvector` + RRF в SQL). Оба — обязательный `tenant_id`-фильтр (§2.4), опц. `category`.
- **index_chunks.py** / **search.py** — CLI индексации и поиска.

## Как это работает (гибрид)
1. **Dense:** вопрос → эмбеддинг → косинус ко всем чанкам тенанта (нормализованные вектора).
2. **Лексика (BM25):** FTS5 `bm25()` по словам запроса — ловит коды/аббревиатуры/номера стандартов.
3. **RRF:** слияние двух ранжирований (`1/(60+rank)`), top_k.
4. **Цитаты** строятся ИЗ метаданных чанка (§9.4): `standard_code · стр. N · раздел · URL` — не из текста модели.

## Прогон (KBTU, локально)
- **535 чанков** (531 текст + 4 OCR-календаря), эмбеддер `local:paraphrase-multilingual-MiniLM-L12-v2` (384-dim), SQLite.
- Демо-вопросы возвращают верные разделы с цитатами: GPA → «9.23 Методика расчёта GPA» + таблица оценок; FX → «8.10 Оценка FX»; документы → «Приложение 1. Перечень документов»; **сессия → OCR-календарь** (даты 2025-2026). См. `data/kbtu/search_demo.txt`.

## Честно / ограничения
- **MiniLM — демо-модель** (компактная, средняя на русском). Ранжирование верное, но абсолютные RRF-скоры низкие. **Прод: OpenAI `text-embedding-3-large` (3072) или BGE-M3 (1024)** — заметно лучше семантика; переключение = `--profile openai` / `EMBED_PROFILE`, размер колонки под dim (§2.10).
- **OCR-текст календарей шумноват** (`ЖКБТУ>`, склейки), но даты извлекаются и ищутся. Для дат-таблиц прод-апгрейд — vision-LLM в structured rows (§7.2).
- **FTS5 unicode61** без стемминга (точные словоформы) — достаточно для кодов/терминов; прод FTS(`russian`) со стеммингом в pgvector.

## Прод-путь (Postgres + pgvector)
`PgVectorHybridStore` — тот же интерфейс. Поднять БД: `api/docker-compose.yml` (из POC движка B) + `CREATE EXTENSION vector`; индексировать `--profile openai` (нужен `OPENAI_API_KEY`) с `get_store('pgvector')`.

## Дальше
- **Этап 3** — генерация: `gpt-4o-mini` + context-only промпт + confidence-gate + цитаты из `source_nodes` (нужен ключ).
- **Этап 4** — Streamlit-чат → FastAPI (тонкий клиент, ADR-017).
