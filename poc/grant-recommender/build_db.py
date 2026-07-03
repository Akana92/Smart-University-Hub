"""
Строит SQLite-БД `data/grant_scores.db` из скрейпленных CSV.
Схема — SQLite-вариант структурного стора движка B (docs/03 §4.4):
  universities, passing_scores. Провенанс лежит колонками рядом с числом.
"""
import csv
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DB = os.path.join(DATA, "grant_scores.db")

SCHEMA = """
DROP TABLE IF EXISTS passing_scores;
DROP TABLE IF EXISTS tuition;
DROP TABLE IF EXISTS universities;

CREATE TABLE universities (
    univ_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT,
    univ_type       TEXT,
    is_national     INTEGER,
    admission_track TEXT,
    univision_id    INTEGER,
    source_url      TEXT
);

CREATE TABLE passing_scores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    univ_id       TEXT REFERENCES universities(univ_id),
    gop_code      TEXT NOT NULL,
    gop_name      TEXT,
    metric        TEXT NOT NULL,      -- 'passing' | 'threshold'
    quota_type    TEXT NOT NULL,      -- general | rural | disability | large_family | single_parent | other
    score         INTEGER NOT NULL,
    grants_count  INTEGER,
    year          INTEGER NOT NULL,
    granularity   TEXT,               -- 'univ_gop'
    source_url    TEXT NOT NULL,
    source_type   TEXT NOT NULL,      -- 'aggregator' | 'official'
    confidence    TEXT NOT NULL,
    scraped_at    TEXT NOT NULL
);
CREATE INDEX ix_ps_lookup ON passing_scores (gop_code, univ_id, year, metric, quota_type);

CREATE TABLE tuition (
    univ_id         TEXT PRIMARY KEY REFERENCES universities(univ_id),
    tuition_min_kzt INTEGER,
    tuition_max_kzt INTEGER,
    tuition_year    INTEGER,
    source_url      TEXT,
    source_type     TEXT,
    confidence      TEXT,
    note            TEXT
);
"""


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    unis = load_csv(os.path.join(DATA, "universities.csv"))
    con.executemany(
        "INSERT INTO universities VALUES (:univ_id,:name,:city,:univ_type,:is_national,:admission_track,:univision_id,:source_url)",
        [{**u, "is_national": 1 if str(u["is_national"]).lower() in ("true", "1") else 0} for u in unis],
    )

    scores = load_csv(os.path.join(DATA, "passing_scores.csv"))
    con.executemany(
        """INSERT INTO passing_scores
           (univ_id,gop_code,gop_name,metric,quota_type,score,grants_count,year,granularity,source_url,source_type,confidence,scraped_at)
           VALUES (:univ_id,:gop_code,:gop_name,:metric,:quota_type,:score,:grants_count,:year,:granularity,:source_url,:source_type,:confidence,:scraped_at)""",
        [{**s, "grants_count": (int(s["grants_count"]) if s["grants_count"] not in ("", "None") else None)} for s in scores],
    )
    # tuition (сид из research, config/tuition_seed.csv)
    tuition_path = os.path.join(HERE, "config", "tuition_seed.csv")
    if os.path.exists(tuition_path):
        tuition = load_csv(tuition_path)
        con.executemany(
            """INSERT OR IGNORE INTO tuition
               (univ_id,tuition_min_kzt,tuition_max_kzt,tuition_year,source_url,source_type,confidence,note)
               VALUES (:univ_id,:tuition_min_kzt,:tuition_max_kzt,:tuition_year,:source_url,:source_type,:confidence,:note)""",
            [{**t, "tuition_min_kzt": int(t["tuition_min_kzt"]), "tuition_max_kzt": int(t["tuition_max_kzt"]),
              "tuition_year": int(t["tuition_year"])} for t in tuition],
        )
    con.commit()

    # summary
    nu = con.execute("SELECT COUNT(*) FROM universities").fetchone()[0]
    ns = con.execute("SELECT COUNT(*) FROM passing_scores").fetchone()[0]
    ng = con.execute("SELECT COUNT(*) FROM passing_scores WHERE metric='passing' AND quota_type='general'").fetchone()[0]
    print(f"DB built: {DB}")
    print(f"  universities: {nu}")
    print(f"  passing_scores rows: {ns} (general-passing: {ng})")
    print("  by univ (general passing):")
    for row in con.execute(
        "SELECT u.name, COUNT(*) FROM passing_scores p JOIN universities u ON u.univ_id=p.univ_id "
        "WHERE p.metric='passing' AND p.quota_type='general' GROUP BY u.name ORDER BY 2 DESC"
    ):
        print(f"    {row[0]}: {row[1]}")
    con.close()


if __name__ == "__main__":
    main()
