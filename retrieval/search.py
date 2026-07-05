"""
Гибридный поиск по индексу движка A (этап 2): вопрос → dense + BM25 → RRF → top_k с ЦИТАТАМИ.
Цитаты строятся ИЗ метаданных чанка (§9.4), не из текста модели.

    python retrieval/search.py --config configs/kbtu.yaml --demo
    python retrieval/search.py --config configs/kbtu.yaml -q "Как рассчитывается GPA?" --category student
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from providers.embedding import get_embedder  # noqa: E402
from retrieval.stores import PgVectorHybridStore, SqliteHybridStore  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

DEMO = [
    ("Можно ли пересдать экзамен, если получил FX?", ["student"]),
    ("Как рассчитывается GPA?", ["student"]),
    ("Какие документы нужны для поступления на бакалавриат?", ["abiturient"]),
    ("Когда начинается экзаменационная сессия осенью?", ["calendar"]),
]


def citation(r):
    bits = [r.get("standard_code") or r.get("source"), f"стр. {r.get('page_number')}"]
    if r.get("section_title"):
        bits.append(r["section_title"][:60])
    return " · ".join(str(b) for b in bits if b)


def render(query, results):
    out = [f"\n{'=' * 70}", f"❓ {query}", "=" * 70]
    if not results:
        out.append("  (ничего не найдено)")
        return "\n".join(out)
    for i, r in enumerate(results, 1):
        snip = " ".join(r["text"].split())[:180]
        out.append(f"\n[{i}] score={float(r.get('_score') or 0):.4f}  📎 {citation(r)}  [{r.get('content_type')}]")
        out.append(f"    {snip}…")
        out.append(f"    🔗 {r.get('source_url')}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--profile", default="local")
    ap.add_argument("-q", "--query", default=None)
    ap.add_argument("--category", default=None, help="фильтр: student|abiturient|calendar")
    ap.add_argument("--top_k", type=int, default=5)
    ap.add_argument("--store", default="sqlite", choices=["sqlite", "pgvector"])
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    store = (PgVectorHybridStore() if args.store == "pgvector"
             else SqliteHybridStore(os.path.join(ROOT, "data", tenant, "index.db")))
    emb = get_embedder(args.profile)

    queries = DEMO if (args.demo or not args.query) else [(args.query, [args.category] if args.category else None)]
    blocks = []
    for q, cats in queries:
        qv = emb.embed_query(q)
        res = store.search(qv, q, tenant_id=tenant, top_k=args.top_k, categories=cats)
        blocks.append(render(q, res))
    text = "\n".join(blocks) + "\n"
    print(text)
    with open(os.path.join(ROOT, "data", tenant, "search_demo.txt"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
