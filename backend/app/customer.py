"""Сторона заказчика: та же система защищает и его.

1. Проверка своей закупки до публикации: сроки подачи против минимумов 44-ФЗ, условия проекта
   контракта (оплата, приёмка, санкции), марки без «или эквивалент» — то, на что пишут жалобы в ФАС.
2. Прогноз интереса поставщиков: закупка прогоняется через движок по профилям поставщиков,
   и видно, сколько из них сказали бы «Участвовать». Мало желающих — риск несостоявшейся закупки.
3. Проверка участников по ИНН: статус и возраст по ЕГРЮЛ, МСП для закупок «только для СМП»,
   профильный ОКВЭД, антидемпинговые меры при снижении цены на 25% и больше.
"""

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.domain import PROCEDURE_NAMES, CanonicalTender, CompanyCard, Finding, Preferences
from app.reference.okved import match_okved_okpd

# Минимальный срок подачи заявок, календарные дни: (НМЦК ≤ 300 млн, больше 300 млн). 44-ФЗ, ст. 48–50.
MIN_DAYS = {
    "e_auction": (7, 15, "ст. 49 44-ФЗ"),
    "open_contest": (11, 20, "ст. 48 44-ФЗ"),
    "quotation_request": (4, 4, "ст. 50 44-ФЗ (4 рабочих дня)"),
}
REFERENCE_PROFILES = Path(__file__).resolve().parents[1] / "eval" / "golden.yaml"


def check_notice(t: CanonicalTender) -> list[Finding]:
    """Риски закупки для заказчика: что могут обжаловать и что отпугнёт поставщиков."""
    out: list[Finding] = []
    if t.law == "44-FZ" and t.published_at and t.submission_deadline and t.procedure_type in MIN_DAYS:
        small, big, law = MIN_DAYS[t.procedure_type]
        need = big if (t.nmck or 0) > 300_000_000 else small
        pub = t.published_at if t.published_at.tzinfo else t.published_at.replace(tzinfo=timezone.utc)
        dl = t.submission_deadline if t.submission_deadline.tzinfo else t.submission_deadline.replace(tzinfo=timezone.utc)
        days = (dl - pub).total_seconds() / 86400
        name = PROCEDURE_NAMES.get(t.procedure_type, t.procedure_type)
        if days < need:
            out.append(Finding(code="deadline_short", side="customer", severity="high",
                               title=f"Срок подачи {days:.1f} дн. — меньше минимума {need} дн.".replace(".", ","),
                               detail=f"Для способа «{name}» срок короче установленного — основание для жалобы и отмены закупки.",
                               law=law))
        else:
            out.append(Finding(code="deadline_ok", side="customer", severity="info",
                               title=f"Срок подачи {int(days)} дн. — не меньше минимума {need} дн.", detail=name, law=law))
    if not t.okpd2 and not t.ktru:
        out.append(Finding(code="no_okpd", side="customer", severity="warn", title="Не указаны коды ОКПД 2 / КТРУ",
                           detail="Поставщики не найдут закупку по кодам — меньше заявок."))
    if t.contract:
        out += [x for x in t.contract.findings if x.side in ("customer", "both")]
    return out


class ReferenceProfile(BaseModel):
    key: str
    name: str
    company: CompanyCard | None
    preferences: Preferences


@lru_cache(maxsize=1)
def reference_profiles() -> list[ReferenceProfile]:
    """Типовые профили поставщиков для прогноза интереса (на демо — из эталонного набора)."""
    from app.egrul.providers import MockProvider
    from app.nlp.criteria import parse_criteria

    data = yaml.safe_load(REFERENCE_PROFILES.read_text(encoding="utf-8"))
    mock = MockProvider()
    names = {"it_sib": "IT-поставщик, Сибирь", "build_tomsk": "Стройматериалы, Томск", "med_msk": "Медизделия, Москва"}
    out = []
    for key, p in data["profiles"].items():
        if key not in names:
            continue
        company = mock.fetch(p["company_inn"]) if p["company_inn"] in mock.data else None
        prefs = parse_criteria(p["criteria"], use_llm=False).preferences
        out.append(ReferenceProfile(key=key, name=names[key], company=company, preferences=prefs))
    return out


def supplier_interest(t: CanonicalTender, profiles: list[ReferenceProfile] | None = None,
                      now: datetime | None = None) -> dict:
    from app.scoring.engine import evaluate

    rows = []
    for p in profiles if profiles is not None else reference_profiles():
        r = evaluate(t, p.company, None, p.preferences, now=now)
        rows.append({"profile": p.name, "score": r.score, "verdict": r.verdict, "verdict_name": r.verdict_name,
                     "reason": r.stops[0] if r.stops else r.main_reason})
    counts = {v: sum(1 for x in rows if x["verdict"] == v) for v in ("go", "consider", "skip")}
    return {"profiles": rows, "counts": counts, "total": len(rows),
            "note": "Прогноз по типовым профилям поставщиков. На площадке это будут реальные профили — "
                    "чем меньше «Участвовать», тем выше риск, что закупка не состоится."}


class Participant(BaseModel):
    inn: str
    price: float | None = None


def check_participant(t: CanonicalTender, card: CompanyCard | None, p: Participant,
                      now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    findings: list[Finding] = []
    if card is None:
        findings.append(Finding(code="not_found", side="customer", severity="high", title="Нет в ЕГРЮЛ",
                                detail="Организация с таким ИНН не найдена — проверьте реквизиты."))
    else:
        if card.status not in ("ACTIVE", "UNKNOWN"):
            findings.append(Finding(code="inactive", side="customer", severity="high",
                                    title="Организация недействующая или ликвидируется",
                                    detail="Контракт с ней может быть не исполнен."))
        if card.registration_date:
            reg = card.registration_date if card.registration_date.tzinfo else card.registration_date.replace(tzinfo=timezone.utc)
            months = (now - reg).days / 30.4
            if months < 12:
                findings.append(Finding(code="young", side="customer", severity="warn",
                                        title=f"Зарегистрирована {months:.0f} мес. назад".replace(".", ","),
                                        detail="Мало истории — проверьте опыт и отзывы."))
        if t.smp_only and card.is_msp is False:
            findings.append(Finding(code="not_smp", side="customer", severity="high", title="Не субъект МСП",
                                    detail="Закупка только для СМП — заявка такого участника подлежит отклонению.",
                                    law="ст. 30 44-ФЗ"))
        if t.okpd2 and card.okved_codes:
            score, _, _ = match_okved_okpd(card.okved_codes, t.okpd2)
            if score < 0.4:
                findings.append(Finding(code="no_okved", side="customer", severity="warn",
                                        title="Нет профильного ОКВЭД",
                                        detail="Виды деятельности по ЕГРЮЛ не связаны с предметом закупки."))
    if p.price and t.nmck and p.price <= t.nmck * 0.75:
        drop = round(100 * (1 - p.price / t.nmck))
        measure = ("обеспечение исполнения контракта в 1,5 раза больше" if t.nmck > 15_000_000
                   else "обеспечение в 1,5 раза больше или информация о добросовестности")
        findings.append(Finding(code="dumping", side="customer", severity="warn",
                                title=f"Снижение цены на {drop}% — антидемпинговые меры",
                                detail=f"Требуется {measure}.", law="ст. 37 44-ФЗ"))
    findings.append(Finding(code="rnp_unchecked", side="customer", severity="info",
                            title="Реестр недобросовестных поставщиков не проверен",
                            detail="Источник (РНП ЕИС) подключается через API ЕИС по токену."))
    level = "high" if any(f.severity == "high" for f in findings) else \
        "warn" if any(f.severity == "warn" for f in findings) else "low"
    return {"inn": p.inn, "price": p.price, "company": card, "risk": level,
            "risk_name": {"high": "Высокий риск", "warn": "Есть замечания", "low": "Без замечаний"}[level],
            "findings": findings}
