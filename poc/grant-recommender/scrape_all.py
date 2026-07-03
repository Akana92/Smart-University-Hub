"""
Масштабный скрейпер: все вузы РК, у которых есть страница проходных баллов на univision
(87 шт. из config/universities_all.json). Вежливый краулинг (UA + задержка + ретраи).
Перезаписывает data/passing_scores.csv и data/universities.csv полным набором.

Курируемые вузы (5 из POC) получают человеческие метаданные (город/тип) поверх авто-имён.
"""
import csv
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CFG = os.path.join(HERE, "config")
os.makedirs(DATA, exist_ok=True)

UA = "Mozilla/5.0 (SmartUniversity research POC; contact akana92@gmail.com)"
BASE = "https://univision.kz/univ/{slug}/ball"
YEAR = 2025
DELAY = 1.5

# курируемые метаданные (uv_id -> город/тип/имя)
CURATED = {
    50:  ("КазНУ им. аль-Фараби", "Алматы", "national"),
    63:  ("KBTU (Каз.-Британский ТУ)", "Алматы", "private"),
    47:  ("Satbayev University", "Алматы", "national"),
    23:  ("ЕНУ им. Гумилёва", "Астана", "national"),
    119: ("Astana IT University", "Астана", "private"),
}

def classify(label):
    l = (label or "").lower()
    if "минимальн" in l or "пороговый" in l: return "general", "threshold"
    if "общий конкурс" in l: return "general", "passing"
    if "сельск" in l: return "rural", "passing"
    if "инвалид" in l: return "disability", "passing"
    if "четыре и более" in l or "многодет" in l: return "large_family", "passing"
    if "неполн" in l: return "single_parent", "passing"
    return "other", "passing"

GOP_RE = re.compile(r"^(B[A-ZА-Я]?\d+[A-Za-z]?)\s+(.+)$")

def nearest_label(table):
    node = table
    for _ in range(10):
        node = node.find_previous(["h2","h3","h4","h5","button","summary","strong"])
        if node is None: return ""
        txt = node.get_text(strip=True)
        if txt and ("2025" in txt or "пороговый" in txt.lower() or "минимальн" in txt.lower()):
            return txt
    return ""

def fetch(session, url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
        except Exception:
            pass
        time.sleep(1.5 * (i + 1))
    return None

def main():
    unis = json.load(open(os.path.join(CFG, "universities_all.json"), encoding="utf-8"))
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ru,en"})
    from datetime import datetime, timezone
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    all_rows, uni_rows, ok, fail = [], [], 0, 0
    for i, u in enumerate(unis):
        uv_id = u["uv_id"]
        name, city, utype = CURATED.get(uv_id, (u["name"], "", "other"))
        url = BASE.format(slug=u["slug"])
        html = fetch(session, url)
        if html is None:
            fail += 1
            print(f"[FAIL] {uv_id} {u['slug'][:40]}")
            continue
        soup = BeautifulSoup(html, "lxml")
        rows = []
        for table in soup.find_all("table"):
            qt, metric = classify(nearest_label(table))
            for tr in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in tr.find_all(["td","th"])]
                if len(cells) < 3: continue
                m = GOP_RE.match(cells[0])
                if not m: continue
                try: score = int(re.sub(r"\D","",cells[1]))
                except ValueError: continue
                grants = None
                if cells[2] and cells[2] not in ("-","—"):
                    d = re.sub(r"\D","",cells[2]); grants = int(d) if d else None
                rows.append({
                    "univ_id": f"u{uv_id}", "univ_name": name, "city": city, "univ_type": utype,
                    "is_national": u["is_national"], "gop_code": m.group(1).strip(),
                    "gop_name": m.group(2).strip(), "metric": metric, "quota_type": qt,
                    "score": score, "grants_count": grants, "year": YEAR, "granularity": "univ_gop",
                    "source_url": url, "source_type": "aggregator", "confidence": "medium",
                    "scraped_at": scraped_at,
                })
        if rows:
            all_rows.extend(rows); ok += 1
            uni_rows.append({"univ_id": f"u{uv_id}", "name": name, "city": city, "univ_type": utype,
                             "is_national": u["is_national"], "admission_track": "ent",
                             "univision_id": uv_id, "source_url": url})
            gen = sum(1 for r in rows if r["quota_type"]=="general" and r["metric"]=="passing")
            print(f"[{i+1:3d}/{len(unis)}] {uv_id:<4} rows={len(rows):4d} genpass={gen:3d} {name[:34]}")
        else:
            fail += 1
            print(f"[EMPTY] {uv_id} {u['slug'][:40]}")
        time.sleep(DELAY)

    with open(os.path.join(DATA,"passing_scores.csv"),"w",encoding="utf-8",newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys())); w.writeheader(); w.writerows(all_rows)
    with open(os.path.join(DATA,"universities.csv"),"w",encoding="utf-8",newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(uni_rows[0].keys())); w.writeheader(); w.writerows(uni_rows)
    print(f"\nDONE ok={ok} fail={fail} total_rows={len(all_rows)} unis={len(uni_rows)}")

if __name__ == "__main__":
    main()
