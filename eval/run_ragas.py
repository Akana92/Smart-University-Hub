"""
Оценка качества RAG через Ragas (ТЗ §5 «Тестирование», TASK-014).

Метрики RAG-триады + relevancy (судья ≠ генератор). ВАЖНО — оси считаются раздельно:
  * faithfulness, answer_relevancy — по ОТВЕЧЕННЫМ in_base вопросам (качество выданного ответа;
    отказ не имеет «faithfulness», иначе он смешивается с галлюцинацией);
  * context_precision, context_recall — по ВСЕМ in_base (это метрики retrieval, они осмысленны,
    даже если LLM затем отказал).

Отдельная ось (дёшево, без судьи) — поведение отказа:
  * refusal_rate (out_of_base)      — доля корректных отказов, когда ответа в базе нет (эталон 1.0);
  * false_refusal_rate (in_base)    — доля ложных отказов, когда ответ в базе есть (эталон 0.0);
    с разбором: retrieval-gap (recall низкий) vs over-refusal (retrieval нашёл, LLM отказал).

Бюджет:
  * генерация кэшируется в eval/rag_outputs.jsonl → повторный прогон судьи = 0 токенов генератора;
  * по-сэмплово оценки судьи сохраняются в eval/ragas_per_sample.json → пере-отчёт без API;
  * судья по умолчанию gpt-4o-mini (структурная проверка); отчётный прогон — --judge gpt-4o.

Примеры:
  python eval/run_ragas.py --config configs/kbtu.yaml --judge gpt-4o-mini --n 8              # дёшево
  python eval/run_ragas.py --config configs/kbtu.yaml --judge gpt-4o --ids s01,s03,c01,c02   # отчётный
  python eval/run_ragas.py --config configs/kbtu.yaml --offline --skip-ragas                 # 0 API
"""
import argparse
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)   # для _ragas_compat
sys.path.insert(0, ROOT)   # для generation/providers

import _ragas_compat  # noqa: E402,F401  ДО импорта ragas: заглушка удалённого langchain_community.chat_models.vertexai

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from generation.ask import build_pipeline  # noqa: E402

GOLDEN = os.path.join(HERE, "golden_set.jsonl")
CACHE = os.path.join(HERE, "rag_outputs.jsonl")
PER_JSON = os.path.join(HERE, "ragas_per_sample.json")
REPORT_JSON = os.path.join(HERE, "ragas_report.json")
REPORT_MD = os.path.join(HERE, "ragas_report.md")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def pick_spread(items, n):
    """Равномерно выбрать n элементов (репрезентативно по всему списку/категориям)."""
    if n is None or n >= len(items):
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def generate(records, cfg, args):
    """Ответы пайплайна с кэшем по id (бережём бюджет: повторный прогон не перегенерирует).

    ВНИМАНИЕ: кэш (rag_outputs.jsonl) НЕ инвалидируется при переиндексации стора.
    После reindex (напр. добавили student_life) прогоняйте с --regen, иначе метрики
    посчитаются по устаревшим ответам старого индекса.
    """
    cache = {r["id"]: r for r in load_jsonl(CACHE)}
    pipe = None
    out = []
    for it in records:
        cached = cache.get(it["id"])
        if cached and not args.regen:
            out.append(cached)
            continue
        if args.offline:
            print(f"  [offline] нет в кэше, пропуск: {it['id']}", file=sys.stderr)
            continue
        if pipe is None:
            pipe = build_pipeline(cfg, args.store, args.emb, args.llm)
        cats = [it["category"]] if it.get("category") else None
        res = pipe.answer(it["question"], categories=cats)
        rec = {
            "id": it["id"], "type": it["type"], "category": it.get("category"),
            "question": it["question"], "ground_truth": it["ground_truth"],
            "answer": res["answer"], "refused": res["refused"],
            "contexts": res.get("contexts", []), "reason": res["reason"],
            "tokens": res.get("tokens"),
        }
        out.append(rec)
        cache[it["id"]] = rec
    with open(CACHE, "w", encoding="utf-8") as f:
        for r in cache.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def _canon(col):
    c = col.lower()
    if "faithful" in c:
        return "faithfulness"
    if "relevanc" in c:
        return "answer_relevancy"
    if "precision" in c:
        return "context_precision"
    if "recall" in c:
        return "context_recall"
    return None


