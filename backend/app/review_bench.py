"""Бенчмарк проверки ИИ на реальных закупках: помогает ли нейросеть алгоритму или мешает.

    LLM_PROVIDER=ollama LLM_MODEL=qwen2.5:3b python -m app.review_bench

На каждом случае eval/golden_real.yaml: вердикт алгоритма → проверка ИИ → итоговый вердикт.
Считаем: сколько раз ИИ исправил ошибку алгоритма, сколько раз испортил верный вердикт,
сколько замечаний отброшено из-за выдуманных цитат, и время. Отчёт — eval/review_report_<модель>.json.
"""

import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from app.config import get_settings
from app.egrul.providers import MockProvider
from app.evaluation import build_tender
from app.nlp.criteria import parse_criteria
from app.scoring import review
from app.scoring.engine import evaluate

ROOT = Path(__file__).resolve().parents[1] / "eval"


def run(timeout: float = 60.0) -> dict:
    data = yaml.safe_load((ROOT / "golden_real.yaml").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(data["now"])
    mock = MockProvider()
    profiles = {k: (mock.fetch(p["company_inn"]) if p["company_inn"] in mock.data else None,
                    parse_criteria(p["criteria"], use_llm=False).preferences, p["criteria"])
                for k, p in data["profiles"].items()}
    rows, times = [], []
    for i, case in enumerate(data["cases"]):
        company, prefs, criteria = profiles[case["profile"]]
        t = build_tender(case["tender"], now, i)
        res = evaluate(t, company, None, prefs, now=now).model_dump()
        started = time.perf_counter()
        rv = review.review(t, res, criteria, timeout=timeout)
        times.append((time.perf_counter() - started) * 1000)
        rows.append({"id": case["id"], "expected": case["expected"], "algorithm": rv.algorithm_verdict,
                     "final": rv.final_verdict, "status": rv.status,
                     "unverified": sum(1 for x in rv.issues if not x.verified),
                     "issues": [{"problem": x.problem, "quote": x.quote, "verified": x.verified} for x in rv.issues][:3]})
    n = len(rows)
    algo_ok = sum(r["algorithm"] == r["expected"] for r in rows)
    final_ok = sum(r["final"] == r["expected"] for r in rows)
    report = {
        "model": get_settings().llm_model,
        "cases": n,
        "algorithm_accuracy": round(algo_ok / n, 3),
        "with_review_accuracy": round(final_ok / n, 3),
        "changed": sum(r["algorithm"] != r["final"] for r in rows),
        "fixed": sum(r["algorithm"] != r["expected"] and r["final"] == r["expected"] for r in rows),
        "broken": sum(r["algorithm"] == r["expected"] and r["final"] != r["expected"] for r in rows),
        "unanswered": sum(r["status"] == "unavailable" for r in rows),
        "hallucinated_quotes": sum(r["unverified"] for r in rows),
        "ms_median": round(statistics.median(times)), "ms_p95": round(sorted(times)[int(n * 0.95)]),
        "rows": rows,
    }
    name = get_settings().llm_model.replace(":", "-")
    (ROOT / f"review_report_{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    r = run()
    print(f"Проверка ИИ [{r['model']}] на {r['cases']} реальных закупках: алгоритм {r['algorithm_accuracy']:.0%} → "
          f"с проверкой {r['with_review_accuracy']:.0%}; изменено {r['changed']}, исправлено {r['fixed']}, "
          f"испорчено {r['broken']}; без ответа {r['unanswered']}; выдуманных цитат отброшено {r['hallucinated_quotes']}; "
          f"время медиана {r['ms_median']} мс, p95 {r['ms_p95']} мс")
    return 0


if __name__ == "__main__":
    sys.exit(main())
