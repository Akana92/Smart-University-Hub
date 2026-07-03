"""
POC-рекомендатель грантов (движок B, docs/03 §5).

Вход: балл ЕНТ + пара профильных предметов (+ опц. город).
Выход: программы (ГОП×вуз), разложенные на 3 корзины — ✅ проходит / ⚠️ рискованно / ❌ не проходит,
каждая с ПРОВЕНАНСОМ (источник, год, число грантов, достоверность). Если ничего не проходит —
дерево «что делать дальше».

ЖЁСТКИЙ ИНВАРИАНТ (docs/03 §5.4): ни один балл не выдуман — все числа из БД. Нет данных → честный отказ.
ЧЕСТНОСТЬ: показываем ИСТОРИЧЕСКУЮ отсечку 2025 как вероятность, НЕ гарантию.

Запуск:
    python recommend.py --demo
    python recommend.py --score 100 --profile "математика,информатика" --city Алматы
"""
import argparse
import json
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CFG = os.path.join(HERE, "config")
DB = os.path.join(DATA, "grant_scores.db")

with open(os.path.join(CFG, "thresholds.json"), encoding="utf-8") as f:
    TH = json.load(f)
with open(os.path.join(CFG, "profile_map.json"), encoding="utf-8") as f:
    _PROFILE_MAP_RAW = json.load(f)["pairs"]

MARGIN = 3  # коридор «рискованно» вокруг прошлогодней отсечки


def norm_profile(profile: str) -> str:
    """'информатика, математика' -> 'информатика+математика' (сортированный ключ, порядок предметов не важен)."""
    parts = [p.strip().lower() for p in profile.replace("+", ",").split(",") if p.strip()]
    return "+".join(sorted(parts))


# нормализуем ключи карты тем же способом, чтобы порядок предметов в JSON не влиял
PROFILE_MAP = {norm_profile(k): v for k, v in _PROFILE_MAP_RAW.items()}


def statutory_threshold(is_national: int, gop_name: str) -> int:
    t = TH["base"]
    if is_national:
        t = max(t, TH["national_university"])
    low = (gop_name or "").lower()
    for kw, val in TH["by_gop_keyword"].items():
        if kw in low:
            t = max(t, val)
    return t


def classify(score: int, passing: int) -> str:
    if score >= passing + MARGIN:
        return "pass"
    if score >= passing - MARGIN:
        return "risk"
    return "fail"


BUCKET_LABEL = {"pass": "✅ ПРОХОДИТ", "risk": "⚠️ РИСКОВАННО", "fail": "❌ НЕ ПРОХОДИТ"}


