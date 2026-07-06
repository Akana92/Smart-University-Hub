"""
Гейт качества RAG (TASK-029, ADR-021 — паттерн LLM-as-a-Judge по ресёрчу).

Детерминированная проверка PASS/FAIL метрик из отчёта eval/ragas_report.json против
запиненного baseline (eval/baseline.json). **0 токенов**: читает УЖЕ посчитанный отчёт
(судья не вызывается). Роняет билд (exit 1) при просадке ниже порога — защита от регрессий
качества перед изменением кода/промпта.

Двухслойно (по ресёрчу): судья НЕ единственный гейт — бесплатные детерминированные оси
(refusal_rate / false_refusal_rate, 0 токенов) проверяются всегда; метрики судьи — если есть
в отчёте. Пороги = baseline − допуск (не 0.9), чтобы шум судьи ~±0.03 не ронял билд.

    python eval/gate.py                          # проверить eval/ragas_report.json
    python eval/gate.py --report eval/ragas_report_studentlife.json
    # свежий прогон судьи перед гейтом (тратит токены):
    python eval/run_ragas.py --config configs/kbtu.yaml --judge gpt-4o --ids ... && python eval/gate.py
"""
import argparse
import json
import os
import sys

try:  # utf-8 для консоли (символ «≠» и т.п.); под захватом stdout в тестах — без падения
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))


def evaluate_gate(metrics: dict, thresholds: dict) -> tuple[bool, list[dict]]:
    """Чистая функция (тестируемая): metrics + пороги → (passed, строки-результаты)."""
    rows, passed = [], True
    for key, rule in thresholds.items():
        val = metrics.get(key)
        label = rule.get("label", key)
        if val is None or (isinstance(val, float) and val != val):  # None / NaN → SKIP (не роняем)
            rows.append({"metric": key, "label": label, "value": None, "status": "SKIP",
                         "note": "нет значения в отчёте"})
            continue
        if "min" in rule:
            ok = val >= rule["min"]
            bound = f"≥ {rule['min']}"
        else:
            ok = val <= rule["max"]
            bound = f"≤ {rule['max']}"
        if not ok:
            passed = False
        rows.append({"metric": key, "label": label, "value": round(float(val), 4),
                     "bound": bound, "status": "PASS" if ok else "FAIL"})
    return passed, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=os.path.join(HERE, "ragas_report.json"))
    ap.add_argument("--baseline", default=os.path.join(HERE, "baseline.json"))
    args = ap.parse_args()

    if not os.path.exists(args.report):
        print(f"ГЕЙТ: нет отчёта {args.report} — сначала запусти eval/run_ragas.py", file=sys.stderr)
        sys.exit(2)
    report = json.load(open(args.report, encoding="utf-8"))
    metrics = report.get("metrics", {})
    thresholds = json.load(open(args.baseline, encoding="utf-8"))["thresholds"]

    passed, rows = evaluate_gate(metrics, thresholds)

    print("=" * 62)
    print(f"ГЕЙТ КАЧЕСТВА RAG · отчёт: {os.path.basename(args.report)}")
    print(f"судья: {report.get('meta', {}).get('judge_llm', '—')}  "
          f"(судья≠генератор: {report.get('meta', {}).get('judge_ne_generator')})")
    print("=" * 62)
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚠️ "}
    for r in rows:
        v = r["value"] if r["value"] is not None else "—"
        b = r.get("bound", r.get("note", ""))
        print(f" {icon[r['status']]} {r['status']:4} {str(v):>6}  {b:8}  {r['label']}")
    print("=" * 62)
    if passed:
        print("ИТОГ: ✅ PASS — качество не ниже baseline, релиз разрешён.")
        sys.exit(0)
    print("ИТОГ: ❌ FAIL — просадка ниже порога. Релиз заблокирован (разберись до мерджа).")
    sys.exit(1)


if __name__ == "__main__":
    main()
