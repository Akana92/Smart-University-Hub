"""
OCR сканированных источников (scanned:true в конфиге) → data/<tenant>/chunks_ocr.jsonl.
Рендер страниц PDF @300dpi (PyMuPDF) → EasyOCR (rus+en) → текст → чанки со схемой §6.1 + ocr-провенанс.
Даты сессий/каникул — высокочувствительны: помечаем ocr=true и confidence, чтобы движок отвечал осторожно.

    python ingestion/ocr_calendars.py --config configs/kbtu.yaml
"""
import argparse
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import fitz  # PyMuPDF  # noqa: E402
import numpy as np  # noqa: E402
import tiktoken  # noqa: E402
import yaml  # noqa: E402


def render_page_array(page, dpi=300):
    # numpy-массив вместо PNG-пути: OpenCV/imread в EasyOCR НЕ читает пути с кириллицей на Windows
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csRGB)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


def token_split(text, enc, target, maxt, overlap):
    toks = enc.encode(text)
    if len(toks) <= maxt:
        return [text]
    step = max(1, target - overlap)
    return [enc.decode(toks[i:i + target]) for i in range(0, len(toks), step)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    cc = cfg["chunk"]
    enc = tiktoken.get_encoding(cc["tokenizer"])
    base = os.path.join(ROOT, "data", tenant)
    raw = os.path.join(base, "raw")

    prov = {}
    dm = os.path.join(base, "download_manifest.json")
    if os.path.exists(dm):
        for r in json.load(open(dm, encoding="utf-8")):
            prov[r.get("file")] = r

    import easyocr
    print("Загружаю EasyOCR (rus+en) — первая загрузка тянет модели…")
    reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)

    scanned = [s for s in cfg["sources"] if s.get("scanned")]
    out_path = os.path.join(base, "chunks_ocr.jsonl")
    total = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for s in scanned:
            path = os.path.join(raw, s["file"])
            if not os.path.exists(path):
                print(f"[MISS] {s['file']}"); continue
            doc = fitz.open(path)
            char_pos = 0
            for pi in range(doc.page_count):
                img = render_page_array(doc[pi])
                res = reader.readtext(img, detail=1, paragraph=False)  # [(bbox, text, conf), ...]
                if not res:
                    continue
                text = "\n".join(t for _, t, _ in res).strip()
                confs = [c for _, _, c in res]
                avg_conf = round(sum(confs) / len(confs), 3) if confs else 0.0
                for piece in token_split(text, enc, cc["target_tokens"], cc["max_tokens"], cc["overlap_tokens"]):
                    piece = piece.strip()
                    if len(enc.encode(piece)) < cc.get("min_tokens", 12):
                        continue
                    start = char_pos
                    char_pos += len(piece) + 1
                    cid = hashlib.sha1(f"{tenant}|{s['file']}|{start}".encode()).hexdigest()[:16]
                    rec = {
                        "chunk_id": cid, "tenant_id": tenant, "source": s["file"], "source_url": s["url"],
                        "category": s["category"], "doc_type": s["doc_type"],
                        "standard_code": s.get("standard_code"), "doc_version": s.get("doc_version"),
                        "language": cfg.get("language", "ru"), "page_number": pi + 1,
                        "section_title": s.get("title", ""), "heading_path": [s.get("title", "")],
                        "content_type": "text", "char_start": start, "char_end": start + len(piece),
                        "token_count": len(enc.encode(piece)),
                        "fetch_timestamp": prov.get(s["file"], {}).get("fetch_timestamp"),
                        "file_hash": prov.get(s["file"], {}).get("file_hash"),
                        "ocr": True, "ocr_confidence": avg_conf, "text": piece,
                    }
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    total += 1
                print(f"[OCR] {s['file']} стр.{pi + 1}: {len(res)} блоков, conf~{avg_conf}")
            doc.close()
    print(f"\nOCR готов: {total} чанков → {out_path}")


if __name__ == "__main__":
    main()