def recommend(score: int, profile: str, city: str | None = None, budget: int | None = None):
    key = norm_profile(profile)
    keywords = PROFILE_MAP.get(key)
    if keywords is None:
        return {"error": f"Профиль '{key}' не в карте (POC поддерживает: {', '.join(PROFILE_MAP)})."}

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT p.*, u.name AS univ_name, u.city AS city, u.is_national AS is_national
           FROM passing_scores p JOIN universities u ON u.univ_id=p.univ_id
           WHERE p.metric='passing' AND p.quota_type='general' AND p.year=2025"""
    ).fetchall()
    tuition = {r["univ_id"]: dict(r) for r in con.execute("SELECT * FROM tuition").fetchall()}
    con.close()

    results = []
    for r in rows:
        name_low = (r["gop_name"] or "").lower()
        if not any(k in name_low for k in keywords):
            continue
        if city and city.strip().lower() not in (r["city"] or "").lower():
            continue
        thr = statutory_threshold(r["is_national"], r["gop_name"])
        passing = r["score"]
        bucket = "blocked" if score < thr else classify(score, passing)
        t = tuition.get(r["univ_id"], {})
        results.append({
            "univ": r["univ_name"], "city": r["city"], "gop_code": r["gop_code"],
            "gop_name": r["gop_name"], "passing_2025": passing, "grants": r["grants_count"],
            "threshold": thr, "bucket": bucket, "gap": score - passing,
            "source_url": r["source_url"], "confidence": r["confidence"], "year": r["year"],
            "tuition_min": t.get("tuition_min_kzt"), "tuition_max": t.get("tuition_max_kzt"),
            "tuition_src": t.get("source_url"),
        })

    order = {"pass": 0, "risk": 1, "fail": 2, "blocked": 3}
    results.sort(key=lambda x: (order[x["bucket"]], -x["passing_2025"]))
    return {"score": score, "profile": key, "city": city, "budget": budget, "results": results}


def render(rec) -> str:
    if "error" in rec:
        return "⚠️ " + rec["error"]
    out = []
    out.append("=" * 66)
    out.append(f" Балл ЕНТ: {rec['score']}   Профиль: {rec['profile']}" + (f"   Город: {rec['city']}" if rec["city"] else ""))
    out.append("=" * 66)
    res = rec["results"]
    if not res:
        out.append("Нет программ под этот профиль в базе (87 вузов; покрытие ограничено иллюстративной профиль-картой POC).")
        return "\n".join(out)

    passable = [r for r in res if r["bucket"] in ("pass", "risk")]
    groups = {
        "pass": sorted([r for r in res if r["bucket"] == "pass"], key=lambda x: -x["passing_2025"]),
        "risk": sorted([r for r in res if r["bucket"] == "risk"], key=lambda x: -x["passing_2025"]),
        "fail": sorted([r for r in res if r["bucket"] == "fail"], key=lambda x: x["gap"], reverse=True),  # ближайший промах первым
    }
    LIMITS = {"pass": 6, "risk": 4, "fail": 5}
    for b in ("pass", "risk", "fail"):
        g = groups[b]
        for r in g[:LIMITS[b]]:
            sign = f"+{r['gap']}" if r["gap"] >= 0 else str(r["gap"])
            src = r["source_url"].split("//")[1][:34]
            city = f" ({r['city']})" if r["city"] else ""
            out.append("")
            out.append(f"{BUCKET_LABEL[b]}  {r['gop_code']} {r['gop_name']} — {r['univ']}{city}")
            out.append(f"    Проходной на грант 2025: {r['passing_2025']}  (грантов: {r['grants']})  |  ваш балл {sign} к отсечке")
            out.append(f"    Порог допуска: {r['threshold']}   ·   📎 {src}… · {r['year']} · достоверность: {r['confidence']}")
        if len(g) > LIMITS[b]:
            out.append(f"    …ещё {len(g) - LIMITS[b]} программ в категории «{BUCKET_LABEL[b]}»")

    blocked = [r for r in res if r["bucket"] == "blocked"]
    if blocked:
        out.append("")
        out.append(f"⛔ Ниже порога допуска: {len(blocked)} программ (балл не даёт участвовать в конкурсе по этим ГОП)")

    out.append("")
    out.append("-" * 66)
    if passable:
        out.append("⚠️  Это НЕ гарантия: отсечка 2026 сформируется по итогам конкурса (число грантов × сила заявителей).")
        out.append("💡 Стратегия 4 приоритетов: 1-2 — амбициозные (⚠️), 3-4 — запасные (✅).")
    else:
        out.append("На желаемый профиль баллов на грант НЕ ХВАТАЕТ. Что делать (docs/03 §5.2):")
        near = max((r for r in res if r["bucket"] == "fail"), key=lambda x: x["gap"], default=None)
        # A. Платное — реальные варианты по стоимости из БД tuition (ветка «не хватило → платное»)
        paid = [r for r in res if r.get("tuition_min")]
        if rec.get("budget"):
            paid = [r for r in paid if r["tuition_min"] <= rec["budget"]]
        seen, paid_u = set(), []
        for r in sorted(paid, key=lambda x: x["tuition_min"]):
            if r["univ"] in seen:
                continue
            seen.add(r["univ"]); paid_u.append(r)
        if paid_u:
            bnote = (f" (в бюджете <= {rec['budget']:,} тг)".replace(",", " ")) if rec.get("budget") else ""
            out.append(f"  • A. Платное обучение{bnote} — доступно по цене:")
            for r in paid_u[:5]:
                src = r["tuition_src"].split("//")[1][:32] if r.get("tuition_src") else "—"
                out.append(f"       {r['univ']}: от {r['tuition_min']:,} тг/год".replace(",", " ") + f"   📎 {src}…")
        else:
            out.append("  • A. Платное обучение (+ перевод на грант по успеваемости).")
        if near:
            out.append(f"  • B. Пересдача ЕНТ: до ближайшей отсечки не хватает {-near['gap']} балл(ов) ({near['gop_code']}@{near['univ']} = {near['passing_2025']}).")
        out.append("  • C. Ниже-конкурсные ГОП/вузы того же профиля (региональные вузы с меньшей отсечкой).")
        out.append("  • D. Гранты акиматов / вузовские гранты (отдельные конкурсы).")
        out.append("  • E. Колледж → сокращённая программа (пороги 25/35).")
        out.append("  • F. Автономный трек (NU/KIMEP — свои экзамены, платно).")
    return "\n".join(out)


DEMO = [
    (120, "математика,информатика", None, None),
    (100, "математика,информатика", None, None),
    (55,  "химия,биология", None, 2500000),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", type=int)
    ap.add_argument("--profile", type=str)
    ap.add_argument("--city", type=str, default=None)
    ap.add_argument("--budget", type=int, default=None, help="макс. бюджет платного, тг/год")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    blocks = []
    if args.demo or not (args.score and args.profile):
        for s, p, c, b in DEMO:
            blocks.append(render(recommend(s, p, c, b)))
    else:
        blocks.append(render(recommend(args.score, args.profile, args.city, args.budget)))

    text = ("\n\n".join(blocks)) + "\n"
    print(text)
    with open(os.path.join(DATA, "demo_output.txt"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
