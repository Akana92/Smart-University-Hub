# Smart University — платформа успешного поступления

AI-платформа, которая помогает абитуриенту поступить в вуз Казахстана: **дорожная карта за год**,
**реальные проходные баллы**, **сравнение вузов** и **AI-советник**, отвечающий по официальным
документам с цитатами. Построена на продакшен-RAG (движок A) + детерминированном навигаторе
грантов (движок B). Эталонные вузы: **KBTU, КазНУ им. аль-Фараби, Nazarbayev University**.

> **Два уровня проекта:** (1) **курсовой** — RAG-ассистент по ТЗ (ingestion → retrieval → генерация с
> guardrails → Streamlit → Ragas), сдан полностью; (2) **продукт** — пивот в монетизируемую платформу
> абитуриента (5 разделов, мультивуз, реклама-слоты). Опорные документы: [docs/00-foundation.md](docs/00-foundation.md)
> (конституция + ADR-лог), [docs/07_Applicant_Platform_Pivot.md](docs/07_Applicant_Platform_Pivot.md) (план продукта),
> [docs/08_Defense_Report.md](docs/08_Defense_Report.md) (отчёт к защите + демо-сценарий).

## Что внутри

**5 разделов (http://localhost:8000):**
- 🎯 **Гид абитуриента** — дорожная карта за год до поступления + рекламные слоты курсов (монетизация)
- 🏛️ **Университеты** — карточки KBTU / КазНУ / NU, ассистент с фильтром по выбранному вузу
- 📊 **Навигатор грантов** — балл ЕНТ + предметы → куда проходишь на грант (87 вузов, данные 2025)
- ⚖️ **Сравнить вузы** — таблица по модели/порогам/стоимости/грантам + сравнение словами через ИИ
- 🤖 **AI-советник** — любой вопрос абитуриента: факт вуза → с цитатами, общий совет → по делу, нет данных → мягко

## Архитектура: 2 движка × 2 слоя

```
Пользователь
   │
   ▼  Слой 1 — детерминированный, 0 токенов (массовый трафик)
   ├─ Навигатор грантов (движок B) — SQL по историческим отсечкам ЕНТ
   └─ Клик-FAQ — 26 готовых карточек Q→ответ+источник
   │
   ▼  Слой 2 — LLM, только «длинный хвост»
   └─ AI-советник (движок A) — гибридный RAG + gpt-4o-mini + цитаты / мягкий отказ
```

- **Движок A (RAG):** гибридный retrieval `pgvector (<=>)` dense + Postgres FTS(`russian`) BM25 + RRF в SQL;
  генерация через LlamaIndex + gpt-4o-mini (temp 0); **цитаты строятся из метаданных чанков, не из текста модели**;
  два режима — `strict` (курсовой, дословный отказ по ТЗ) и `advisor` (продуктовый советник).
- **Движок B (навигатор):** чистый SQL по 5632 проходным баллам 2025 (87 вузов); LLM не участвует →
  числа не выдумываются. Баллы подаются как **исторические + источник + «не гарантия»**.
- **Мультивуз:** один индекс pgvector, `tenant_id`=вуз (652 чанка: KBTU 586 + КазНУ 25 + NU 41). Ассистент
  ищет по всем вузам (`tenant_id=None`) или по выбранному; append-индексация добавляет вуз без сброса чужих.
- **Экономика токенов:** ~80% частых вопросов (навигатор + клик-FAQ) обслуживаются без единого токена;
  LLM тратится только на уникальные вопросы.

## Быстрый старт

```bash
pip install -r requirements.txt              # Python 3.13
cp .env.example .env                         # вписать OPENAI_API_KEY (+ DATABASE_URL)
docker compose up -d                         # Postgres+pgvector на :55432

# Индексация вузов (эмбеддинги OpenAI text-embedding-3-large, 3072):
python ingestion/ingest.py       --config configs/kbtu.yaml
python retrieval/index_chunks.py --config configs/kbtu.yaml  --profile openai --store pgvector
# доп. вузы (append, без сброса):
python ingestion/fetch_web.py    --config configs/kaznu.yaml && python ingestion/ingest_web.py --config configs/kaznu.yaml
python retrieval/index_chunks.py --config configs/kaznu.yaml --profile openai --store pgvector --append

# Запуск платформы (единый бэкенд + UI):
uvicorn api.main:app --port 8000             # → открыть http://localhost:8000

# Тесты + гейт качества (0 токенов):
python -m pytest -q                          # 45 passed
python eval/gate.py                          # PASS/FAIL метрик против baseline
```

Курсовой Streamlit-UI (демо этапа 4): `streamlit run ui/streamlit_app.py`.

## Качество (Ragas, судья ≠ генератор)

Оценка на golden set (73 вопроса) через Ragas, судья `gpt-4o` ≠ генератор `gpt-4o-mini`
([eval/ragas_report.md](eval/ragas_report.md)):

| Метрика | Значение |
|---|---|
| **Faithfulness** (нет галлюцинаций, по отвеченным) | **1.00** |
| Context precision / recall | 0.93 / 0.78 |
| Answer relevancy | 0.79 |
| **Refusal rate** (вне базы, 16/16) | **1.0** |

Регрессия защищена `eval/gate.py` (пороги в `eval/baseline.json`) + CI `.github/workflows/eval-gate.yml`.

## Стек

Python 3.13 · FastAPI · Postgres + pgvector · LlamaIndex + OpenAI gpt-4o-mini · OpenAI
text-embedding-3-large (3072, halfvec) · Ragas · один self-contained HTML/JS фронт (без сборки).

## Честность данных (инварианты)

- Ответы движка A — из документов; цитаты (`документ · стр. · раздел · URL · вуз`) — из метаданных чанков.
- Советник: общий совет по поступлению — из знаний; **конкретные числа/сроки/требования вуза — только из базы**.
- Числа движка B — только из БД; проходные — исторические 2025 + источник + «не гарантия».
- Мультивуз: `tenant_id`-фильтр (для одного вуза — изоляция; `None` — публичный поиск по всем), тест `tests/test_tenant_isolation.py`.

## Документация

`docs/00-foundation.md` — конституция + ADR-лог (001…022) · `docs/07` — план продукта ·
`docs/08` — отчёт к защите + демо-сценарий · `docs/05` — роадмап · `docs/02–03` — стратегия/ТЗ.
