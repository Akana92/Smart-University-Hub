"""
POC-скрейпер проходных баллов на грант с univision.kz (страница /univ/{id}-{slug}/ball).

Что делает: для набора вузов забирает HTML-страницу с проходными баллами,
парсит все таблицы (по квотам + пороговый срез), нормализует в единый CSV
с ПОЛНЫМ провенансом (source_url, year, quota_type, metric, scraped_at, confidence).

ЧЕСТНОСТЬ (см. docs/03 §2-3):
- univision.kz — агрегатор, НЕ официальный первоисточник → source_type='aggregator', confidence='medium'.
- Это ИСТОРИЧЕСКАЯ отсечка 2025 (проходной формируется постфактум), НЕ гарантия будущего.
- Конкурс идёт по ГРУППАМ образовательных программ (ГОП B###), не по специальностям.
- robots.txt разрешает /univ/.../ball (запрещены /*Search, /*Result, /admin). Вежливый краулинг: UA + задержка.
"""
import csv
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

UA = "Mozilla/5.0 (SmartUniversity research POC; contact akana92@gmail.com)"
BASE = "https://univision.kz/univ/{id}-{slug}/ball"
YEAR = 2025  # страница помечена «(2025)»; свежайший полностью распределённый конкурс
DELAY_SEC = 2.0  # вежливая пауза между вузами

UNIS = [
    {"univ_id": "kaznu",   "uv_id": 50,  "slug": "kazahskiy-natsionalnyy-universitet-imeni-al-farabi",
     "name": "КазНУ им. аль-Фараби", "city": "Алматы", "type": "national", "is_national": True},
    {"univ_id": "kbtu",    "uv_id": 63,  "slug": "kazahstansko-britanskiy-tehnicheskiy-universitet",
     "name": "KBTU (Каз.-Британский ТУ)", "city": "Алматы", "type": "private", "is_national": False},
    {"univ_id": "satbayev","uv_id": 47,  "slug": "kazahskiy-natsionalnyy-issledovatelskiy-tehnicheskiy-universitet-imeni-k-i-satpaeva",
     "name": "Satbayev University", "city": "Алматы", "type": "national", "is_national": True},
    {"univ_id": "enu",     "uv_id": 23,  "slug": "evraziyskiy-natsionalnyy-universitet-im-l-n-gumileva",
     "name": "ЕНУ им. Гумилёва", "city": "Астана", "type": "national", "is_national": True},
    {"univ_id": "aitu",    "uv_id": 119, "slug": "astana-it-university",
     "name": "Astana IT University", "city": "Астана", "type": "private", "is_national": False},
]

# отображение подписи-заголовка таблицы → машинный quota_type + metric
def classify_table_label(label: str):
    l = (label or "").lower()
    if "минимальн" in l or "пороговый" in l:
        return "general", "threshold"      # пороговый срез (баллы допуска по ГОП)
    if "общий конкурс" in l:
        return "general", "passing"
    if "сельск" in l:
        return "rural", "passing"
    if "инвалид" in l:
        return "disability", "passing"
    if "четыре и более" in l or "многодет" in l:
        return "large_family", "passing"
    if "неполн" in l:
        return "single_parent", "passing"
    return "other", "passing"

GOP_RE = re.compile(r"^(B[A-ZА-Я]?\d+[A-Za-z]?)\s+(.+)$")

def nearest_label(table):
    node = table
    for _ in range(10):
        node = node.find_previous(["h2", "h3", "h4", "h5", "button", "summary", "strong"])
        if node is None:
            return ""
        txt = node.get_text(strip=True)
        if txt and ("2025" in txt or "пороговый" in txt.lower() or "минимальн" in txt.lower()):
            return txt
    return ""

def scrape_one(u, session):
    url = BASE.format(id=u["uv_id"], slug=u["slug"])
    r = session.get(url, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "lxml")
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for table in soup.find_all("table"):
        label = nearest_label(table)
        quota_type, metric = classify_table_label(label)
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            m = GOP_RE.match(cells[0])
            if not m:
                continue
            try:
                score = int(re.sub(r"\D", "", cells[1]))
            except ValueError:
                continue
            grants = None
            if cells[2] and cells[2] not in ("-", "—"):
                digits = re.sub(r"\D", "", cells[2])
                grants = int(digits) if digits else None
            rows.append({
                "univ_id": u["univ_id"], "univ_name": u["name"], "city": u["city"],
                "univ_type": u["type"], "is_national": u["is_national"],
                "gop_code": m.group(1).strip(), "gop_name": m.group(2).strip(),
                "metric": metric, "quota_type": quota_type,
                "score": score, "grants_count": grants, "year": YEAR,
                "granularity": "univ_gop",
                "source_url": url, "source_type": "aggregator",
                "confidence": "medium", "scraped_at": scraped_at,
            })
    return url, rows

def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ru,en"})
    all_rows = []
    uni_rows = []
    for i, u in enumerate(UNIS):
        try:
            url, rows = scrape_one(u, session)
            all_rows.extend(rows)
            gen = sum(1 for r in rows if r["quota_type"] == "general" and r["metric"] == "passing")
            print(f"[OK] {u['univ_id']:8s} id={u['uv_id']:<4} rows={len(rows):4d}  general_passing={gen}")
            uni_rows.append({
                "univ_id": u["univ_id"], "name": u["name"], "city": u["city"],
                "univ_type": u["type"], "is_national": u["is_national"],
                "admission_track": "ent", "univision_id": u["uv_id"], "source_url": url,
            })
        except Exception as e:
            print(f"[FAIL] {u['univ_id']}: {e!r}")
        if i < len(UNIS) - 1:
            time.sleep(DELAY_SEC)

    ps_path = os.path.join(DATA, "passing_scores.csv")
    with open(ps_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)

    uni_path = os.path.join(DATA, "universities.csv")
    with open(uni_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(uni_rows[0].keys()))
        w.writeheader()
        w.writerows(uni_rows)

    print(f"\nTOTAL rows: {len(all_rows)}  ->  {ps_path}")
    print(f"universities: {len(uni_rows)}  ->  {uni_path}")

if __name__ == "__main__":
    main()
