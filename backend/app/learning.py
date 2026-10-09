"""Самообучение на отметках пользователя: подбор важности факторов и порогов под его решения.

Пользователь отмечает в карточке «вердикт верный» или «неверный, правильно — …». По этим меткам
локальный поиск (покоординатный подъём) пробует изменить важность каждого фактора на ±1 и пороги
на ±5 и оставляет изменение, только если оно увеличивает число совпадений с решениями пользователя.
Шагов немного и каждый понятен человеку: «важность цены 3 → 4: совпадение 6 из 10 → 8 из 10».
Это не чёрный ящик — система предлагает, пользователь применяет.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import services
from app.domain import Preferences
from app.models import Feedback, Profile, Score, Tender
from app.scoring.factors import FACTORS

MIN_LABELS = 3
LABELS = {f.key: f.label for f in FACTORS}


def collect(db: Session, profile: Profile) -> list[tuple]:
    """(закупка, ожидаемый вердикт) по последней отметке на каждую оценку."""
    latest: dict[int, Feedback] = {}
    for fb in db.scalars(select(Feedback).order_by(Feedback.id)):
        latest[fb.score_id] = fb
    out, seen = [], set()
    for score_id, fb in latest.items():
        score = db.get(Score, score_id)
        if score is None:
            continue
        expected = score.verdict if fb.correct else fb.expected_verdict
        if expected not in ("go", "consider", "skip") or score.tender_id in seen:
            continue
        row = db.get(Tender, score.tender_id)
        if row is None:
            continue
        seen.add(score.tender_id)
        out.append((row, expected))
    return out


def _agreement(db: Session, labels, prefs: Preferences, company, profile_id: int) -> int:
    hits = 0
    for row, expected in labels:
        r = services.compute(db, services.tender_model(row), company, prefs,
                             committed=services.committed(db, profile_id, row.id))
        hits += r.verdict == expected
    return hits


def _candidates(prefs: Preferences, cut_points: list[int]):
    for f in FACTORS:
        cur = getattr(prefs, f.key).importance
        for d in (1, -1):
            new = cur + d
            if 0 <= new <= 5 and not prefs.weights:
                p = prefs.model_copy(deep=True)
                getattr(p, f.key).importance = new
                yield p, {"kind": "importance", "factor": f.key, "label": f.label, "from": cur, "to": new}
        if prefs.weights and f.key in prefs.weights:
            for k in (1.5, 1 / 1.5):
                p = prefs.model_copy(deep=True)
                p.weights[f.key] *= k
                total = sum(p.weights.values())
                p.weights = {key: round(v / total, 4) for key, v in p.weights.items()}
                yield p, {"kind": "weight", "factor": f.key, "label": f.label,
                          "from": round(prefs.weights[f.key], 3), "to": p.weights[f.key]}
    # Пороги: кандидаты — точки между оценками отмеченных закупок (как в решающем пне),
    # а не фиксированный шаг: так порог встаёт ровно туда, где проходит граница решений пользователя.
    for name in ("go", "consider"):
        cur = getattr(prefs.thresholds, name)
        for new in cut_points:
            if new == cur or not (10 <= new <= 100):
                continue
            if name == "consider" and new >= prefs.thresholds.go or name == "go" and new <= prefs.thresholds.consider:
                continue
            p = prefs.model_copy(deep=True)
            setattr(p.thresholds, name, new)
            yield p, {"kind": "threshold", "factor": name,
                      "label": "Порог «Участвовать»" if name == "go" else "Порог «Рассмотреть»", "from": cur, "to": new}


def suggest(db: Session, profile: Profile, max_steps: int = 4) -> dict:
    labels = collect(db, profile)
    pv = services.current_version(db, profile)
    prefs = Preferences.model_validate(pv.preferences)
    if len(labels) < MIN_LABELS:
        return {"labels": len(labels), "enough": False,
                "message": f"Нужно хотя бы {MIN_LABELS} отметки «верно / неверно» в карточках закупок — сейчас {len(labels)}."}
    company = services.profile_company(db, profile)
    base = best = _agreement(db, labels, prefs, company, profile.id)
    steps = []
    for _ in range(max_steps):
        found = None
        scores = [services.compute(db, services.tender_model(row), company, prefs,
                                   committed=services.committed(db, profile.id, row.id)).score for row, _ in labels]
        cut_points = sorted({min(100, int(sc) + 1) for sc in scores} | {max(10, int(sc)) for sc in scores})
        for cand, change in _candidates(prefs, cut_points):
            score = _agreement(db, labels, cand, company, profile.id)
            if score > best:
                best, found = score, (cand, change, score)
        if not found:
            break
        prefs, change, score = found
        steps.append({**change, "agreement": score})
    return {"labels": len(labels), "enough": True, "baseline": base, "suggested": best,
            "baseline_rate": round(base / len(labels), 3), "suggested_rate": round(best / len(labels), 3),
            "steps": steps, "preferences": prefs if steps else None,
            "message": "Текущие настройки уже лучше всего совпадают с вашими отметками." if not steps else None}
