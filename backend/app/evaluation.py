"""Прогон эталонного набора: `python -m app.evaluation` → eval/report.json и таблица в консоли."""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from app.domain import PROCEDURE_NAMES, CanonicalTender, CompanyCard, TenderItem
from app.egrul.providers import MockProvider
from app.eis.parser import _post_process
from app.nlp.criteria import parse_criteria
from app.scoring.engine import evaluate

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.yaml"
REPORT = ROOT / "eval" / "report.json"
VERDICTS = ["go", "consider", "skip"]


def build_tender(spec: dict, now: datetime, idx: int) -> CanonicalTender:
    nmck = spec.get("nmck")
    t = CanonicalTender(
        purchase_number=f"GOLD{idx:04d}",
        law=spec.get("law", "44-FZ"),
        procedure_type=spec.get("method", "e_auction"),
        procedure_name=PROCEDURE_NAMES.get(spec.get("method", "e_auction")),
        subject=spec["subject"],
        nmck=nmck,
        customer_inn=spec.get("customer_inn"),
        delivery_place=spec.get("place"),
        submission_deadline=now + timedelta(days=spec["days"]) if "days" in spec else None,
        contract_term_days=spec.get("term_days", 45),
        app_guarantee_amount=round(nmck * spec["app_guarantee_percent"] / 100, 2) if nmck and "app_guarantee_percent" in spec else None,
        contract_guarantee_percent=spec.get("contract_guarantee_percent"),
        advance_percent=spec.get("advance_percent"),
        smp_only=spec.get("smp_only"),
        national_regime=spec.get("national_regime"),
        okpd2=spec.get("okpd2", []),
        items=[TenderItem(name=spec["subject"], okpd2=(spec.get("okpd2") or [None])[0])],
    )
    return _post_process(t, extracted_by="json")


def run(write: bool = True, golden: Path = GOLDEN, report_path: Path = REPORT) -> dict:
    data = yaml.safe_load(golden.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(data["now"])
    mock = MockProvider()
    companies: dict[str, CompanyCard] = {inn: mock.fetch(inn) for inn in mock.data}
    profiles = {}
    for key, p in data["profiles"].items():
        parsed = parse_criteria(p["criteria"], use_llm=False)
        profiles[key] = (companies.get(p["company_inn"]), parsed.preferences)

    matrix = {e: {a: 0 for a in VERDICTS} for e in VERDICTS}
    rows, timings = [], []
    for i, case in enumerate(data["cases"]):
        company, prefs = profiles[case["profile"]]
        tender = build_tender(case["tender"], now, i)
        customer = companies.get(tender.customer_inn) if tender.customer_inn else None
        started = time.perf_counter()
        result = evaluate(tender, company, customer, prefs, now=now)
        timings.append((time.perf_counter() - started) * 1000)
        ok = result.verdict == case["expected"]
        matrix[case["expected"]][result.verdict] += 1
        rows.append({"id": case["id"], "expected": case["expected"], "actual": result.verdict, "score": result.score,
                     "ok": ok, "why": case.get("why"), "reason": result.main_reason})
    correct = sum(r["ok"] for r in rows)
    critical = sum(1 for r in rows if r["expected"] == "skip" and r["actual"] == "go")
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases": len(rows),
        "correct": correct,
        "accuracy": round(correct / len(rows), 3),
        "critical_errors": critical,
        "confusion": matrix,
        "timing_ms": {"avg": round(sum(timings) / len(timings), 3), "max": round(max(timings), 3)},
        "rows": rows,
    }
    if write:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "golden"
    golden = ROOT / "eval" / f"{name}.yaml"
    report = run(golden=golden, report_path=REPORT if name == "golden" else ROOT / "eval" / f"report_{name}.json")
    print(f"Набор {name}: {report['correct']}/{report['cases']} = {report['accuracy']:.0%}, "
          f"критических ошибок (skip→go): {report['critical_errors']}, "
          f"среднее время {report['timing_ms']['avg']} мс")
    print("ожидалось \\ получено: " + "  ".join(f"{v:>8}" for v in VERDICTS))
    for e in VERDICTS:
        print(f"{e:>20}: " + "  ".join(f"{report['confusion'][e][a]:>8}" for a in VERDICTS))
    for r in report["rows"]:
        if not r["ok"]:
            print(f"  ✗ {r['id']}: ожидалось {r['expected']}, получено {r['actual']} ({r['score']}) — {r['reason']}")
    return 0 if report["accuracy"] >= 0.8 and report["critical_errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
