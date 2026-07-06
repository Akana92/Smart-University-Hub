"""
Тесты гейта качества RAG (TASK-029) — герметичные, чистая функция evaluate_gate (0 API).
Проверяют PASS/FAIL/SKIP-логику порогов min/max.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "eval")))

from gate import evaluate_gate  # noqa: E402

TH = {
    "faithfulness_answered": {"min": 0.85, "label": "F"},
    "in_base_false_refusal_rate": {"max": 0.35, "label": "FR"},
}


def test_gate_pass_when_above_thresholds():
    passed, rows = evaluate_gate({"faithfulness_answered": 1.0, "in_base_false_refusal_rate": 0.2}, TH)
    assert passed is True
    assert all(r["status"] == "PASS" for r in rows)


def test_gate_fails_on_low_min_metric():
    passed, rows = evaluate_gate({"faithfulness_answered": 0.70, "in_base_false_refusal_rate": 0.2}, TH)
    assert passed is False
    assert any(r["status"] == "FAIL" and r["metric"] == "faithfulness_answered" for r in rows)


def test_gate_fails_on_high_max_metric():
    passed, _ = evaluate_gate({"faithfulness_answered": 1.0, "in_base_false_refusal_rate": 0.55}, TH)
    assert passed is False


def test_gate_skips_missing_metric_without_failing():
    passed, rows = evaluate_gate({"faithfulness_answered": 1.0}, TH)  # false_refusal отсутствует
    assert passed is True  # SKIP не роняет билд
    assert any(r["status"] == "SKIP" for r in rows)


def test_baseline_matches_committed_report():
    # committed отчёт TASK-014 должен проходить запиненный baseline
    import json
    ev = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "eval"))
    metrics = json.load(open(os.path.join(ev, "ragas_report.json"), encoding="utf-8"))["metrics"]
    th = json.load(open(os.path.join(ev, "baseline.json"), encoding="utf-8"))["thresholds"]
    passed, _ = evaluate_gate(metrics, th)
    assert passed is True
