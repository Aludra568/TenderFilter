"""Проверка документов любого вида: тип, срок действия, на кого выдан.

Универсально, без привязки к шаблону: тип определяется по словам в тексте (лицензия, выписка СРО,
сертификат, декларация, банковская гарантия, доверенность, выписка ЕГРЮЛ…), даты — по формам
«до 12.03.2025», «по 12 марта 2025 г.», «срок действия … 2025-03-12», «бессрочно».
Проверки против дат закупки:
  • документ истёк до окончания подачи заявок — заявку отклонят (риск обеим сторонам);
  • истекает до окончания исполнения контракта — нужно продлевать (предупреждение);
  • банковская гарантия должна действовать дольше исполнения контракта минимум на месяц (ст. 96 44-ФЗ);
  • ИНН в документе не совпадает с ИНН компании — документ на другую организацию;
  • документ распознан со скана — даты стоит проверить глазами.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.domain import CanonicalTender, Finding
from app.egrul.inn import is_valid_inn

MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
          "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_MONTH_RE = r"(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)"
DATE_RE = re.compile(
    r"(?P<d1>\d{1,2})[./](?P<m1>\d{1,2})[./](?P<y1>\d{4})"
    r"|(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2})"
    r"|«?(?P<d3>\d{1,2})»?\s+" + _MONTH_RE + r"\s+(?P<y3>\d{4})", re.I)
VALID_UNTIL = re.compile(r"(?:действ\w*|действителен|действительна|срок\w*\s+действия[^\n]{0,60}?|выдан\w*\s+на\s+срок)"
                         r"[^\n]{0,40}?\s(?:до|по)\s*$|окончани\w*\s+срока\s+действия[^.\n]{0,20}?$|истека\w*[^.\n]{0,20}?$|"
                         r"(?:valid|expires?)\s+(?:until|on)?\s*$", re.I)
INDEFINITE = re.compile(r"бессрочн|без\s+ограничения\s+срока|срок\s+действия\s*[:\-–—]?\s*не\s+ограничен", re.I)

DOC_TYPES = [
    ("bank_guarantee", "Банковская гарантия", re.compile(r"банковск\w+\)?\s+гаранти|независим\w+\s+(?:\(\w+\)\s+)?гаранти|^\s*гаранти\w*\s+№", re.I | re.M)),
    ("license", "Лицензия", re.compile(r"\bлицензи[яиюей]\b|лицензия\s+№|на\s+осуществление\s+деятельности", re.I)),
    ("sro", "Выписка из реестра СРО", re.compile(r"саморегулируем\w+\s+организац|\bСРО\b|реестр\w*\s+членов", re.I)),
    ("certificate", "Сертификат соответствия", re.compile(r"сертификат\w*\s+соответстви", re.I)),
    ("declaration", "Декларация о соответствии", re.compile(r"деклараци\w+\s+о\s+соответствии", re.I)),
    ("registration", "Регистрационное удостоверение", re.compile(r"регистрационн\w+\s+удостоверени", re.I)),
    ("power_of_attorney", "Доверенность", re.compile(r"\bдоверенност[ьи]\b", re.I)),
    ("egrul_extract", "Выписка из ЕГРЮЛ/ЕГРИП", re.compile(r"выписк\w+\s+из\s+(?:единого\s+)?(?:государственного\s+)?(?:реестра|ЕГРЮЛ|ЕГРИП)", re.I)),
    ("contract", "Проект контракта", re.compile(r"проект\w*\s+(?:государственного\s+|муниципального\s+)?контракт|"
                                                r"контракт\s+№|предмет\s+контракта|ответственность\s+сторон", re.I)),
    ("tz", "Техническое задание", re.compile(r"техническ\w+\s+задани|описани\w+\s+объекта\s+закупки", re.I)),
]
# Насколько свежей должна быть выписка из ЕГРЮЛ, чтобы её приняли (обычно — не старше 30 дней).
EXTRACT_MAX_AGE_DAYS = 30


@dataclass
class DocInfo:
    name: str
    doc_type: str
    type_name: str
    method: str
    valid_until: str | None = None
    indefinite: bool = False
    issued: str | None = None
    inns: tuple[str, ...] = ()


def classify(text: str, filename: str = "") -> tuple[str, str]:
    head = (filename + "\n" + text[:4000])
    for key, name, pattern in DOC_TYPES:
        if pattern.search(head):
            return key, name
    return "other", "Документ"


def parse_date(m: re.Match) -> date | None:
    try:
        if m.group("y1"):
            return date(int(m.group("y1")), int(m.group("m1")), int(m.group("d1")))
        if m.group("y2"):
            return date(int(m.group("y2")), int(m.group("m2")), int(m.group("d2")))
        month_word = m.group(m.re.groupindex["y3"] - 1).lower()
        month = next(v for k, v in MONTHS.items() if month_word.startswith(k))
        return date(int(m.group("y3")), month, int(m.group("d3")))
    except (ValueError, StopIteration, TypeError):
        return None


def validity(text: str) -> tuple[date | None, bool, date | None]:
    """(действует до, бессрочно, дата выдачи) — по контексту слева от каждой даты."""
    until, issued = None, None
    for m in DATE_RE.finditer(text):
        d = parse_date(m)
        if not d or not (1990 <= d.year <= 2100):
            continue
        left = text[max(0, m.start() - 90):m.start()]
        if VALID_UNTIL.search(left.lower().replace("ё", "е")):
            until = max(until, d) if until else d
        elif issued is None and re.search(r"(?:дата\s+(?:выдачи|регистрации|предоставления|формирования)|выдан\w*|от)\s*[:№\d\s-]*$",
                                          left.lower()[-40:]):
            issued = d
    return until, bool(INDEFINITE.search(text)), issued


def inns_in(text: str) -> tuple[str, ...]:
    found = []
    for m in re.finditer(r"ИНН\D{0,12}(\d{10}|\d{12})\b", text):
        if is_valid_inn(m.group(1)) and m.group(1) not in found:
            found.append(m.group(1))
    return tuple(found)


def _fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def check(name: str, text: str, method: str, tender: CanonicalTender | None, company_inn: str | None,
          today: date | None = None) -> tuple[DocInfo, list[Finding]]:
    doc_type, type_name = classify(text, name)
    until, indefinite, issued = validity(text)
    info = DocInfo(name, doc_type, type_name, method, _fmt(until) if until else None, indefinite,
                   _fmt(issued) if issued else None, inns_in(text))
    findings: list[Finding] = []
    title = f"{type_name} «{name}»"
    today = today or datetime.now(timezone.utc).date()
    deadline = tender.submission_deadline.date() if tender and tender.submission_deadline else today
    contract_end = deadline + timedelta(days=(tender.contract_term_days or 0) + 10) if tender else None

    if method == "ocr":
        findings.append(Finding(code="ocr_used", side="both", severity="info", title=f"{title}: распознан со скана",
                                detail="Текст получен распознаванием изображения — номера и даты стоит сверить с оригиналом."))
    if doc_type in ("contract", "tz", "other"):
        pass
    elif until and not indefinite:
        if until < today:
            findings.append(Finding(code="doc_expired", side="both", severity="high",
                                    title=f"{title} истёк {_fmt(until)}",
                                    detail="Документ недействителен — заявку с ним отклонят; нужен действующий документ."))
        elif until < deadline:
            findings.append(Finding(code="doc_expires_before_deadline", side="both", severity="high",
                                    title=f"{title} истекает {_fmt(until)} — до окончания подачи заявок",
                                    detail="На дату рассмотрения заявки документ будет недействителен."))
        elif doc_type == "bank_guarantee" and contract_end and until < contract_end + timedelta(days=30):
            findings.append(Finding(code="guarantee_too_short", side="both", severity="high",
                                    title=f"Банковская гарантия действует до {_fmt(until)} — короче нужного",
                                    detail=f"Должна действовать минимум на месяц дольше исполнения контракта (≈ до {_fmt(contract_end + timedelta(days=30))}).",
                                    law="ч. 3 ст. 96 44-ФЗ"))
        elif contract_end and until < contract_end:
            findings.append(Finding(code="doc_expires_during_contract", side="supplier", severity="warn",
                                    title=f"{title} истекает {_fmt(until)} — во время исполнения контракта",
                                    detail="Документ придётся продлить до окончания контракта."))
        else:
            findings.append(Finding(code="doc_valid", side="both", severity="info",
                                    title=f"{title} действует до {_fmt(until)}", detail="Срок действия покрывает закупку."))
    elif indefinite:
        findings.append(Finding(code="doc_valid", side="both", severity="info", title=f"{title}: бессрочный",
                                detail="Срок действия не ограничен."))
    elif doc_type == "egrul_extract" and issued:
        age = (today - issued).days
        sev = "warn" if age > EXTRACT_MAX_AGE_DAYS else "info"
        findings.append(Finding(code="extract_age", side="both", severity=sev,
                                title=f"Выписка из ЕГРЮЛ от {_fmt(issued)} ({age} дн.)",
                                detail="Обычно требуют выписку не старше 30 дней." if sev == "warn" else "Выписка свежая."))
    else:
        findings.append(Finding(code="doc_no_validity", side="both", severity="warn",
                                title=f"{title}: срок действия не найден",
                                detail="Проверьте срок действия вручную или приложите документ с текстовым слоем."))

    if company_inn and info.inns and company_inn not in info.inns and doc_type not in ("contract", "tz", "other"):
        findings.append(Finding(code="doc_other_inn", side="both", severity="high",
                                title=f"{title} выдан на другую организацию (ИНН {', '.join(info.inns[:2])})",
                                detail=f"ИНН компании — {company_inn}. Документ другой организации к заявке не подойдёт."))
    return info, findings
