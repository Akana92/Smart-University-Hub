"""
Сборка клик-слоя FAQ (TASK-019, ADR-021 — Слой 1, 0 токенов в рантайме).

Берёт КУРИРОВАННЫЙ набор частых вопросов из уже готовых, проверенных grounded Q/A
(eval/golden_set.jsonl — ответы не выдумываются, переиспользуются), для каждого достаёт
ИСТОЧНИК ретривалом (top-1 чанк → документ + страница/раздел + URL) и пишет статические
карточки data/<tenant>/faq.json.

Смысл (экономика запуска): клик по карточке в UI = мгновенный ответ + кликабельный источник
БЕЗ вызова LLM. Массовые типовые вопросы обслуживаются бесплатно; движок A (RAG) — только на
«длинный хвост».

Разовый билд (эмбеддер нужен только для привязки источника, ~$0.001):
    python faq/build_faq.py --config configs/kbtu.yaml
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from generation.ask import build_pipeline  # noqa: E402
from generation.pipeline import _label  # noqa: E402

GOLDEN = os.path.join(ROOT, "eval", "golden_set.jsonl")

# Курированный набор частых вопросов (id из golden_set) по всем категориям.
# Ответы берутся из golden_set (grounded), источник — ретривалом при сборке.
SELECTION = [
    # студент — учёба
    "s01", "s02", "s03", "s04", "s06", "s09", "s18", "s20", "s21", "s24",
    # абитуриент
    "a01", "a02", "a05", "a07", "a08",
    # календарь
    "c01", "c02",
    # студенческая жизнь
    "sl01", "sl02", "sl04", "sl06", "sl11", "sl15", "o09", "o10", "sl13",
]

CAT_LABEL = {"student": "Студент", "abiturient": "Абитуриент",
             "calendar": "Календарь", "student_life": "Студенческая жизнь"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--store", default="pgvector", choices=["sqlite", "pgvector"])
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    golden = {json.loads(ln)["id"]: json.loads(ln)
              for ln in open(GOLDEN, encoding="utf-8") if ln.strip()}

    pipe = build_pipeline(cfg, args.store, "openai", "openai")

    cards = []
    for cid in SELECTION:
        g = golden.get(cid)
        if not g:
            print(f"[skip] нет в golden_set: {cid}", file=sys.stderr)
            continue
        q = g["question"]
        qv = pipe.embedder.embed_query(q)
        chunks = pipe.store.search(qv, q, tenant_id=tenant, top_k=1, categories=None)
        source = None
        if chunks:
            c = chunks[0]
            source = {"label": _label(c), "url": c.get("source_url"),
                      "page": c.get("page_number"), "section": c.get("section_title")}
        cat = g.get("category")
        cards.append({
            "id": cid, "category": cat, "category_label": CAT_LABEL.get(cat, cat),
            "question": q, "answer": g["ground_truth"], "source": source,
        })
        print(f"[ok] {cid:5} [{cat}] источник: {source['label'] if source else '—'}")

    out = os.path.join(ROOT, "data", tenant, "faq.json")
    json.dump({"tenant": tenant, "count": len(cards), "cards": cards},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nГотово: {len(cards)} карточек FAQ → {out}")


if __name__ == "__main__":
    main()
