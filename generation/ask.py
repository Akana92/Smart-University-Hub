"""
CLI-обёртка RAG-пайплайна (ТЗ §3.3): вопрос → ответ + кликабельные источники.
Тот же RagPipeline переиспользуют API (/v1/chat) и Streamlit-UI.

    python generation/ask.py --config configs/kbtu.yaml -q "Как рассчитывается GPA?" --category student
    python generation/ask.py --config configs/kbtu.yaml --demo
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from generation.pipeline import RagPipeline  # noqa: E402
from providers.embedding import get_embedder  # noqa: E402
from providers.llm import get_llm  # noqa: E402
from retrieval.stores import PgVectorHybridStore, SqliteHybridStore  # noqa: E402

DEMO = [
    ("Как рассчитывается GPA?", ["student"]),
    ("Можно ли пересдать экзамен, если получил FX?", ["student"]),
    ("Есть ли в университете бассейн и спортзал?", None),  # вне базы → ожидаем отказ
]


def build_pipeline(cfg, store_kind, emb_profile, llm_profile):
    tenant = cfg["tenant_id"]
    store = (PgVectorHybridStore() if store_kind == "pgvector"
             else SqliteHybridStore(os.path.join(ROOT, "data", tenant, "index.db")))
    return RagPipeline(store, get_embedder(emb_profile), get_llm(llm_profile), tenant_id=tenant)


def render(q, r):
    out = ["\n" + "=" * 70, f"❓ {q}", "=" * 70, r["answer"]]
    if r["citations"]:
        out.append("\n📚 Источники:")
        for c in r["citations"]:
            pg = f" · стр. {c['page']}" if c.get("page") else ""  # веб-страницы без номера
            sec = f" · {c['section']}" if c.get("section") else ""
            out.append(f"  [{c['n']}] {c['label']}{pg}{sec}\n      🔗 {c['url']}")
    else:
        out.append(f"\n(без источников · {r['reason']})")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("-q", "--query")
    ap.add_argument("--category")
    ap.add_argument("--store", default="pgvector", choices=["sqlite", "pgvector"])
    ap.add_argument("--emb", default="openai")
    ap.add_argument("--llm", default="openai")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    pipe = build_pipeline(cfg, args.store, args.emb, args.llm)

    qs = DEMO if (args.demo or not args.query) else [(args.query, [args.category] if args.category else None)]
    for q, cats in qs:
        print(render(q, pipe.answer(q, categories=cats)))


if __name__ == "__main__":
    main()
