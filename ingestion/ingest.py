"""
Ingestion движка A: PDF (data/<tenant>/raw) → structure-aware чанки с метаданными
→ data/<tenant>/chunks.jsonl + ingest_report.json  (docs/00 §7).

Пайплайн на документ:
  1. Извлечение page-aware Markdown (pymupdf4llm, page_chunks=True) — знаем номер страницы.
  2. Structure-aware чанкинг: разрез по заголовкам (# ..), ТАБЛИЦА = атомарный чанк
     (инвариант §2.8), крупный текст режется token-window'ом ~target с overlap.
  3. Обогащение метаданными (§6.1): chunk_id, tenant_id, source(+url), category, doc_type,
     standard_code, doc_version, page_number, section_title, heading_path, content_type,
     char offsets, token_count, provenance (fetch_timestamp, file_hash).
Сканы (scanned:true) пропускаются с пометкой needs_ocr — не выдумываем текст.

Использование:
    python ingestion/ingest.py --config configs/kbtu.yaml
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

import tiktoken
import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
NOISE_TAGS = re.compile(r"</?(mark|u|sup|sub|b|strong|em|i)\b[^>]*>", re.IGNORECASE)


def strip_noise(s):
    # убираем инлайн HTML-мусор парсера (<mark>,<u>,<sup>…), сохраняя <br> (переносы в таблицах)
    return NOISE_TAGS.sub("", s)


def is_table_line(line):
    return line.count("|") >= 2


def split_page_segments(page_md):
    """Упорядоченные сегменты страницы: ('heading',level,title) | ('table',text) | ('text',text)."""
    lines = page_md.split("\n")
    segs, buf, i = [], [], 0

    def flush():
        if buf:
            segs.append(("text", "\n".join(buf)))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        m = HEADING_RE.match(line.strip())
        if m:
            flush()
            title = strip_noise(re.sub(r"[*`]+", "", m.group(2))).strip()
            segs.append(("heading", len(m.group(1)), title))
            i += 1
        elif is_table_line(line):
            flush()
            tbl = []
            while i < len(lines) and is_table_line(lines[i]):
                tbl.append(lines[i])
                i += 1
            segs.append(("table", "\n".join(tbl)))
        else:
            buf.append(line)
            i += 1
    flush()
    return segs


def extract_pages(path):
    import pymupdf4llm
    data = pymupdf4llm.to_markdown(path, page_chunks=True, show_progress=False)
    if isinstance(data, list):
        return [d.get("text", "") for d in data]
    return [data]


def build_chunks(pages, src, prov, cfg):
    cc = cfg["chunk"]
    enc = tiktoken.get_encoding(cc["tokenizer"])
    target, maxt, overlap = cc["target_tokens"], cc["max_tokens"], cc["overlap_tokens"]
    min_tok = cc.get("min_tokens", 12)
    tenant, lang = cfg["tenant_id"], cfg.get("language", "ru")
    chunks, heading_stack, char_pos = [], [], 0

    def hpath():
        return [t for _, t in heading_stack]

    def section():
        return heading_stack[-1][1] if heading_stack else ""

    def emit(text, content_type, page_no):
        nonlocal char_pos
        text = strip_noise(text).strip()
        if not text:
            return
        tok = len(enc.encode(text))
        if content_type == "text" and tok < min_tok:
            return  # шум: повторяющиеся колонтитулы, короткие обрывки
        start = char_pos
        char_pos += len(text) + 1
        cid = hashlib.sha1(f"{tenant}|{src['file']}|{start}".encode("utf-8")).hexdigest()[:16]
        chunks.append({
            "chunk_id": cid, "tenant_id": tenant,
            "source": src["file"], "source_url": src["url"],
            "category": src["category"], "doc_type": src["doc_type"],
            "standard_code": src.get("standard_code"), "doc_version": src.get("doc_version"),
            "language": lang, "page_number": page_no,
            "section_title": section(), "heading_path": hpath(),
            "content_type": content_type, "char_start": start, "char_end": start + len(text),
            "token_count": tok,
            "fetch_timestamp": prov.get("fetch_timestamp"), "file_hash": prov.get("file_hash"),
            "text": text,
        })

    for pi, page_md in enumerate(pages):
        page_no = pi + 1
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
                emit(joined, "text", page_no)
            else:  # token-window с overlap
                step = max(1, target - overlap)
                j = 0
                while j < len(toks):
                    emit(enc.decode(toks[j:j + target]), "text", page_no)
                    j += step

        for seg in split_page_segments(page_md):
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
                emit(tbl, "table", page_no)
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
    raw = os.path.join(base, "raw")

    prov_map = {}
    dm = os.path.join(base, "download_manifest.json")
    if os.path.exists(dm):
        for r in json.load(open(dm, encoding="utf-8")):
            prov_map[r.get("file")] = r

    out_jsonl = os.path.join(base, "chunks.jsonl")
    report, total = [], 0
    with open(out_jsonl, "w", encoding="utf-8") as out:
        for src in cfg["sources"]:
            fname = src["file"]
            path = os.path.join(raw, fname)
            prov = prov_map.get(fname, {})
            if src.get("scanned"):
                report.append({"file": fname, "status": "needs_ocr", "chunks": 0,
                               "note": "скан-изображение → OCR (этап 1 пропускает)"})
                print(f"[OCR ] {fname}: скан, пропущен (нужен OCR)")
                continue
            if not os.path.exists(path):
                report.append({"file": fname, "status": "missing", "chunks": 0})
                print(f"[MISS] {fname}: нет файла (сначала download)")
                continue
            pages = extract_pages(path)
            chunks = build_chunks(pages, src, prov, cfg)
            for c in chunks:
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
            tbl = sum(1 for c in chunks if c["content_type"] == "table")
            toks = [c["token_count"] for c in chunks] or [0]
            report.append({"file": fname, "status": "ok", "pages": len(pages),
                           "chunks": len(chunks), "table_chunks": tbl, "text_chunks": len(chunks) - tbl,
                           "tokens_min": min(toks), "tokens_max": max(toks),
                           "tokens_avg": round(sum(toks) / len(toks))})
            total += len(chunks)
            print(f"[OK  ] {fname}: pages={len(pages)} chunks={len(chunks)} (таблиц={tbl}) "
                  f"ток[{min(toks)}..{max(toks)}~{round(sum(toks)/len(toks))}]")

    rep_path = os.path.join(base, "ingest_report.json")
    json.dump({"tenant": tenant, "total_chunks": total, "docs": report},
              open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = sum(1 for r in report if r["status"] == "ok")
    ocr = sum(1 for r in report if r["status"] == "needs_ocr")
    print(f"\nИтог: {total} чанков из {ok} документов ({ocr} сканов → OCR).")
    print(f"Чанки: {out_jsonl}\nОтчёт: {rep_path}")


if __name__ == "__main__":
    main()
