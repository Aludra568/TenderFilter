"""Факторы скоринга. Каждый фактор — чистая функция: закупка + компания + настройки → балл и объяснение.

Новый фактор = новая функция + запись в FACTORS. Интерфейс панели настроек строится
по схеме из FACTORS (GET /api/factors), поэтому фронтенд править не нужно.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.domain import PROCEDURE_NAMES, CanonicalTender, CompanyCard, Preferences
from app.reference import textvec
from app.reference.okved import match_okved_okpd
from app.reference.regions import BY_CODE


@dataclass
class Source:
    field: str
    path: str
    raw: str


@dataclass
class FactorResult:
    key: str
    label: str
    score: float | None  # 0..1, None — нет данных
    active: bool = True  # False — пользователь не задал предпочтений, фактор не влияет
    stop: str | None = None  # причина стоп-фактора
    flag: str | None = None  # красный флаг: вердикт не выше «Рассмотреть»
    value: str = ""  # что увидели в закупке, человеческим языком
    reasons: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    weight: float = 0.0
    points: float = 0.0


@dataclass
class Context:
    tender: CanonicalTender
    company: CompanyCard | None
    customer: CompanyCard | None
    prefs: Preferences
    now: datetime


def _src(ctx: Context, *fields: str) -> list[Source]:
    out = []
    for f in fields:
        s = ctx.tender.sources.get(f)
        if s:
            out.append(Source(field=f, path=s.path, raw=s.raw))
    return out


def _rub(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f} млн ₽".replace(".", ",").replace(",0 ", " ")
    if v >= 1000:
        return f"{v / 1000:.0f} тыс. ₽"
    return f"{v:.0f} ₽"


def _days(n: float) -> str:
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} дня"
    return f"{n} дней"


# ---------------- Профильность ----------------

def profile_factor(ctx: Context) -> FactorResult:
    p = ctx.prefs.profile
    t = ctx.tender
    r = FactorResult("profile", "Профильность", None, sources=_src(ctx, "subject"))
    text = t.text_for_matching()
    r.value = t.subject[:160]

    excluded = textvec.keyword_hits(p.exclude_keywords, text)
    if excluded:
        r.score, r.stop = 0.0, f"В предмете закупки исключённое слово: «{excluded[0]}»"
        return r

    best, reasons = 0.0, []
    if p.okpd2_prefixes and t.okpd2:
        hit = next((c for c in t.okpd2 for pref in p.okpd2_prefixes if c.startswith(pref)), None)
        if hit:
            best = 1.0
            reasons.append(f"ОКПД 2 {hit} входит в ваши товарные группы")
    okveds = ctx.company.okved_codes if (ctx.company and p.use_okved) else []
    if okveds and t.okpd2:
        s, okved, okpd = match_okved_okpd(okveds, t.okpd2)
        if s > best:
            best = s
            name = next((o.name for o in ctx.company.okveds if o.code == okved), None) if ctx.company else None
            reasons.append(f"Товар по профилю: ОКПД 2 {okpd} ↔ ваш ОКВЭД {okved}")
            if name:
                reasons.append(f"ОКВЭД {okved} — {name}")
    kw_hits = textvec.keyword_hits(p.keywords, text)
    if kw_hits:
        best = max(best, 1.0)
        reasons.append("Ключевые слова профиля: " + ", ".join(kw_hits[:3]))

    profile_text = " ".join(p.keywords)
    if ctx.company and p.use_okved:
        profile_text += " " + " ".join(o.name or "" for o in ctx.company.okveds)
    if profile_text.strip():
        sim = textvec.cosine(textvec.embed(text), textvec.embed(profile_text))
        sem = max(0.0, min(1.0, (sim - 0.1) / 0.3)) * 0.85
        if sem > best:
            best = sem
            reasons.append(f"Смысловая близость предмета к профилю {round(sim * 100)}%")

    if not t.okpd2 and not profile_text.strip():
        r.reasons = ["Нет кодов ОКПД 2 и не задан профиль — профильность не оценить"]
        return r
    r.score = round(best, 3)
    r.reasons = reasons or ["Предмет закупки не похож на ваш профиль"]
    if t.okpd2:
        r.sources += _src(ctx, "okpd2") or [Source("okpd2", "OKPD2", ", ".join(t.okpd2[:5]))]
    if p.required and best < 0.4:
        r.stop = "Предмет закупки не по вашему профилю"
    return r


# ---------------- Цена ----------------

def price_factor(ctx: Context) -> FactorResult:
    p, t = ctx.prefs.price, ctx.tender
    r = FactorResult("price", "Цена", None, sources=_src(ctx, "nmck"))
    if t.nmck is None:
        r.reasons = ["В извещении не найдена НМЦК"]
        return r
    r.value = f"НМЦК {_rub(t.nmck)}"
    lo, hi = p.min_rub, p.max_rub
    if lo is None and hi is None:
        r.active, r.score = False, 1.0
        r.reasons = ["Диапазон НМЦК не задан — фактор не учитывается"]
        return r
    n = t.nmck
    rng = f"{_rub(lo) if lo else '0'} – {_rub(hi) if hi else 'без ограничения'}"
    if (lo is None or n >= lo) and (hi is None or n <= hi):
        r.score = 1.0
        r.reasons = [f"{_rub(n)} в вашем диапазоне {rng}"]
    elif hi is not None and n > hi:
        # Линейно до нуля при превышении максимума в 1,5 раза.
        r.score = round(max(0.0, 1 - (n - hi) / (0.5 * hi)), 3)
        r.reasons = [f"{_rub(n)} выше вашего максимума {_rub(hi)}"]
    else:
        # Линейно до нуля, если НМЦК вдвое меньше минимума.
        r.score = round(max(0.0, 1 - (lo - n) / (0.5 * lo)), 3) if lo else 0.0
        r.reasons = [f"{_rub(n)} ниже вашего минимума {_rub(lo)}"]
    if p.required and r.score < 1:
        r.stop = f"НМЦК вне диапазона {rng}"
    return r


# ---------------- География ----------------

def geo_factor(ctx: Context) -> FactorResult:
    p, t = ctx.prefs.geo, ctx.tender
    r = FactorResult("geo", "География", None, sources=_src(ctx, "delivery_place"))
    code = t.delivery_region_code
    if not code:
        r.reasons = ["Не удалось определить регион поставки"]
        return r
    region = BY_CODE.get(code)
    r.value = region.name if region else code
    if code in p.excluded:
        r.score, r.stop = 0.0, f"{r.value} — в списке исключённых регионов"
        return r
    allowed = dict(p.regions)
    if not allowed and ctx.company and ctx.company.region_code:
        allowed = {ctx.company.region_code: 1.0}
    if not allowed:
        r.active, r.score = False, 1.0
        r.reasons = ["Регионы не заданы — фактор не учитывается"]
        return r
    if code in allowed:
        r.score = float(allowed[code])
        r.reasons = [f"{r.value} — ваш регион" if r.score >= 1 else f"{r.value} — регион с пониженным приоритетом"]
    else:
        districts = {BY_CODE[c].district for c, v in allowed.items() if c in BY_CODE and v >= 1}
        if region and region.district in districts and not p.required:
            r.score = p.same_district_score
            r.reasons = [f"{r.value} — соседний регион вашего федерального округа"]
        else:
            r.score = 0.0
            r.reasons = [f"{r.value} — вне ваших регионов"]
    if p.required and r.score == 0:
        r.stop = f"Поставка в {r.value} — вне ваших регионов"
    return r


# ---------------- Сроки ----------------

def timing_factor(ctx: Context) -> FactorResult:
    p, t = ctx.prefs.timing, ctx.tender
    r = FactorResult("timing", "Сроки", None, sources=_src(ctx, "deadline", "delivery_term"))
    parts: list[tuple[float, float]] = []
    reasons = []
    if t.submission_deadline:
        deadline = t.submission_deadline if t.submission_deadline.tzinfo else t.submission_deadline.replace(tzinfo=timezone.utc)
        days = (deadline - ctx.now).total_seconds() / 86400
        if days < 0:
            r.score, r.stop = 0.0, "Срок подачи заявок истёк"
            r.value = deadline.strftime("подача до %d.%m.%Y")
            return r
        whole = int(days)
        left = _days(whole) if whole >= 1 else "меньше суток"
        r.value = f"до окончания подачи {left}"
        min_days = max(0, p.min_days_to_deadline)
        if days >= max(7, min_days):
            ds = 1.0
        elif days >= min_days:
            span = max(1, 7 - min_days)
            ds = 0.6 + 0.4 * (days - min_days) / span
        else:
            ds = 0.2
            if p.required:
                r.stop = f"До окончания подачи {left} — меньше вашего минимума ({_days(min_days)})"
        reasons.append(f"{left[0].upper() + left[1:]} на подготовку заявки" + (" — мало" if ds < 0.6 else ""))
        parts.append((2.0, ds))
    if p.min_contract_days and t.contract_term_days:
        ts = 1.0 if t.contract_term_days >= p.min_contract_days else t.contract_term_days / p.min_contract_days
        reasons.append(f"Срок исполнения {_days(t.contract_term_days)} при вашем минимуме {_days(p.min_contract_days)}")
        parts.append((1.0, ts))
    elif t.contract_term_days:
        reasons.append(f"Срок исполнения {_days(t.contract_term_days)}")
    if not parts:
        r.reasons = ["Не найден срок окончания подачи заявок"]
        return r
    r.score = round(sum(w * s for w, s in parts) / sum(w for w, _ in parts), 3)
    r.reasons = reasons
    return r


# ---------------- Финансы ----------------

def finance_factor(ctx: Context) -> FactorResult:
    p, t = ctx.prefs.finance, ctx.tender
    r = FactorResult("finance", "Финансы", None,
                     sources=_src(ctx, "app_guarantee_amount", "contract_guarantee_part", "contract_guarantee_amount", "advance_percent"))
    parts, reasons, values = [], [], []
    total = (t.app_guarantee_amount or 0) + (t.contract_guarantee_amount or 0)
    known_guarantee = t.app_guarantee_amount is not None or t.contract_guarantee_amount is not None
    if known_guarantee:
        values.append(f"обеспечения {_rub(total)}")
        if p.guarantee_limit_rub:
            ratio = total / p.guarantee_limit_rub
            gs = 1.0 if ratio <= 0.5 else 0.7 if ratio <= 1 else max(0.0, 0.5 * (2 - ratio))
            reasons.append(f"Обеспечения {_rub(total)} при лимите {_rub(p.guarantee_limit_rub)}")
            if ratio > 1 and p.required:
                r.stop = f"Обеспечения {_rub(total)} больше вашего лимита {_rub(p.guarantee_limit_rub)}"
        else:
            pct = t.contract_guarantee_percent or 0
            gs = 1.0 if pct <= 5 else 0.8 if pct <= 10 else 0.6 if pct <= 20 else 0.4
            reasons.append(f"Обеспечение контракта {pct:g}%".replace(".", ","))
        parts.append(gs)
    if t.advance_percent is not None:
        values.append(f"аванс {t.advance_percent:g}%")
    if p.advance in ("want", "must"):
        if t.advance_percent and t.advance_percent > 0:
            parts.append(1.0)
            reasons.append(f"Аванс {t.advance_percent:g}%")
        elif t.advance_percent == 0 or (t.advance_percent is None and t.sources.get("advance_percent")):
            parts.append(0.0)
            reasons.append("Аванс не предусмотрен")
            if p.advance == "must":
                r.stop = "Аванс не предусмотрен, а он для вас обязателен"
        else:
            # ЕИС не публикует аванс в XML — он в проекте контракта во вложениях. Не штрафуем, но предупреждаем.
            parts.append(0.5)
            reasons.append("Аванс в XML не публикуется — проверьте проект контракта")
            if p.advance == "must":
                r.flag = "Аванс для вас обязателен, а в извещении он не указан — проверьте проект контракта"
    elif t.advance_percent:
        reasons.append(f"Аванс {t.advance_percent:g}%")
    r.value = ", ".join(values)
    if not parts:
        r.reasons = ["Нет данных об обеспечениях и авансе"]
        return r
    r.score = round(sum(parts) / len(parts), 3)
    r.reasons = reasons
    return r


# ---------------- Условия участия ----------------

def conditions_factor(ctx: Context) -> FactorResult:
    p, t, c = ctx.prefs.conditions, ctx.tender, ctx.company
    r = FactorResult("conditions", "Условия участия", None,
                     sources=_src(ctx, "placing_way_name", "smp_only", "national_regime"))
    proc_name = t.procedure_name or PROCEDURE_NAMES.get(t.procedure_type, t.procedure_type)
    r.value = f"{t.law.replace('-FZ', '-ФЗ')}, {proc_name}" + (", только СМП" if t.smp_only else "")
    if t.law not in p.laws:
        r.score, r.stop = 0.0, f"Закупки по {t.law.replace('-FZ', '-ФЗ')} вы не рассматриваете"
        return r
    if c and c.status not in ("ACTIVE", "UNKNOWN"):
        r.score, r.stop = 0.0, "Ваша компания по данным ЕГРЮЛ недействующая"
        return r
    pref = p.methods.get(t.procedure_type, "neutral")
    if pref == "exclude":
        r.score, r.stop = 0.0, f"Способ «{proc_name}» вы исключили"
        return r
    parts, reasons = [], []
    parts.append(1.0 if pref == "prefer" else 0.7)
    reasons.append(f"{proc_name} — " + ("предпочтительный способ" if pref == "prefer" else "нейтральный способ"))
    if t.smp_only:
        if c and c.is_msp is False:
            r.score, r.stop = 0.0, "Закупка только для СМП, а вашей компании нет в реестре МСП"
            return r
        if c and c.is_msp:
            parts.append(1.0 if p.prefer_smp else 0.8)
            reasons.append("Закупка только для СМП — вы в реестре, конкурентов меньше")
        else:
            parts.append(0.6)
            reasons.append("Закупка только для СМП — статус МСП вашей компании неизвестен")
    if t.national_regime:
        if p.imports_only:
            r.score, r.stop = 0.0, "Действует национальный режим, а вы поставляете импортные товары"
            return r
        reasons.append("Действует национальный режим (ПП № 1875) — нужны документы о происхождении товара")
        parts.append(0.8)
    r.score = round(sum(parts) / len(parts), 3)
    r.reasons = reasons
    return r


# ---------------- Заказчик ----------------

def customer_factor(ctx: Context) -> FactorResult:
    p, t, cust = ctx.prefs.customer, ctx.tender, ctx.customer
    r = FactorResult("customer", "Заказчик", None, sources=_src(ctx, "customer_inn", "customer_name"))
    r.value = t.customer_name or (t.customer_inn or "")
    if t.customer_inn and t.customer_inn in p.excluded_inns:
        r.score, r.stop = 0.0, "Заказчик в вашем чёрном списке"
        return r
    if not cust:
        r.reasons = ["Нет данных ЕГРЮЛ о заказчике"]
        return r
    status_score = {"ACTIVE": 1.0, "REORGANIZING": 0.5, "UNKNOWN": 0.6}.get(cust.status, 0.0)
    reasons = []
    if cust.status == "ACTIVE":
        reasons.append("Действующая организация")
    elif cust.status == "REORGANIZING":
        reasons.append("Заказчик в процессе реорганизации")
    elif cust.status != "UNKNOWN":
        reasons.append("Заказчик ликвидируется или банкрот — риск неоплаты")
        r.flag = "Заказчик ликвидируется или банкрот — риск неоплаты"
        if p.required:
            r.stop = "Заказчик ликвидируется или банкрот"
    age_score = 1.0
    if cust.registration_date:
        reg = cust.registration_date if cust.registration_date.tzinfo else cust.registration_date.replace(tzinfo=timezone.utc)
        years = (ctx.now - reg).days / 365.25
        if years < 1:
            age_score = 0.5
            reasons.append("Зарегистрирован меньше года назад")
        else:
            reasons.append(f"Работает {int(years)} лет" if int(years) % 10 not in (1, 2, 3, 4) else f"Работает с {reg.year} г.")
    r.score = round(min(status_score, 1.0) * 0.7 + age_score * 0.3, 3)
    r.reasons = reasons
    return r


@dataclass(frozen=True)
class FactorDef:
    key: str
    label: str
    base_weight: float
    fn: Callable[[Context], FactorResult]
    description: str
    controls: list[dict]


FACTORS: list[FactorDef] = [
    FactorDef("profile", "Профильность", 25, profile_factor,
              "Совпадение предмета закупки с вашими товарами: ОКПД 2 ↔ ОКВЭД, ключевые слова, смысловая близость",
              [{"param": "keywords", "type": "tags", "label": "Ключевые слова (что вы поставляете)"},
               {"param": "exclude_keywords", "type": "tags", "label": "Исключить, если в предмете есть"},
               {"param": "okpd2_prefixes", "type": "tags", "label": "Коды ОКПД 2 (начало кода)"}]),
    FactorDef("price", "Цена", 15, price_factor, "НМЦК в вашем рабочем диапазоне",
              [{"param": "min_rub", "type": "money", "label": "НМЦК от", "max": 1_000_000_000},
               {"param": "max_rub", "type": "money", "label": "НМЦК до", "max": 1_000_000_000}]),
    FactorDef("geo", "География", 15, geo_factor, "Регион поставки: ваши регионы, соседние и исключённые",
              [{"param": "regions", "type": "regions", "label": "Ваши регионы"},
               {"param": "excluded", "type": "region_list", "label": "Исключённые регионы"},
               {"param": "same_district_score", "type": "ratio", "label": "Балл соседнего региона того же округа"}]),
    FactorDef("timing", "Сроки", 15, timing_factor, "Время на подготовку заявки и срок исполнения контракта",
              [{"param": "min_days_to_deadline", "type": "int", "label": "Минимум дней на заявку", "min": 1, "max": 15},
               {"param": "min_contract_days", "type": "int", "label": "Минимальный срок исполнения, дней", "min": 0, "max": 120}]),
    FactorDef("finance", "Финансы", 10, finance_factor, "Обеспечения заявки и контракта, аванс",
              [{"param": "guarantee_limit_rub", "type": "money", "label": "Лимит на обеспечения", "max": 100_000_000},
               {"param": "advance", "type": "segmented", "label": "Аванс",
                "options": [["ignore", "Не важен"], ["want", "Важен"], ["must", "Обязателен"]]}]),
    FactorDef("conditions", "Условия участия", 15, conditions_factor, "Закон, способ закупки, СМП, национальный режим",
              [{"param": "laws", "type": "multi", "label": "Законы", "options": [["44-FZ", "44-ФЗ"], ["223-FZ", "223-ФЗ"]]},
               {"param": "methods", "type": "methods", "label": "Способы закупки",
                "options": [[k, v] for k, v in PROCEDURE_NAMES.items() if k != "other"]},
               {"param": "imports_only", "type": "toggle", "label": "Поставляем только импортные товары"}]),
    FactorDef("customer", "Заказчик", 5, customer_factor, "Надёжность заказчика по ЕГРЮЛ",
              [{"param": "excluded_inns", "type": "tags", "label": "ИНН заказчиков, с которыми не работаем"}]),
]

FACTOR_BY_KEY = {f.key: f for f in FACTORS}
