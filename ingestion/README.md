# Ingestion движка A (RAG по документам) — Этап 1

Config-driven пайплайн: PDF вуза → structure-aware чанки с метаданными и провенансом.
Реализует [docs/00-foundation.md](../docs/00-foundation.md) §7. Новый вуз = новый YAML, **без кода**.

## Запуск
```bash
pip install pymupdf4llm tiktoken pyyaml requests beautifulsoup4 lxml

python ingestion/download_kbtu.py --config configs/kbtu.yaml   # PDF → data/kbtu/raw/
python ingestion/ingest.py       --config configs/kbtu.yaml   # → data/kbtu/chunks.jsonl + ingest_report.json
```

## Что делает
1. **download_kbtu.py** — качает PDF по списку из конфига. SSL-aware (у kbtu неполная цепочка → фолбэк с пометкой `ssl_insecure` в провенансе). Пишет `download_manifest.json` (size, `file_hash`, `fetch_timestamp`).
2. **ingest.py**:
   - Извлечение **page-aware** Markdown (`pymupdf4llm`, `page_chunks=True`) → у каждого чанка есть `page_number` для цитат.
   - **Structure-aware чанкинг:** разрез по заголовкам (`#`), **таблица = атомарный чанк** (инвариант §2.8) с подписью `[Раздел: …]`; крупный текст режется token-window'ом ~700 ток. c overlap ~90 (§14); токенайзер `cl100k_base` (OpenAI-эмбеддинги).
   - Фильтр `min_tokens` отбрасывает колонтитулы/обрывки.
   - **Метаданные (§6.1):** `chunk_id, tenant_id, source(+url), category, doc_type, standard_code, doc_version, language, page_number, section_title, heading_path, content_type, char_start/end, token_count, fetch_timestamp, file_hash`.
   - **Сканы** (`scanned:true`, календари) помечаются `needs_ocr` и пропускаются — текст не выдумывается.

## Результат (KBTU, прогон)
- 8 PDF скачано; **6 текстовых → 531 чанк** (463 текст / 68 таблиц); 2 календаря → OCR.
- Категории: `student` 351, `abiturient` 180. Токены текста ~13–981 (таблицы атомарны, до ~1556).

## Дальше (Этап 2)
- **OCR** для календарей (Tesseract `rus`/EasyOCR или vision) → те же чанки с `content_type` дат.
- **Эмбеддинги + pgvector:** `providers/embedding.py` (OpenAI `text-embedding-3-large`, 3072) → таблица `chunks` в Postgres (нужен API-ключ + docker).
- **Гибридный retrieval:** pgvector `<=>` + Postgres FTS(`tsvector`) + RRF, `tenant_id`-фильтр (`retrieval/pgvector_store.py`).
