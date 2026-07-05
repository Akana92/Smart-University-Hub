"""
Инвариант §2.4 на прод-сторе PgVectorHybridStore (TASK-010).
Требует запущенный Postgres+pgvector (docker compose up -d) и DATABASE_URL.
Без БД тест SKIP (в CI без docker не падает) — но при живой БД гоняется реально.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:  # .env → DATABASE_URL
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

BASE_DSN = os.environ.get("DATABASE_URL", "")
# отдельная БД, чтобы НЕ затирать боевой индекс smartuni (init_schema делает DROP TABLE)
TEST_DSN = BASE_DSN.rsplit("/", 1)[0] + "/smartuni_test" if BASE_DSN else ""


def _pg_available():
    if not BASE_DSN.startswith("postgres"):
        return False
    try:
        import psycopg
        with psycopg.connect(BASE_DSN, connect_timeout=3):
            return True
    except Exception:
        return False


def _ensure_test_db():
    import psycopg
    admin = BASE_DSN.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True, connect_timeout=3) as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname='smartuni_test'")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE smartuni_test")


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres/pgvector недоступен (docker compose up -d)")

DIM = 4


def _rec(cid, t, text, cat="student"):
    return {"chunk_id": cid, "tenant_id": t, "source": "d.pdf", "source_url": "http://x/d.pdf",
            "category": cat, "doc_type": "academic_policy", "standard_code": "S1", "doc_version": "2025",
            "language": "ru", "page_number": 1, "section_title": "Разд", "content_type": "text",
            "token_count": 5, "text": text}


@pytest.fixture()
def store():
    from retrieval.stores import PgVectorHybridStore
    _ensure_test_db()
    st = PgVectorHybridStore(dsn=TEST_DSN)
    st.init_schema(DIM)
    st.add(
        [_rec("a1", "uniA", "экзамен пересдача"), _rec("a2", "uniA", "стоимость", "abiturient"),
         _rec("b1", "uniB", "экзамен бета")],
        [[1, 0, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]],
    )
    return st


def test_pg_only_own_tenant(store):
    res = store.search([1, 0, 0, 0], "экзамен", tenant_id="uniA", top_k=10)
    assert res and all(r["tenant_id"] == "uniA" for r in res)


def test_pg_ghost_tenant_empty(store):
    assert store.search([1, 0, 0, 0], "экзамен документ", tenant_id="ghost", top_k=10) == []


def test_pg_category_filter(store):
    res = store.search([0, 0, 1, 0], "стоимость", tenant_id="uniA", top_k=10, categories=["abiturient"])
    assert all(r["tenant_id"] == "uniA" and r["category"] == "abiturient" for r in res)
