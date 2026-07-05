"""
Fetch веб-страниц студенческой жизни (движок A, TASK-015).

Читает web_sources из конфига → HTML (requests, браузерный UA; SSL-цепочка kbtu.edu.kz
неполная → verify=False фолбэк) → очистка (BeautifulSoup: основной контент, заголовки → #,
списки → -, таблицы → |; убираем Joomla-шорткоды {spoiler=Заголовок} → ## Заголовок и
антиспам-заглушки email, полупустые строки контактов) → data/<tenant>/web_raw/<slug>.md
+ web_manifest.json (url, title, статус, размер, provenance: fetch_timestamp, file_hash).

Идемпотентно: повторный запуск перекачивает. Дальше — ingest_web.py (чанкинг).

    python ingestion/fetch_web.py --config configs/kbtu.yaml
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests
import urllib3
import yaml
from bs4 import BeautifulSoup

urllib3.disable_warnings()
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125 Safari/537.36")
SPAM = ("Адрес электронной почты защищен от спам-ботов. "
        "Для просмотра адреса в браузере должен быть включен Javascript.")


def to_markdown(html):
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one(".item-page, [itemprop=articleBody], main, .content, #content, article") or soup.body
    if not main:
        return ""
    for t in main.select("script,style,nav,header,footer,noscript,form,.breadcrumb,.pagination"):
        t.decompose()
    out = []
    for el in main.find_all(["h1", "h2", "h3", "h4", "h5", "p", "ul", "ol", "table", "blockquote"]):
        if el.find_parent("table"):
            continue
        name = el.name
        if name[0] == "h" and name[1:].isdigit():
            txt = el.get_text(" ", strip=True)
            if txt:
                out.append(f"\n{'#' * int(name[1])} {txt}")
        elif name in ("ul", "ol"):
            for li in el.find_all("li", recursive=False):
                t = li.get_text(" ", strip=True)
                if t:
                    out.append(f"- {t}")
        elif name == "table":
            for tr in el.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if any(cells):
                    out.append("| " + " | ".join(cells) + " |")
        else:
            t = el.get_text(" ", strip=True)
            if t:
                out.append(t)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def clean(md):
    md = md.replace(SPAM, "")
    md = re.sub(r"\{spoiler=([^}]*)\}", lambda m: f"\n## {m.group(1).strip()}\n", md)
    md = md.replace("{/spoilers}", "").replace("{/spoiler}", "")
    lines = []
    for ln in md.split("\n"):
        s = ln.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if sum(1 for c in cells if c) < 2:  # почти пустая строка контактов
                continue
        lines.append(ln)
    md = "\n".join(lines)
    md = re.sub(r"[ \t]+\n", "\n", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--min-chars", type=int, default=200, help="страницы короче — не сохраняем")
    args = ap.parse_args()
    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    tenant = cfg["tenant_id"]
    base = os.path.join(ROOT, "data", tenant)
    web_dir = os.path.join(base, "web_raw")
    os.makedirs(web_dir, exist_ok=True)

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    sess.verify = False  # kbtu.edu.kz: неполная цепочка CA (как в download_kbtu.py)

    ts = datetime.now(timezone.utc).isoformat()
    manifest = []
    for s in cfg.get("web_sources", []):
        slug, url, title = s["slug"], s["url"], s.get("title", s["slug"])
        try:
            r = sess.get(url, timeout=30, allow_redirects=True)
            md = clean(f"# {title}\n\n{to_markdown(r.text)}") if r.status_code == 200 else ""
            status, fh = r.status_code, hashlib.sha1(r.content).hexdigest()[:16]
        except Exception as e:
            md, status, fh = "", f"ERR:{type(e).__name__}", ""
            print(f"[ERR ] {slug}: {e}")
        if len(md) >= args.min_chars:
            open(os.path.join(web_dir, slug + ".md"), "w", encoding="utf-8").write(md + "\n")
        manifest.append({"slug": slug, "url": url, "category": "student_life", "title": title,
                         "status": status, "chars": len(md), "fetch_timestamp": ts, "file_hash": fh})
        print(f"[{status}] {slug:18} chars={len(md)}")

    json.dump(manifest, open(os.path.join(base, "web_manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    ok = sum(1 for m in manifest if isinstance(m["status"], int) and m["status"] == 200 and m["chars"] >= args.min_chars)
    print(f"\nИтог: {ok}/{len(manifest)} страниц сохранено в {web_dir}")


if __name__ == "__main__":
    main()
