"""Движок скоринга: детерминированный, без LLM, миллисекунды на закупку."""

import time
from datetime import datetime, timezone

from pydantic import BaseModel

from app.domain import VERDICT_NAMES, CanonicalTender, CompanyCard, CustomRule, Preferences
from app.scoring.factors import FACTORS, Context, FactorResult


class FactorOut(BaseModel):
    key: str
    label: str
    score: float | None
    active: bool
    weight: float
    points: float
    max_points: float
    value: str
    reasons: list[str]
    stop: str | None
    sources: list[dict]


class RuleOut(BaseModel):
    id: str
    label: str
    effect: str
    points: float


class ScoreResult(BaseModel):
    score: float
    verdict: str
    verdict_name: str
    completeness: float
    stops: list[str]
    flags: list[str]
    main_reason: str
    factors: list[FactorOut]
    rules: list[RuleOut]
    elapsed_ms: float


def _field_value(tender: CanonicalTender, path: str):
    obj = tender.model_dump()
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _check_rule(rule: CustomRule, tender: CanonicalTender) -> bool | None:
    v = _field_value(tender, rule.field)
    if v is None:
        return None
    target = rule.value
    try:
        if rule.op == "eq":
            return v == target
        if rule.op == "ne":
            return v != target
        if rule.op in ("gt", "gte", "lt", "lte"):
            a, b = float(v), float(target)
            return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[rule.op]
        if rule.op in ("in", "not_in"):
            values = target if isinstance(target, list) else [target]
            hit = any(x in values for x in v) if isinstance(v, list) else v in values
            return hit if rule.op == "in" else not hit
        if rule.op in ("contains", "not_contains"):
            hay = " ".join(map(str, v)) if isinstance(v, list) else str(v)
            hit = str(target).lower() in hay.lower()
            return hit if rule.op == "contains" else not hit
    except (TypeError, ValueError):
        return None
    return None


def evaluate(
    tender: CanonicalTender,
    company: CompanyCard | None,
    customer: CompanyCard | None,
    prefs: Preferences,
    now: datetime | None = None,
    committed: tuple[float, int] = (0.0, 0),
) -> ScoreResult:
    started = time.perf_counter()
    ctx = Context(tender=tender, company=company, customer=customer, prefs=prefs, now=now or datetime.now(timezone.utc),
                  committed=committed[0], committed_count=committed[1])

    results: list[FactorResult] = []
    for f in FACTORS:
        settings = getattr(prefs, f.key)
        res = f.fn(ctx)
        if settings.importance == 0 or not res.active:
            res.weight = 0.0
        elif prefs.weights:
            res.weight = 100 * prefs.weights.get(f.key, 0.0)
        else:
            res.weight = f.base_weight * settings.importance / 3
        results.append(res)

    total_w = sum(r.weight for r in results)
    known_w = sum(r.weight for r in results if r.score is not None)
    score = 100 * sum(r.weight * r.score for r in results if r.score is not None) / known_w if known_w else 0.0
    completeness = known_w / total_w if total_w else 1.0
    for r in results:
        r.points = round(100 * r.weight * (r.score or 0) / known_w, 1) if known_w and r.score is not None else 0.0

    stops = [r.stop for r in results if r.stop]
    rules_out: list[RuleOut] = []
    for rule in prefs.custom_rules:
        hit = _check_rule(rule, tender)
        if not hit:
            continue
        if rule.mode == "stop":
            stops.append(rule.label)
            rules_out.append(RuleOut(id=rule.id, label=rule.label, effect="stop", points=0))
        else:
            delta = rule.points if rule.mode == "bonus" else -rule.points
            score += delta
            rules_out.append(RuleOut(id=rule.id, label=rule.label, effect=rule.mode, points=delta))
    score = max(0.0, min(100.0, score))

    # Красные флаги: ключевой фактор (вес ≥ 15) на нуле или риск со стороны заказчика.
    flags = [r.flag for r in results if r.flag]
    zero_keys = [r for r in results if r.weight >= 15 and r.score == 0]
    flags += [f"{r.label}: {r.reasons[0]}" if r.reasons else f"{r.label} — 0 баллов" for r in zero_keys]

    th = prefs.thresholds
    if stops:
        verdict, score = "skip", 0.0
    elif len(zero_keys) >= 2:
        verdict = "skip"
    elif score >= th.go:
        verdict = "go"
    elif score >= th.consider:
        verdict = "consider"
    else:
        verdict = "skip"
    # Мало данных в извещении: оцениваем по тому, что есть, но «Участвовать» не ставим —
    # решение принимается автоматически, без отправки человеку на ручную проверку.
    if completeness < th.min_completeness and not stops:
        missing = [r.label.lower() for r in results if r.weight > 0 and r.score is None]
        flags.append(f"Мало данных в извещении: нет — {', '.join(missing)}; оценка по {round(completeness * 100)}% данных")
    if verdict == "go" and flags:
        verdict = "consider"

    active = [r for r in results if r.weight > 0 and r.score is not None]
    if stops:
        main = stops[0]
    elif flags and verdict != "go":
        main = "; ".join(flags[:2])
    else:
        best = max(active, key=lambda r: r.weight * r.score, default=None)
        worst = min(active, key=lambda r: r.score, default=None)
        bits = []
        if best and best.reasons:
            bits.append(best.reasons[0])
        if worst and worst is not best and worst.score < 0.7 and worst.reasons:
            bits.append(worst.reasons[0])
        main = ". Минус: ".join(bits) if len(bits) == 2 else (bits[0] if bits else "")

    factors_out = [
        FactorOut(
            key=r.key, label=r.label, score=r.score, active=r.active and r.weight > 0, weight=round(r.weight, 2),
            points=r.points, max_points=round(100 * r.weight / known_w, 1) if known_w and r.score is not None else 0.0,
            value=r.value, reasons=r.reasons, stop=r.stop,
            sources=[{"field": s.field, "path": s.path, "raw": s.raw} for s in r.sources],
        )
        for r in results
    ]
    return ScoreResult(
        score=round(score, 1),
        verdict=verdict,
        verdict_name=VERDICT_NAMES[verdict],
        completeness=round(completeness, 3),
        stops=stops,
        flags=flags,
        main_reason=main,
        factors=factors_out,
        rules=rules_out,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )
