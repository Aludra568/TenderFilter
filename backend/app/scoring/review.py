"""Второе мнение LLM: нейросеть проверяет оценку алгоритма и автоматически корректирует вердикт.

Алгоритм даёт оценку и вердикт. Затем LLM получает извещение, критерии пользователя и разбор
по факторам и отвечает, согласна ли она. Её ответ проходит через ограничители:

1. Процент оценки LLM не меняет никогда — он остаётся воспроизводимым и объяснимым.
2. Стоп-факторы — проверенные факты (срок истёк, только СМП и т. п.); LLM их не отменяет.
3. Каждое возражение LLM обязано опираться на дословную цитату из извещения или из критериев.
   Цитата ищется в исходном тексте; не нашлась — возражение считается неподтверждённым
   (защита от выдумок модели) и только показывается.
4. Подтверждённое возражение сдвигает вердикт к мнению модели, но не больше чем на одну ступень
   (Участвовать ↔ Рассмотреть ↔ Не участвовать): одна ошибка модели не превратит «Участвовать»
   в «Не участвовать».
5. Не ответила за отведённое время — работает только алгоритм, общий лимит 10 с не нарушается.
"""

import json
import re
import time

from pydantic import BaseModel, Field

from app.domain import VERDICT_NAMES, CanonicalTender
from app.nlp import llm

FACTOR_KEYS = ["profile", "price", "geo", "timing", "finance", "conditions", "customer", "other"]

SYSTEM = (
    "Ты — опытный тендерный специалист и проверяешь работу алгоритма скоринга закупок 44-ФЗ/223-ФЗ. "
    "Тебе дают извещение, критерии поставщика и оценку алгоритма по факторам. "
    "Найди, где алгоритм мог ошибиться: не заметил важное в тексте закупки или неверно применил критерий. "
    "Не пересчитывай баллы. Каждое возражение подтверди ДОСЛОВНОЙ цитатой (3–12 слов) из извещения "
    "или из критериев. Если ошибок нет — agree=true и пустой список issues. Ответ — только JSON."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "agree": {"type": "boolean"},
        "suggested_verdict": {"type": "string", "enum": ["go", "consider", "skip"]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string", "enum": FACTOR_KEYS},
                    "problem": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["factor", "problem", "quote"],
            },
        },
    },
    "required": ["agree", "issues"],
}


class ReviewIssue(BaseModel):
    factor: str
    problem: str
    quote: str
    verified: bool  # цитата найдена в извещении или критериях


class Review(BaseModel):
    status: str  # agree | doubt | unconfirmed | unavailable
    status_name: str
    algorithm_verdict: str
    final_verdict: str
    changed: bool = False
    suggested_verdict: str | None = None
    issues: list[ReviewIssue] = Field(default_factory=list)
    note: str
    elapsed_ms: float = 0.0


STATUS_NAMES = {
    "agree": "ИИ согласен с алгоритмом",
    "doubt": "ИИ скорректировал вердикт",
    "unconfirmed": "ИИ сомневается, но не подтвердил цитатой",
    "unavailable": "Проверка ИИ не подключена",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[«»\"'“”„]", "", text.lower().replace("ё", "е"))).strip()


def tender_text(t: CanonicalTender) -> str:
    parts = [t.subject, t.procedure_name or "", t.customer_name or "", t.delivery_place or "",
             t.delivery_region_name or "", *t.requirements, *(i.name for i in t.items[:50])]
    return "\n".join(p for p in parts if p)


def quote_found(quote: str, *texts: str) -> bool:
    q = _norm(quote)
    return len(q) >= 4 and any(q in _norm(t) for t in texts if t)


def _prompt(t: CanonicalTender, result: dict, criteria_text: str | None) -> str:
    factors = [{"фактор": f["key"], "название": f["label"], "балл": f["score"], "вес": f["weight"],
                "причины": f["reasons"][:3]} for f in result["factors"]]
    data = {
        "извещение": {
            "номер": t.purchase_number, "закон": t.law, "способ": t.procedure_name or t.procedure_type,
            "предмет": t.subject, "НМЦК": t.nmck, "заказчик": t.customer_name, "место поставки": t.delivery_place,
            "окончание подачи": t.submission_deadline.isoformat() if t.submission_deadline else None,
            "только СМП": t.smp_only, "нацрежим": t.national_regime, "требования": t.requirements[:10],
            "позиции": [i.name for i in t.items[:15]],
        },
        "критерии поставщика": criteria_text or "(заданы настройками профиля, см. причины факторов)",
        "оценка алгоритма": {"процент": result["score"], "вердикт": result["verdict_name"],
                             "стоп-факторы": result["stops"], "факторы": factors},
    }
    return json.dumps(data, ensure_ascii=False, default=str)


