"""
Векторные store'ы за ОДНИМ интерфейсом (docs/00 §8, ADR-016).
  SqliteHybridStore  — SQLite FTS5 (BM25) + numpy-косинус + RRF. Гонится здесь, без сервера.
  PgVectorHybridStore — Postgres + pgvector (`<=>`) + FTS (`tsvector`/`ts_rank`) + RRF в SQL. Прод.
Оба: обязательный `tenant_id`-фильтр (инвариант §2.4), опц. фильтр по category, гибрид dense+lex, RRF.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import List, Optional, Protocol

import numpy as np

RRF_K = 60  # константа Reciprocal Rank Fusion

_COLS = ["chunk_id", "tenant_id", "source", "source_url", "category", "doc_type",
         "standard_code", "doc_version", "language", "page_number", "section_title",
         "content_type", "token_count", "text"]


def _terms(q: str) -> List[str]:
    return [w for w in re.findall(r"\w+", q.lower(), re.UNICODE) if len(w) > 2]


def _rrf(*ranked_lists: List[int]) -> dict:
    scores: dict = {}
    for lst in ranked_lists:
        for rank, rid in enumerate(lst):
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (RRF_K + rank + 1)
    return scores


class VectorStore(Protocol):
    def search(self, query_vec, query_text, tenant_id, top_k=5, categories=None): ...


# ─────────────────────────── SQLite (локальный прогон) ───────────────────────────
def _pack(v): return np.asarray(v, dtype=np.float32).tobytes()
def _unpack(b): return np.frombuffer(b, dtype=np.float32)


class SqliteHybridStore:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._loaded = False

    def init_schema(self, dim: int):
        self.conn.executescript(
            """
            DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS chunks_fts; DROP TABLE IF EXISTS meta;
            CREATE TABLE chunks (
                rowid INTEGER PRIMARY KEY,
                chunk_id TEXT, tenant_id TEXT, source TEXT, source_url TEXT, category TEXT,
                doc_type TEXT, standard_code TEXT, doc_version TEXT, language TEXT,
                page_number INT, section_title TEXT, content_type TEXT, token_count INT,
                text TEXT, embedding BLOB
            );
            CREATE VIRTUAL TABLE chunks_fts USING fts5(text, tokenize='unicode61');
            CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
            """
        )
        self.conn.execute("INSERT INTO meta VALUES ('dim', ?)", (str(dim),))
        self.conn.commit()

    def add(self, records: List[dict], embeddings: List[List[float]]):
        cur = self.conn
        for r, e in zip(records, embeddings):
            row = cur.execute(
                "INSERT INTO chunks (chunk_id,tenant_id,source,source_url,category,doc_type,standard_code,"
                "doc_version,language,page_number,section_title,content_type,token_count,text,embedding) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["chunk_id"], r["tenant_id"], r["source"], r.get("source_url"), r.get("category"),
                 r.get("doc_type"), r.get("standard_code"), r.get("doc_version"), r.get("language"),
                 r.get("page_number"), r.get("section_title"), r.get("content_type"),
                 r.get("token_count"), r["text"], _pack(e)),
            )
            cur.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (row.lastrowid, r["text"]))
        cur.commit()

    def ensure_schema(self, dim: int):
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks'").fetchone():
            self.init_schema(dim)

    def delete_tenant(self, tenant_id: str):
        ids = [r[0] for r in self.conn.execute("SELECT rowid FROM chunks WHERE tenant_id=?", (tenant_id,)).fetchall()]
        self.conn.execute("DELETE FROM chunks WHERE tenant_id=?", (tenant_id,))
        self.conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        self.conn.commit()
        self._loaded = False

    def _load(self):
        rows = self.conn.execute("SELECT rowid, tenant_id, embedding FROM chunks").fetchall()
        self._ids = [r["rowid"] for r in rows]
        self._tenant = {r["rowid"]: r["tenant_id"] for r in rows}
        self._mat = np.vstack([_unpack(r["embedding"]) for r in rows]) if rows else np.zeros((0, 1), np.float32)
        self._loaded = True

    def search(self, query_vec, query_text, tenant_id, top_k=5, categories=None, k_each=20):
        if not self._loaded:
            self._load()
        # dense: чужие тенанты ИСКЛЮЧАЮТСЯ до ранжирования (инвариант §2.4).
        # Ранее чужие лишь занижались скором -1e9 и просачивались в top-k,
        # когда у своего тенанта < k_each строк (аудит 2026-07-03, P0-3).
        own_pos = [p for p, rid in enumerate(self._ids) if tenant_id is None or self._tenant[rid] == tenant_id]
        dense_ids: List[int] = []
        if own_pos:
            q = np.asarray(query_vec, dtype=np.float32)
            sims = self._mat[own_pos] @ q
            top = np.argsort(-sims)[:k_each]
            dense_ids = [self._ids[own_pos[i]] for i in top]
        # lexical (BM25 через FTS5)
        lex_ids: List[int] = []
        terms = _terms(query_text)
        if terms:
            match = " OR ".join(f'"{t}"' for t in terms)
            try:
                rows = self.conn.execute(
                    "SELECT rowid, bm25(chunks_fts) AS s FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY s LIMIT ?",
                    (match, k_each * 3),
                ).fetchall()
                lex_ids = [r["rowid"] for r in rows
                           if tenant_id is None or self._tenant.get(r["rowid"]) == tenant_id][:k_each]
            except sqlite3.OperationalError:
                lex_ids = []
        # RRF + фильтр по category + добор
        scores = _rrf(dense_ids, lex_ids)
        out = []
        for rid in sorted(scores, key=lambda r: -scores[r]):
            row = dict(self.conn.execute("SELECT * FROM chunks WHERE rowid=?", (rid,)).fetchone())
            if tenant_id is not None and row["tenant_id"] != tenant_id:  # §2.4 (None → все вузы, продукт)
                continue
            if categories and row["category"] not in categories:
                continue
            row["_score"] = round(scores[rid], 5)
            out.append(row)
            if len(out) >= top_k:
                break
        return out


# ─────────────────────────── Postgres + pgvector (прод) ───────────────────────────
class PgVectorHybridStore:
    """Прод-реализация того же интерфейса. Требует DATABASE_URL + `pip install "psycopg[binary]" pgvector`.
    Гибрид dense (`<=>`) + FTS (`ts_rank`, конфиг 'russian') + RRF одним SQL (CTE)."""

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ["DATABASE_URL"]

    def _conn(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def init_schema(self, dim: int):
        self._dim = dim
        # pgvector HNSW/IVFFlat ограничены 2000 измерениями; для 3072 (OpenAI large)
        # индексируем halfvec-каст (pgvector так и рекомендует, полная размерность в колонке остаётся).
        idx = (f"CREATE INDEX ON chunks USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops);"
               if dim > 2000 else
               "CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);")
        with self._conn() as c, c.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(f"""
                DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS store_meta;
                CREATE TABLE store_meta (k text PRIMARY KEY, v text);
                CREATE TABLE chunks (
                    rowid BIGSERIAL PRIMARY KEY,
                    chunk_id TEXT, tenant_id TEXT NOT NULL, source TEXT, source_url TEXT, category TEXT,
                    doc_type TEXT, standard_code TEXT, doc_version TEXT, language TEXT,
                    page_number INT, section_title TEXT, content_type TEXT, token_count INT,
                    text TEXT, embedding vector({dim}),
                    tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', coalesce(text,''))) STORED
                );
                {idx}
                CREATE INDEX ON chunks USING gin (tsv);
                CREATE INDEX ON chunks (tenant_id);
                INSERT INTO store_meta VALUES ('dim', '{dim}');
            """)
            c.commit()

    def ensure_schema(self, dim: int):
        """Неразрушающая инициализация: если таблица уже есть (мультивуз-индекс) — не трогаем.
        Иначе создаём с нуля. Для append новых вузов без DROP чужих (TASK-025)."""
        self._dim = dim
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT to_regclass('public.chunks')")
            if cur.fetchone()[0] is not None:
                return
        self.init_schema(dim)

    def delete_tenant(self, tenant_id: str):
        """Удалить все чанки одного вуза (идемпотентная переиндексация тенанта)."""
        with self._conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE tenant_id = %s", (tenant_id,))
            c.commit()

    def _get_dim(self) -> int:
        if getattr(self, "_dim", None) is None:
            with self._conn() as c, c.cursor() as cur:
                cur.execute("SELECT v FROM store_meta WHERE k='dim'")
                self._dim = int(cur.fetchone()[0])
        return self._dim

    def add(self, records, embeddings):
        with self._conn() as c, c.cursor() as cur:
            for r, e in zip(records, embeddings):
                cur.execute(
                    "INSERT INTO chunks (chunk_id,tenant_id,source,source_url,category,doc_type,standard_code,"
                    "doc_version,language,page_number,section_title,content_type,token_count,text,embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r["chunk_id"], r["tenant_id"], r["source"], r.get("source_url"), r.get("category"),
                     r.get("doc_type"), r.get("standard_code"), r.get("doc_version"), r.get("language"),
                     r.get("page_number"), r.get("section_title"), r.get("content_type"),
                     r.get("token_count"), r["text"], "[" + ",".join(map(str, e)) + "]"),
                )
            c.commit()

    def search(self, query_vec, query_text, tenant_id, top_k=5, categories=None, k_each=20):
        import psycopg
        dim = self._get_dim()
        vec = "[" + ",".join(map(str, query_vec)) + "]"
        # выражение расстояния должно совпадать с индексируемым (halfvec для >2000), иначе seq-scan
        dist = (f"embedding::halfvec({dim}) <=> %(vec)s::halfvec({dim})" if dim > 2000
                else "embedding <=> %(vec)s::vector")
        # tenant_id=None → поиск по ВСЕМ вузам (продукт-платформа, ADR-022); иначе фильтр по вузу
        tenant_sql = "tenant_id = %(tid)s" if tenant_id else "TRUE"
        cat_sql = "AND category = ANY(%(cats)s)" if categories else ""
        sql = f"""
        WITH params AS (SELECT plainto_tsquery('russian', %(qt)s) AS tq),
        dense AS (
            SELECT rowid, row_number() OVER (ORDER BY {dist}) AS r
            FROM chunks WHERE {tenant_sql} {cat_sql} ORDER BY {dist} LIMIT %(k)s),
        lexical AS (
            SELECT rowid, row_number() OVER (ORDER BY ts_rank(tsv, (SELECT tq FROM params)) DESC) AS r
            FROM chunks WHERE {tenant_sql} {cat_sql} AND tsv @@ (SELECT tq FROM params)
            ORDER BY ts_rank(tsv, (SELECT tq FROM params)) DESC LIMIT %(k)s),
        fused AS (
            SELECT rowid, SUM(1.0/({RRF_K}+r)) AS score FROM (
                SELECT rowid, r FROM dense UNION ALL SELECT rowid, r FROM lexical) u GROUP BY rowid)
        SELECT c.*, f.score AS _score FROM fused f JOIN chunks c USING (rowid)
        ORDER BY f.score DESC LIMIT %(top)s;
        """
        with self._conn() as c, c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, {"vec": vec, "qt": query_text, "tid": tenant_id,
                              "k": k_each, "top": top_k, "cats": categories or []})
            return cur.fetchall()


def get_store(kind: str = "sqlite", **kw) -> VectorStore:
    return PgVectorHybridStore(**kw) if kind in ("pgvector", "postgres") else SqliteHybridStore(**kw)
