"""
Ingestion веб-страниц студенческой жизни (движок A, TASK-015 / категория student_life).

Берёт очищенные data/<tenant>/web_raw/*.md (см. fetch_web.py) и структурно чанкует
(переиспользуя split_page_segments/strip_noise из ingest.py: заголовки → секции, таблицы
атомарны, крупный текст режется token-window'ом) → data/<tenant>/chunks_student_life.jsonl.

Отличие от PDF-пути: у веб-страницы нет номера страницы → page_number=None; раздел (section_title)
берётся из ближайшего Markdown-заголовка (# / ## из Joomla-spoiler'ов). doc_type="webpage".
Провенанс (url, fetch_timestamp, file_hash) читается из web_manifest.json по slug.

    python ingestion/ingest_web.py --config configs/kbtu.yaml
"""
import argparse
import glob
import hashlib
import json
import os
import sys

import tiktoken
import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ingestion.ingest import split_page_segments, strip_noise  # noqa: E402  (переиспользуем чанкер)

CATEGORY = "student_life"


def build_web_chunks(md, src, cfg):
    cc = cfg["chunk"]
    enc = tiktoken.get_encoding(cc["tokenizer"])
    target, maxt, overlap = cc["target_tokens"], cc["max_tokens"], cc["overlap_tokens"]
    min_tok = cc.get("min_tokens", 12)
    tenant, lang = cfg["tenant_id"], cfg.get("language", "ru")
    chunks, heading_stack, char_pos = [], [], 0

    def section():
        return heading_stack[-1][1] if heading_stack else src["title"]

    def hpath():
        return [t for _, t in heading_stack]

    def emit(text, ctype):
        nonlocal char_pos
        text = strip_noise(text).strip()
        if not text:
            return
        tok = len(enc.encode(text))
        if ctype == "text" and tok < min_tok:
            return
        start = char_pos
        char_pos += len(text) + 1
        cid = hashlib.sha1(f'web|{tenant}|{src["slug"]}|{start}'.encode("utf-8")).hexdigest()[:16]
        chunks.append({
            "chunk_id": cid, "tenant_id": tenant,
            "source": src["title"], "source_url": src["url"],
            "category": CATEGORY, "doc_type": "webpage",
            "standard_code": None, "doc_version": None,
            "language": lang, "page_number": None,
            "section_title": section(), "heading_path": hpath(),
            "content_type": ctype, "char_start": start, "char_end": start + len(text),
            "token_count": tok,
            "fetch_timestamp": src.get("fetch_timestamp"), "file_hash": src.get("file_hash"),
            "text": text,
        })

    text_buf = []

    def flush_text():
        if not text_buf:
            return
        joined = "\n".join(text_buf).strip()
        text_buf.clear()
        if not joined:
            return
        toks = enc.encode(joined)
        if len(toks) <= maxt:
            emit(joined, "text")
        else:
            step = max(1, target - overlap)
            j = 0
            while j < len(toks):
                emit(enc.decode(toks[j:j + target]), "text")
                j += step

    for seg in split_page_segments(md):
        if seg[0] == "heading":
            flush_text()
            level, title = seg[1], seg[2]
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        elif seg[0] == "table":
            flush_text()
            cap = section()
            tbl = (f"[Раздел: {cap}]\n" if cap else "") + seg[1]
            emit(tbl, "table")
        else:
            text_buf.append(seg[1])
    flush_text()
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    base = os.path.join(ROOT, "data", tenant)
    web_dir = os.path.join(base, "web_raw")

    prov = {}
    mpath = os.path.join(base, "web_manifest.json")
    if os.path.exists(mpath):
        for m in json.load(open(mpath, encoding="utf-8")):
            prov[m["slug"]] = m
    # запасной провенанс из конфига (url/title), если manifest неполный
    cfg_src = {s["slug"]: s for s in cfg.get("web_sources", [])}

    out_jsonl = os.path.join(base, "chunks_student_life.jsonl")
    report, total = [], 0
    with open(out_jsonl, "w", encoding="utf-8") as out:
        for path in sorted(glob.glob(os.path.join(web_dir, "*.md"))):
            slug = os.path.splitext(os.path.basename(path))[0]
            md = open(path, encoding="utf-8").read().strip()
            if len(md) < 200:
                report.append({"slug": slug, "status": "too_short", "chunks": 0})
                print(f"[SKIP] {slug}: слишком короткая ({len(md)} симв.)")
                continue
            m = prov.get(slug, {})
            src = {"slug": slug,
                   "url": m.get("url") or cfg_src.get(slug, {}).get("url", ""),
                   "title": m.get("title") or cfg_src.get(slug, {}).get("title", slug),
                   "fetch_timestamp": m.get("fetch_timestamp"), "file_hash": m.get("file_hash")}
            chunks = build_web_chunks(md, src, cfg)
            for c in chunks:
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
            tbl = sum(1 for c in chunks if c["content_type"] == "table")
            total += len(chunks)
            report.append({"slug": slug, "status": "ok", "chunks": len(chunks), "table_chunks": tbl})
            print(f"[OK  ] {slug}: chunks={len(chunks)} (таблиц={tbl})")

    rep = os.path.join(base, "ingest_web_report.json")
    json.dump({"tenant": tenant, "category": CATEGORY, "total_chunks": total, "pages": report},
              open(rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nИтог: {total} чанков student_life из {sum(1 for r in report if r['status']=='ok')} страниц.")
    print(f"Чанки: {out_jsonl}\nОтчёт: {rep}")


if __name__ == "__main__":
    main()
