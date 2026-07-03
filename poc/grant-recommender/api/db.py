"""
Слой доступа к данным движка B.
Сейчас — SQLite (grant_scores.db). В проде — Postgres через переменную окружения DATABASE_URL
(docs/03 §4.4). Это делает движок B Postgres-готовым без переписывания эндпоинтов.
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.abspath(os.path.join(HERE, "..", "data", "grant_scores.db"))


def _backend():
    url = os.environ.get("DATABASE_URL", "")
    return "postgres" if url.startswith("postgres") else "sqlite"


def query(sql: str, params: tuple = ()):
    """Портируемый SELECT. Плейсхолдеры пишем как '?', для Postgres транслируем в '%s'."""
    if _backend() == "postgres":
        import psycopg  # ленивый импорт; pip install "psycopg[binary]"
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.replace("?", "%s"), params)
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def backend_name() -> str:
    return _backend()
