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
from dotenv import load_dotenv  # noqa: E402
from providers.embedding import get_embedder  # noqa: E402
from retrieval.stores import PgVectorHybridStore, SqliteHybridStore  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))  # OPENAI_API_KEY, DATABASE_URL, EMBED_PROFILE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--profile", default="local", help="local | openai")
    ap.add_argument("--store", default="sqlite", choices=["sqlite", "pgvector"])
    args = ap.parse_args()

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    base = os.path.join(ROOT, "data", tenant)
    files = sorted(glob.glob(os.path.join(base, "chunks*.jsonl")))
    records = [json.loads(line) for f in files for line in open(f, encoding="utf-8")]
    if not records:
        print("Нет чанков — сначала ingest."); sys.exit(1)
    print(f"Чанков: {len(records)} из {len(files)} файлов ({', '.join(os.path.basename(f) for f in files)})")

    import numpy as np
    print(f"Загружаю эмбеддер (profile={args.profile})…")
    emb = get_embedder(args.profile)
    print(f"Эмбеддер: {emb.name}, dim={emb.dim}")
    # кэш эмбеддингов: защищает бюджет API на повторных прогонах
    cache = os.path.join(base, f"emb_{args.profile}_{emb.dim}.npy")
    arr = np.load(cache) if os.path.exists(cache) else None
    if arr is not None and arr.shape[0] == len(records):
        vecs = arr.tolist()
        print(f"Эмбеддинги ИЗ КЭША (без вызова API): {os.path.basename(cache)}")
    else:
        print("Считаю эмбеддинги через API…")
        vecs = emb.embed_documents([r["text"] for r in records])
        np.save(cache, np.asarray(vecs, dtype=np.float32))
        print(f"Эмбеддинги посчитаны и закэшированы: {os.path.basename(cache)}")

    if args.store == "pgvector":
        store = PgVectorHybridStore()
        target = os.environ.get("DATABASE_URL", "").rsplit("@", 1)[-1]
    else:
        target = os.path.join(base, "index.db")
        store = SqliteHybridStore(target)
    store.init_schema(emb.dim)
    store.add(records, vecs)
    print(f"Готово: проиндексировано {len(records)} чанков → {args.store}:{target} "
          f"(dim={emb.dim}, эмбеддер={emb.name})")


if __name__ == "__main__":
    main()