def review(tender: CanonicalTender, result: dict, criteria_text: str | None = None,
           timeout: float = 3.0, complete=None) -> Review:
    """result — ScoreResult в виде словаря. complete — подмена клиента LLM (для тестов)."""
    started = time.perf_counter()
    algo = result["verdict"]
    base = dict(algorithm_verdict=algo, final_verdict=algo)
    raw = None
    if timeout > 0.3:
        raw = (complete or llm.complete_json)(SYSTEM, _prompt(tender, result, criteria_text), SCHEMA, timeout)
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    if not isinstance(raw, dict) or "agree" not in raw:
        return Review(status="unavailable", status_name=STATUS_NAMES["unavailable"], elapsed_ms=elapsed,
                      note="Оценка посчитана алгоритмом; нейросеть не ответила или не подключена.", **base)

    text = tender_text(tender)
    issues = []
    for it in (raw.get("issues") or [])[:5]:
        if not isinstance(it, dict) or not it.get("problem"):
            continue
        quote = str(it.get("quote") or "")
        issues.append(ReviewIssue(factor=it.get("factor") if it.get("factor") in FACTOR_KEYS else "other",
                                  problem=str(it["problem"])[:400], quote=quote[:300],
                                  verified=quote_found(quote, text, criteria_text or "")))
    suggested = raw.get("suggested_verdict") if raw.get("suggested_verdict") in ("go", "consider", "skip") else None
    verified = [i for i in issues if i.verified]

    if raw.get("agree") and not verified:
        return Review(status="agree", status_name=STATUS_NAMES["agree"], issues=issues, suggested_verdict=suggested,
                      elapsed_ms=elapsed, note="Нейросеть проверила разбор и не нашла ошибок алгоритма.", **base)
    if not verified:
        return Review(status="unconfirmed", status_name=STATUS_NAMES["unconfirmed"], issues=issues,
                      suggested_verdict=suggested, elapsed_ms=elapsed,
                      note="Возражения нейросети не подтверждены цитатами из извещения — вердикт алгоритма оставлен.",
                      **base)
    if result["stops"]:
        return Review(status="doubt", status_name=STATUS_NAMES["doubt"], issues=issues, suggested_verdict=suggested,
                      elapsed_ms=elapsed,
                      note="Сработал стоп-фактор — это проверенный факт, нейросеть его не отменяет. Возражение показано для сведения.",
                      **base)
    final = corrected_verdict(algo, suggested)
    if final == algo:
        note = f"Нейросеть привела подтверждённое замечание, но вердикт «{VERDICT_NAMES[algo]}» оставлен."
    else:
        note = (f"Алгоритм: «{VERDICT_NAMES[algo]}» → после проверки ИИ: «{VERDICT_NAMES[final]}». "
                "Процент оценки посчитан алгоритмом и не изменён.")
    return Review(status="doubt", status_name=STATUS_NAMES["doubt"], issues=issues, suggested_verdict=suggested,
                  algorithm_verdict=algo, final_verdict=final, changed=final != algo, elapsed_ms=elapsed, note=note)


LADDER = ["skip", "consider", "go"]


def corrected_verdict(algo: str, suggested: str | None) -> str:
    """Не больше одной ступени к мнению модели; без явного мнения возражение = на ступень ниже."""
    pos = LADDER.index(algo)
    target = LADDER.index(suggested) if suggested in LADDER else pos - 1
    step = (target > pos) - (target < pos)
    return LADDER[max(0, min(len(LADDER) - 1, pos + step))]


def apply(result: dict, rv: Review) -> dict:
    """Записать второе мнение в результат: вердикт меняется не больше чем на ступень, процент — никогда."""
    result = {**result, "review": rv.model_dump()}
    if rv.changed:
        result["verdict"] = rv.final_verdict
        result["verdict_name"] = VERDICT_NAMES[rv.final_verdict]
        first = next(i for i in rv.issues if i.verified)
        result["flags"] = [*result.get("flags", []), f"Проверка ИИ: {first.problem} («{first.quote}»)"]
    return result
