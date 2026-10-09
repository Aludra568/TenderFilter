"""Нагрузочный тест: сколько извещений в секунду система разбирает и оценивает.

    python -m app.loadtest            # 1000 извещений (XML демо-генератора с разными параметрами)

Меряются отдельно: разбор XML ЕИС, оценка движком (с профилем, разобранным из текста) и вся цепочка.
Отчёт — eval/load_report.json. ЕГРЮЛ не участвует (данные компании из кэша), чтобы мерить сам алгоритм.
"""

import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.egrul.providers import MockProvider
from app.eis.parser import parse_bytes
from app.nlp.criteria import parse_criteria
from app.scoring.engine import evaluate
from app.seed.demo import DEMO_COMPANY_INN, DEMO_CRITERIA, demo_files

REPORT = Path(__file__).resolve().parents[1] / "eval" / "load_report.json"


def _pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * p))], 3)


def run(n: int = 1000) -> dict:
    now = datetime.now(timezone.utc)
    files = demo_files(now)
    company = MockProvider().fetch(DEMO_COMPANY_INN)
    prefs = parse_criteria(DEMO_CRITERIA, use_llm=False).preferences
    parse_ms, score_ms = [], []
    started = time.perf_counter()
    verdicts: dict[str, int] = {}
    for i in range(n):
        name, content = files[i % len(files)]
        t0 = time.perf_counter()
        tender = parse_bytes(content, name)
        t1 = time.perf_counter()
        result = evaluate(tender, company, None, prefs, now=now)
        t2 = time.perf_counter()
        parse_ms.append((t1 - t0) * 1000)
        score_ms.append((t2 - t1) * 1000)
        verdicts[result.verdict] = verdicts.get(result.verdict, 0) + 1
    total_s = time.perf_counter() - started
    report = {
        "notices": n,
        "total_seconds": round(total_s, 2),
        "notices_per_second": round(n / total_s, 1),
        "parse_ms": {"median": round(statistics.median(parse_ms), 3), "p95": _pct(parse_ms, 0.95), "max": round(max(parse_ms), 3)},
        "score_ms": {"median": round(statistics.median(score_ms), 3), "p95": _pct(score_ms, 0.95), "max": round(max(score_ms), 3)},
        "verdicts": verdicts,
        "generated_at": now.isoformat(timespec="seconds"),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    r = run(n)
    print(f"{r['notices']} извещений за {r['total_seconds']} с — {r['notices_per_second']} в секунду. "
          f"Разбор XML: медиана {r['parse_ms']['median']} мс, p95 {r['parse_ms']['p95']} мс. "
          f"Оценка: медиана {r['score_ms']['median']} мс, p95 {r['score_ms']['p95']} мс.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
