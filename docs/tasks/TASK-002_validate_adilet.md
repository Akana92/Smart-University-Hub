# TASK-002 — `validate.py`: сверка с adilet + отчёт качества данных

**Цель.** Выборочно сверить данные агрегатора (univision) с официальным приказом об объёмах грантов и выпустить машинный отчёт. Это основа честности продукта: снимает статус «непроверенный агрегатор». Reporting-only: расхождения ПОМЕЧАЮТСЯ, запуск не блокируют (план Б docs/02 §4.П1).

**Связанный пункт ТЗ:** DR-3, §12 (бейджи), §18 (метрика ≥95% совпадения объёмов); арх. A2 (docs/04 §5).

**Контекст.**
- Официальный источник: приказ МНВО РК **G24HN000193** на adilet.zan.kz — объёмы грантов по ГОП на 2024-2027, машиночитаем (HTML-таблицы / DOCX). URL: `https://adilet.zan.kz/rus/docs/G24HN000193`. Парсинг: `pandas.read_html` или bs4; если отдаёт DOCX — `python-docx` (добавить в requirements при необходимости).
- Наши данные: `data/grant_scores.db` → `SELECT gop_code, SUM(grants_count) FROM passing_scores WHERE metric='passing' AND quota_type='general' AND year=? GROUP BY gop_code` — сумма мест по вузам ≈ национальный объём ГОП (не 1:1: у нас 84 вуза из всех → наша сумма ≤ adilet; verdict-логика: `univision_sum <= adilet_total` = `plausible`, `>` = `conflict`).
- Дубли квот: подсчёт по **натуральному ключу** `(univ_id, gop_code, year, quota_type, metric)` — ключ ЛОГИЧЕСКИЙ, в схеме SQLite он НЕ enforced (в `passing_scores` только autoincrement-PK; не ищи constraint). **Эталонный SQL:** `SELECT univ_id,gop_code,year,quota_type,metric,COUNT(*) n FROM passing_scores GROUP BY 1,2,3,4,5 HAVING n>1`. Считаем **группы-конфликты** (ожидаемо 179 на данных 2025). Только посчитать и перечислить (фикс скрейпера = RB-201, НЕ эта задача).

**Границы.** Новый скрипт + отчёт + тест. Скрейперы, recommend.py, схему БД НЕ менять (запись `validation`-таблицы — опционально, можно ограничиться JSON-отчётом).

**Запрещено менять:** scrape_*.py, recommend.py, build_db.py (кроме опц. добавления таблицы `validation` отдельной функцией), консервация §9 ТЗ, P2/P3-области.

**Файлы можно менять/создавать:** `poc/grant-recommender/validate.py` (новый), `poc/grant-recommender/data/validation_report.json` (генерируется), `tests/test_validate.py` (новый, на фикстуре — без сети), `poc/grant-recommender/README.md`, `requirements.txt` (если нужен python-docx — с пином версии).

**Ожидаемый результат.** `python validate.py --year 2025` → `data/validation_report.json`.

**Критерии приёмки.**
1. Отчёт содержит по каждому сверенному ГОП: `{gop_code, year, adilet_total, univision_sum, delta, verdict(plausible|conflict|no_adilet_data)}`; покрытие ≥ топ-20 ГОП по числу грантов.
2. Блок `duplicates`: общее число конфликтующих дублей + список ключей (точное число — из данных, ~179).
3. Скрипт завершает exit 0 даже при конфликтах (reporting-only); summary печатается в stdout.
4. Сетевая часть вежливая (UA, таймаут, 1 повтор); при недоступности adilet — отчёт с `no_adilet_data` и exit 0, НЕ падение.

**Тесты.** `tests/test_validate.py` на фикстурных данных (мини-БД + замоканный adilet-parse): verdict-логика 3 случая; подсчёт дублей на синтетике = известному числу.

**Definition of Done.** Критерии 1–4; отчёт на реальных данных 2025 сгенерирован и закоммичен; `pytest` зелёный; коммит `TASK-002: ...`.

**Как проверить.** Запустить на реальной БД; открыть отчёт; сверить 2–3 ГОП глазами с adilet-страницей (B057 ИТ: adilet_total=5425 — опорное число из docs/03-strategy §3, зафиксированное на 2026-07; **приказ могли обновить — сверяйся с текущей страницей adilet, а не слепо с этим числом**).

**Документы обновить:** галочка §19.2 launch-checklist; docs/05 TASK-002; если найдены conflicts — задача на бейджи уходит в TASK-005 (передать список).

**Обязанности исполнителя:** изменённые файлы; что изменено; тесты с выводом; непроверенное; сверка с roadmap перед следующей задачей.
