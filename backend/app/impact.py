"""Сколько ручной работы снимает система — измерено на реальных извещениях, без интервью.

    python -m app.impact

198 реальных извещений ЕИС × типовые профили поставщиков: какая доля закупок решается автоматически
(«Не участвовать» с понятной причиной), какая требует внимания («Рассмотреть») и какая — «Участвовать».
Отдельно — доля, отсечённая стоп-факторами: там человеку не нужно ничего читать.
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.corpus import CORPUS
from app.customer import reference_profiles
from app.eis.parser import parse_bytes
from app.scoring.engine import evaluate

REPORT = Path(__file__).resolve().parents[1] / "eval" / "impact_report.json"


def run() -> dict:
    tenders = [parse_bytes(f.read_bytes(), f.name) for f in sorted(CORPUS.glob("*.xml"))]
    # Оцениваем на момент публикации извещения — как увидел бы его поставщик в день выхода.
    rows, reasons = [], Counter()
    for t in tenders:
        now = t.published_at or datetime.now(timezone.utc)
        for p in reference_profiles():
            r = evaluate(t, p.company, None, p.preferences, now=now)
            profile = next(f for f in r.factors if f.key == "profile")
            on_profile = (profile.score or 0) >= 0.4  # закупка прошла бы поиск по профилю/ключевым словам
            rows.append((p.name, r.verdict, bool(r.stops), on_profile))
            if r.stops and on_profile:
                reasons[r.stops[0].split(":")[0][:60]] += 1
    # Главная мера — среди профильных закупок: их поставщик и так нашёл бы поиском и читал бы вручную.
    rel = [x for x in rows if x[3]]
    n = len(rel) or 1
    verdicts = Counter(v for _, v, _, _ in rel)
    stops = sum(1 for _, _, s, _ in rel if s)
    report = {
        "notices": len(tenders),
        "pairs": len(rows),
        "on_profile_pairs": len(rel),
        "auto_skip": round(verdicts["skip"] / n, 3),
        "stop_factor": round(stops / n, 3),
        "consider": round(verdicts["consider"] / n, 3),
        "go": round(verdicts["go"] / n, 3),
        "top_stop_reasons": reasons.most_common(6),
        "note": "Профили — типовые (IT, стройматериалы, медизделия); у реального поставщика доля зависит от его профиля.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    r = run()
    print(f"{r['notices']} реальных извещений × профили: профильных пар {r['on_profile_pairs']} из {r['pairs']}. Среди профильных: "
          f"сразу «Не участвовать» — {r['auto_skip']:.0%} (из них по стоп-фактору {r['stop_factor']:.0%}), "
          f"«Рассмотреть» — {r['consider']:.0%}, «Участвовать» — {r['go']:.0%}")
    for reason, k in r["top_stop_reasons"]:
        print(f"  {k:>4} × {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
