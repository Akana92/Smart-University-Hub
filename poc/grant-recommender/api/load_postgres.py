"""
Загрузка CSV-данных в Postgres (продовый стор движка B, docs/03 §4.4).
Требует: DATABASE_URL + `pip install "psycopg[binary]"`.

Использование:
    export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smartuni
    python api/load_postgres.py
(инфраструктуру поднять через api/docker-compose.yml)
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
CFG = os.path.join(ROOT, "config")


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Задайте DATABASE_URL (см. docstring).")
    import psycopg  # pip install "psycopg[binary]"

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(open(os.path.join(HERE, "schema_postgres.sql"), encoding="utf-8").read())
        cur.execute("TRUNCATE tuition, passing_scores, universities RESTART IDENTITY CASCADE;")

        unis = load_csv(os.path.join(DATA, "universities.csv"))
        cur.executemany(
            "INSERT INTO universities (univ_id,name,city,univ_type,is_national,admission_track,univision_id,source_url)"
            " VALUES (%(univ_id)s,%(name)s,%(city)s,%(univ_type)s,%(is_national)s,%(admission_track)s,%(univision_id)s,%(source_url)s)",
            [{**u, "is_national": str(u["is_national"]).lower() in ("true", "1")} for u in unis],
        )

        scores = load_csv(os.path.join(DATA, "passing_scores.csv"))
        cur.executemany(
            "INSERT INTO passing_scores (univ_id,gop_code,gop_name,metric,quota_type,score,grants_count,year,granularity,source_url,source_type,confidence,scraped_at)"
            " VALUES (%(univ_id)s,%(gop_code)s,%(gop_name)s,%(metric)s,%(quota_type)s,%(score)s,%(grants_count)s,%(year)s,%(granularity)s,%(source_url)s,%(source_type)s,%(confidence)s,%(scraped_at)s)"
            " ON CONFLICT DO NOTHING",
            [{**s, "grants_count": (s["grants_count"] or None)} for s in scores],
        )

        tuition = load_csv(os.path.join(CFG, "tuition_seed.csv"))
        cur.executemany(
            "INSERT INTO tuition (univ_id,tuition_min_kzt,tuition_max_kzt,tuition_year,source_url,source_type,confidence,note)"
            " VALUES (%(univ_id)s,%(tuition_min_kzt)s,%(tuition_max_kzt)s,%(tuition_year)s,%(source_url)s,%(source_type)s,%(confidence)s,%(note)s)"
            " ON CONFLICT (univ_id) DO NOTHING",
            tuition,
        )
        conn.commit()
        n = cur.execute("SELECT COUNT(*) FROM passing_scores").fetchone()[0]
        print(f"Postgres загружен: universities={len(unis)} passing_scores={n} tuition={len(tuition)}")


if __name__ == "__main__":
    main()