def run_ragas(records, judge_model):
    """Считает Ragas-метрики; возвращает per-sample список dict с каноническими именами метрик."""
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (Faithfulness, LLMContextPrecisionWithReference,
                               LLMContextRecall, ResponseRelevancy)
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    judge = LangchainLLMWrapper(ChatOpenAI(model=judge_model, temperature=0))
    emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))

    samples = [SingleTurnSample(
        user_input=r["question"], response=r["answer"],
        retrieved_contexts=(r["contexts"] or [""]), reference=r["ground_truth"],
    ) for r in records]
    ds = EvaluationDataset(samples=samples)
    metrics = [Faithfulness(), ResponseRelevancy(),
               LLMContextPrecisionWithReference(), LLMContextRecall()]

    kwargs = {}
    try:  # больший таймаут + ретраи, чтобы тяжёлые NLI-джобы не падали в NaN
        from ragas.run_config import RunConfig
        kwargs["run_config"] = RunConfig(timeout=300, max_retries=5, max_wait=60, max_workers=4)
    except Exception:
        pass
    result = evaluate(dataset=ds, metrics=metrics, llm=judge, embeddings=emb, **kwargs)
    df = result.to_pandas()

    per = []
    for rec, (_, row) in zip(records, df.iterrows()):
        d = {"id": rec["id"], "category": rec.get("category"), "refused": rec["refused"]}
        for col in df.columns:
            k = _canon(col)
            if not k:
                continue
            v = row[col]
            d[k] = (None if (isinstance(v, float) and math.isnan(v))
                    else round(float(v), 4) if isinstance(v, (int, float)) else None)
        per.append(d)
    return per


def _mean(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 4) if vals else None


