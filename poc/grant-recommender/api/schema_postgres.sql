-- Postgres-схема структурного стора движка B (docs/03 §4.4).
-- Продовый вариант SQLite-схемы из build_db.py. Загрузка — load_postgres.py.

CREATE TABLE IF NOT EXISTS universities (
    univ_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT,
    univ_type       TEXT,
    is_national     BOOLEAN,
    admission_track TEXT DEFAULT 'ent',   -- 'ent' | 'autonomous' (NU/KIMEP)
    univision_id    INTEGER,
    tenant_id       TEXT,                  -- FK к реестру тенантов §00 (NULL если вуз не RAG-клиент)
    source_url      TEXT
);

CREATE TABLE IF NOT EXISTS gop (
    gop_code         TEXT PRIMARY KEY,     -- 'B057' (канон — классификатор adilet)
    gop_name         TEXT,
    threshold        INT,                  -- пороговый (допуск)
    threshold_src    TEXT,
    profile_subjects JSONB                 -- допустимые пары профильных предметов
);

CREATE TABLE IF NOT EXISTS passing_scores (
    id            BIGSERIAL PRIMARY KEY,
    univ_id       TEXT REFERENCES universities(univ_id),
    gop_code      TEXT NOT NULL,
    gop_name      TEXT,
    metric        TEXT NOT NULL,           -- 'passing' | 'threshold'
    quota_type    TEXT NOT NULL,           -- general|rural|disability|large_family|single_parent|other
    score         INT NOT NULL,
    grants_count  INT,
    year          INT NOT NULL,
    granularity   TEXT,                    -- 'univ_gop' | 'national_gop'
    source_url    TEXT NOT NULL,
    source_type   TEXT NOT NULL,           -- 'aggregator' | 'official'
    confidence    TEXT NOT NULL,
    scraped_at    TIMESTAMPTZ NOT NULL,
    UNIQUE (univ_id, gop_code, year, quota_type, metric)
);
CREATE INDEX IF NOT EXISTS ix_ps_lookup ON passing_scores (gop_code, univ_id, year, metric, quota_type);

CREATE TABLE IF NOT EXISTS tuition (
    univ_id         TEXT PRIMARY KEY REFERENCES universities(univ_id),
    tuition_min_kzt INT,
    tuition_max_kzt INT,
    tuition_year    INT,
    source_url      TEXT,
    source_type     TEXT,
    confidence      TEXT,
    note            TEXT
);
