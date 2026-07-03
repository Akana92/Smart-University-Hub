"""
Индексация: data/<tenant>/chunks*.jsonl → эмбеддинги → SQLite-store (data/<tenant>/index.db).
Локальный прогон движка A (этап 2). Прод — тот же код с get_store('pgvector').

    python retrieval/index_chunks.py --config configs/kbtu.yaml --profile local
"""
import argparse
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402
from providers.embedding import get_embedder  # noqa: E402
from retrieval.stores import SqliteHybridStore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--profile", default="local", help="local | openai")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    base = os.path.join(ROOT, "data", tenant)
    files = sorted(glob.glob(os.path.join(base, "chunks*.jsonl")))
    records = [json.loads(line) for f in files for line in open(f, encoding="utf-8")]
    if not records:
        print("Нет чанков — сначала ingest."); sys.exit(1)
    print(f"Чанков: {len(records)} из {len(files)} файлов ({', '.join(os.path.basename(f) for f in files)})")

    print(f"Загружаю эмбеддер (profile={args.profile})…")
    emb = get_embedder(args.profile)
    print(f"Эмбеддер: {emb.name}, dim={emb.dim}. Считаю эмбеддинги…")
    vecs = emb.embed_documents([r["text"] for r in records])

    db = os.path.join(base, "index.db")
    store = SqliteHybridStore(db)
    store.init_schema(emb.dim)
    store.add(records, vecs)
    print(f"Готово: проиндексировано {len(records)} чанков → {db} (dim={emb.dim}, эмбеддер={emb.name})")


if __name__ == "__main__":
    main()
