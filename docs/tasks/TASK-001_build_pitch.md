# TASK-001 — `build_pitch.py`: детерминированная сборка публичного артефакта

**Цель.** Замкнуть цикл обновления данных: одна команда собирает канонический `grant-navigator.html` из SQLite. Сейчас звено отсутствует (инъекция делалась ручным скриптом вне репо).

**Связанный пункт ТЗ:** DR-2 (docs/03_ §8); арх. A1 (docs/04 §5).

**Контекст.**
- Шаблон: `poc/grant-recommender/pitch/index.template.html`, плейсхолдер строка ~180: `const DATA = /*__DATA__*/;`.
- Формат `DATA` (обратная инженерия из собранного html — сохранить совместимость с JS!):
  `meta{unis, programs, year, source, generated}` · `thresholds{base, national, kw{...}}` · `profiles{ "<пара-предметов-sorted>": [keywords...] }` (ключи нормализованы: предметы lowercase, отсортированы, через `+`) · `unis[[name, city, is_national(0/1), tuition_min|0]]` · `progs[[uni_index, gop_code, gop_name, passing, grants]]`.
- Источники: `data/grant_scores.db` (только `metric='passing' AND quota_type='general' AND year=<--year>`), `config/thresholds.json`, `config/profile_map.json`, `tuition` из БД.
- **Детерминизм:** `meta.generated` = max(`scraped_at`) из выбранных данных, НЕ текущая дата — иначе критерий «байт-в-байт» невыполним.
- Канонический артефакт — ТОЛЬКО `grant-navigator.html`; `pitch/index.html` больше не производится и **удаляется из репо** (двух правд быть не должно).

**Границы задачи.** Только новый скрипт + удаление дубля + тест + README-строка. Логику JS/вёрстку шаблона НЕ менять; схему БД НЕ менять; `recommend.py` НЕ трогать.

**Запрещено менять:** `index.template.html` (кроме случая, если плейсхолдер потребует маркер конца — тогда минимальный диф с объяснением), всё из консервации §9 ТЗ (ingestion/retrieval/providers), P2/P3-области (docs/04 §5).

**Файлы, которые можно менять/создавать:**
- `poc/grant-recommender/build_pitch.py` (новый)
- `poc/grant-recommender/pitch/index.html` (удалить)
- `tests/test_build_pitch.py` (новый)
- `poc/grant-recommender/README.md` (раздел «Как запустить»)

**Ожидаемый результат.** `python build_pitch.py --year 2025` из папки POC пересобирает `pitch/grant-navigator.html`.

**Критерии приёмки.**
1. Повторный запуск на тех же данных → файл байт-в-байт идентичен (сравнить hash).
2. В `DATA.progs` — только general-passing выбранного года; `meta.year` = `--year`; счётчики `meta.unis`/`meta.programs` совпадают с SQL-подсчётом.
3. Существующий JS работает без правок: собранный html открывается, расчёт для «100 / математика+информатика» даёт непустой ✅-список (ручная проверка в браузере или node-smoke).
4. `pitch/index.html` отсутствует в репо.

**Тесты.** `tests/test_build_pitch.py`: (а) сборка проходит, html содержит `const DATA = {`; (б) `meta.year==2025`; (в) счётчики == SQL; (г) два запуска → одинаковый sha256.

**Definition of Done.** Критерии 1–4 выполнены; `pytest tests -q` полностью зелёный; коммит `TASK-001: ...`.

**Как проверить результат.** `cd poc/grant-recommender && python build_pitch.py --year 2025 && python -m pytest ../../tests/test_build_pitch.py -q`; открыть html.

**Документы обновить после выполнения:** отметить DR-2 в launch-checklist (docs/03_ §19.1 частично), галочка TASK-001 в docs/05; README POC.

**Обязанности исполнителя после задачи:** перечислить изменённые файлы; объяснить, что изменено; прогнать тесты и привести вывод; явно указать непроверенное; следующую задачу не начинать без сверки с docs/05.
