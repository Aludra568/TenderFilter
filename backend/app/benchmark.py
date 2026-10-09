"""Бенчмарк разбора критериев: насколько верно текст превращается в настройки.

    python -m app.benchmark                # правила (морфология + грамматики), без нейросети
    python -m app.benchmark --mode hybrid  # правила + LLM на непонятых фразах (нужна LLM)
    python -m app.benchmark --mode llm     # только LLM — для сравнения (нужна LLM)

Набор — eval/phrases.yaml, ожидания проставлены вручную. Отчёт — eval/phrases_report_<mode>.json:
точность по проверкам, доля полностью верных фраз, время на фразу.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

from app.domain import Preferences
from app.nlp.criteria import parse_criteria

ROOT = Path(__file__).resolve().parents[1] / "eval"
PHRASES = ROOT / "phrases.yaml"


def _get(prefs: dict, path: str):
    obj = prefs
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def check(prefs: Preferences, expect: dict) -> list[dict]:
    data = json.loads(prefs.model_dump_json())
    out = []
    for key, want in expect.items():
        if key.endswith("[]"):
            got = _get(data, key[:-2]) or []
            ok = all(str(w) in [str(g) for g in got] for w in want)
        elif key.endswith("~"):
            got = [str(x).lower() for x in (_get(data, key[:-1]) or [])]
            ok = all(any(w.lower() in g for g in got) for w in want)
        else:
            got = _get(data, key)
            if isinstance(want, (int, float)) and not isinstance(want, bool) and isinstance(got, (int, float)):
                ok = abs(got - want) <= max(abs(want) * 0.01, 1e-9)
            else:
                ok = got == want
        out.append({"key": key, "expected": want, "got": got, "ok": ok})
    return out


LLM_SYSTEM = (
    "Переведи критерии поставщика для отбора госзакупок в JSON. Поля: price {min_rub, max_rub}; "
    "geo {regions: {код региона РФ (2 цифры): 1.0 или 0.5 если «если выгодно»}, excluded: [коды], warehouses: [коды], "
    "required: bool}; timing {min_days_to_deadline: календарные дни}; finance {guarantee_limit_rub, advance: ignore|want|must}; "
    "conditions {laws: ['44-FZ','223-FZ'], methods: {e_auction|open_contest|quotation_request|proposal_request|"
    "single_supplier: prefer|neutral|exclude}, imports_only: bool}; customer {excluded_inns: []}; "
    "profile {keywords: [], exclude_keywords: []}. Указывай только то, что есть в тексте."
)


def llm_only(text: str, timeout: float) -> Preferences:
    from app.nlp import llm

    raw = llm.complete_json(LLM_SYSTEM, text, None, timeout) or {}
    base = json.loads(Preferences().model_dump_json())
    for section, values in raw.items():
        if isinstance(values, dict) and isinstance(base.get(section), dict):
            base[section].update(values)
    try:
        return Preferences.model_validate(base)
    except Exception:  # noqa: BLE001 — невалидный ответ модели считается промахом
        return Preferences()


def run(mode: str = "rules", write: bool = True, timeout: float = 30.0, dataset: str = "phrases") -> dict:
    data = yaml.safe_load((ROOT / f"{dataset}.yaml").read_text(encoding="utf-8"))
    rows, times = [], []
    for item in data["phrases"]:
        started = time.perf_counter()
        if mode == "llm":
            prefs = llm_only(item["text"], timeout)
        else:
            prefs = parse_criteria(item["text"], use_llm=(mode == "hybrid"), timeout=timeout).preferences
        times.append((time.perf_counter() - started) * 1000)
        checks = check(prefs, item["expect"])
        rows.append({"text": item["text"], "ok": all(c["ok"] for c in checks), "checks": checks})
    total_checks = sum(len(r["checks"]) for r in rows)
    ok_checks = sum(c["ok"] for r in rows for c in r["checks"])
    report = {
        "mode": mode,
        "dataset": dataset,
        "phrases": len(rows),
        "phrases_fully_correct": sum(r["ok"] for r in rows),
        "phrase_accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "check_accuracy": round(ok_checks / total_checks, 3),
        "checks": total_checks,
        "ms_median": round(statistics.median(times), 2),
        "ms_max": round(max(times), 2),
        "errors": [{"text": r["text"], "failed": [c for c in r["checks"] if not c["ok"]]} for r in rows if not r["ok"]],
    }
    if write:
        (ROOT / f"{dataset}_report_{mode}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                                          encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "hybrid", "llm"], default="rules")
    ap.add_argument("--set", default="phrases", help="phrases (набор для доработки) или phrases_holdout (отложенный)")
    args = ap.parse_args()
    r = run(args.mode, dataset=args.set)
    print(f"Разбор критериев [{r['mode']}, {r['dataset']}]: фраз полностью верно {r['phrases_fully_correct']}/{r['phrases']} "
          f"({r['phrase_accuracy']:.0%}), проверок верно {r['check_accuracy']:.0%} из {r['checks']}, "
          f"медиана {r['ms_median']} мс на фразу")
    for e in r["errors"]:
        print(f"  ✗ «{e['text']}»")
        for c in e["failed"]:
            print(f"      {c['key']}: ожидалось {c['expected']}, получено {c['got']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