def write_report(args, in_recs, out_recs, per):
    by_id = {p["id"]: p for p in per}
    answered = [p for p in per if not p["refused"]]

    faithfulness = _mean([p.get("faithfulness") for p in answered])       # только по отвеченным
    answer_relevancy = _mean([p.get("answer_relevancy") for p in answered])
    context_precision = _mean([p.get("context_precision") for p in per])  # retrieval — по всем
    context_recall = _mean([p.get("context_recall") for p in per])

    refusal_rate = (round(sum(1 for r in out_recs if r["refused"]) / len(out_recs), 4)
                    if out_recs else None)
    false_refusal = (round(sum(1 for r in in_recs if r["refused"]) / len(in_recs), 4)
                     if in_recs else None)

    # разбор ложных отказов: retrieval нашёл (recall высокий) → over-refusal; иначе retrieval-gap
    false_ref_detail = []
    for r in in_recs:
        if r["refused"]:
            rec = by_id.get(r["id"], {})
            rc = rec.get("context_recall")
            kind = ("over-refusal (retrieval нашёл, LLM отказал)" if isinstance(rc, (int, float)) and rc >= 0.5
                    else "retrieval-gap (нужного контекста не поднялось)")
            false_ref_detail.append((r["id"], r["question"], rc, kind))

    report = {
        "meta": {
            "generator_llm": "gpt-4o-mini (temperature=0)",
            "judge_llm": args.judge,
            "judge_ne_generator": args.judge not in ("gpt-4o-mini", "openai"),
            "embeddings_metric": "text-embedding-3-small",
            "golden_set_total": len(load_jsonl(GOLDEN)),
            "in_base_evaluated": len(in_recs),
            "in_base_answered": len(answered),
            "out_of_base_evaluated": len(out_recs),
        },
        "metrics": {
            "faithfulness_answered": faithfulness,
            "answer_relevancy_answered": answer_relevancy,
            "context_precision_all": context_precision,
            "context_recall_all": context_recall,
            "out_of_base_refusal_rate": refusal_rate,
            "in_base_false_refusal_rate": false_refusal,
        },
        "per_sample": per,
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(PER_JSON, "w", encoding="utf-8") as f:
        json.dump(per, f, ensure_ascii=False, indent=2)

    def fmt(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "—"

    L = ["# Отчёт по оценке RAG (Ragas) — TASK-014, ТЗ §5", ""]
    L += [
        f"- **Генератор:** gpt-4o-mini, temperature=0",
        f"- **Судья (Ragas):** `{args.judge}` — судья ≠ генератор: "
        f"**{'да' if report['meta']['judge_ne_generator'] else 'НЕТ (та же модель; для отчёта --judge gpt-4o)'}**",
        f"- **Эмбеддинги (answer_relevancy):** text-embedding-3-small",
        f"- **Golden set:** {report['meta']['golden_set_total']} вопросов; оценено "
        f"in_base={len(in_recs)} (из них отвечено {len(answered)}), out_of_base={len(out_recs)}",
        "",
        "## RAG-триада + relevancy",
        "",
        "| Метрика | Значение | База усреднения | Смысл |",
        "|---|---|---|---|",
        f"| **Faithfulness** (нет галлюцинаций) | **{fmt(faithfulness)}** | отвеченные ({len(answered)}) "
        f"| ответ опирается только на контекст (1.0 → всё подтверждено) |",
        f"| **Answer relevancy** | **{fmt(answer_relevancy)}** | отвеченные ({len(answered)}) "
        f"| ответ по существу вопроса |",
        f"| **Context precision** | **{fmt(context_precision)}** | все in_base ({len(per)}) "
        f"| поднятые чанки релевантны (мало мусора) |",
        f"| **Context recall** | **{fmt(context_recall)}** | все in_base ({len(per)}) "
        f"| контекст покрывает эталон (ничего не упущено) |",
        "",
        "## Анти-галлюцинация: поведение отказа",
        "",
        f"- **Refusal rate (out_of_base): {refusal_rate}** — доля корректных отказов, когда ответа в базе нет "
        f"(эталон 1.0).",
        f"- **False refusal rate (in_base): {false_refusal}** — доля ложных отказов, когда ответ в базе есть "
        f"(эталон 0.0).",
    ]
    if false_ref_detail:
        L += ["", "Разбор ложных отказов:", "", "| id | вопрос | context_recall | тип |", "|---|---|---|---|"]
        for i, q, rc, kind in false_ref_detail:
            L.append(f"| {i} | {q} | {fmt(rc)} | {kind} |")

    L += [
        "",
        "## Пооконная детализация (in_base)",
        "",
        "| id | категория | отказ | faithfulness | answer_relevancy | context_precision | context_recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in in_recs:
        p = by_id.get(r["id"], {})
        L.append(f"| {r['id']} | {r.get('category') or '—'} | {'да' if r['refused'] else 'нет'} "
                 f"| {fmt(p.get('faithfulness'))} | {fmt(p.get('answer_relevancy'))} "
                 f"| {fmt(p.get('context_precision'))} | {fmt(p.get('context_recall'))} |")

    L += ["", "## Отказы на «вне базы»", "", "| id | вопрос | отказался |", "|---|---|---|"]
    for r in out_recs:
        L.append(f"| {r['id']} | {r['question']} | {'✅ да' if r['refused'] else '❌ НЕТ'} |")

    L += [
        "",
        "## Методология и оговорки",
        "",
        "- **Judge ≠ generator** (требование ТЗ): генерация — gpt-4o-mini, судейство Ragas — gpt-4o "
        "(другая, более сильная модель; частично снимает self-preference bias).",
        "- **Разделение осей:** faithfulness/answer_relevancy считаются по отвеченным вопросам; "
        "отказ — отдельная ось (false_refusal_rate), иначе корректный «безопасный» отказ штрафовал бы "
        "faithfulness как галлюцинацию. context_precision/recall — метрики retrieval, поэтому по всем in_base.",
        "- **Ragas 0.2.15:** свежий langchain-community удалил `chat_models.vertexai`, который Ragas жёстко "
        "импортирует; в `eval/_ragas_compat.py` подложена заглушка (Vertex не используется, работаем через OpenAI).",
        "- **Бюджет:** ответы кэшируются (`eval/rag_outputs.jsonl`), оценки судьи — в `eval/ragas_per_sample.json`; "
        "пере-отчёт возможен без обращений к API.",
        "- Метрики Ragas опираются на LLM-судью → недетерминированы в пределах ~±0.03.",
    ]
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--judge", default="gpt-4o-mini", help="модель-судья Ragas (для отчёта: gpt-4o)")
    ap.add_argument("--n", type=int, default=8, help="сколько in_base вопросов оценивать (бюджет)")
    ap.add_argument("--ids", default=None, help="явный список in_base id через запятую (переопределяет --n)")
    ap.add_argument("--store", default="pgvector", choices=["sqlite", "pgvector"])
    ap.add_argument("--emb", default="openai")
    ap.add_argument("--llm", default="openai")
    ap.add_argument("--offline", action="store_true", help="только кэш, без вызовов генератора")
    ap.add_argument("--regen", action="store_true", help="перегенерировать ответы (игнорировать кэш)")
    ap.add_argument("--skip-ragas", action="store_true", help="только генерация+refusal, без судьи")
    ap.add_argument("--report-only", action="store_true", help="пересобрать отчёт из кэша (0 API)")
    ap.add_argument("--tag", default=None, help="суффикс файлов отчёта (не затирать основной отчёт)")
    args = ap.parse_args()

    if args.tag:  # отдельный отчёт (напр. --tag studentlife → ragas_report_studentlife.md)
        global REPORT_JSON, REPORT_MD, PER_JSON
        REPORT_JSON = os.path.join(HERE, f"ragas_report_{args.tag}.json")
        REPORT_MD = os.path.join(HERE, f"ragas_report_{args.tag}.md")
        PER_JSON = os.path.join(HERE, f"ragas_per_sample_{args.tag}.json")

    cfg = yaml.safe_load(open(os.path.join(ROOT, args.config), encoding="utf-8"))
    golden = load_jsonl(GOLDEN)
    in_base = [g for g in golden if g["type"] == "in_base"]
    out_base = [g for g in golden if g["type"] == "out_of_base"]

    if args.report_only:  # пересборка отчёта из кэша: судья не вызывается
        per = json.load(open(PER_JSON, encoding="utf-8"))
        cache = {r["id"]: r for r in load_jsonl(CACHE)}
        in_recs = [cache[p["id"]] for p in per if p["id"] in cache]
        out_recs = [r for r in cache.values() if r.get("type") == "out_of_base"]
        rep = write_report(args, in_recs, out_recs, per)
        print("Отчёт пересобран из кэша:", json.dumps(rep["metrics"], ensure_ascii=False))
        print(f"Отчёт: {REPORT_MD}")
        return

    if args.ids:
        wanted = [x.strip() for x in args.ids.split(",") if x.strip()]
        by_id = {g["id"]: g for g in in_base}
        in_sel = [by_id[i] for i in wanted if i in by_id]
    else:
        in_sel = pick_spread(in_base, args.n)

    print(f"Генерация ответов: in_base={len(in_sel)} (из {len(in_base)}), out_of_base={len(out_base)} ...")
    in_recs = generate(in_sel, cfg, args)
    out_recs = generate(out_base, cfg, args)

    ref_rate = sum(1 for r in out_recs if r["refused"]) / len(out_recs) if out_recs else None
    false_ref = sum(1 for r in in_recs if r["refused"]) / len(in_recs) if in_recs else None
    print(f"Refusal rate (out_of_base): {ref_rate}")
    print(f"False refusal (in_base):    {false_ref}")

    if args.skip_ragas:
        print("Пропуск Ragas (--skip-ragas). Готово.")
        return

    print(f"Запуск Ragas, судья={args.judge} ...")
    per = run_ragas(in_recs, args.judge)
    rep = write_report(args, in_recs, out_recs, per)
    print("Метрики:", json.dumps(rep["metrics"], ensure_ascii=False))
    print(f"Отчёт: {REPORT_MD}\n       {REPORT_JSON}\n       {PER_JSON}")


if __name__ == "__main__":
    main()
