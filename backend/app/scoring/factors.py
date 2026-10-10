"""Факторы скоринга. Каждый фактор — чистая функция: закупка + компания + настройки → балл и объяснение.

Новый фактор = новая функция + запись в FACTORS. Интерфейс панели настроек строится
по схеме из FACTORS (GET /api/factors), поэтому фронтенд править не нужно.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.docs.contract import supplier_findings
from app.domain import PROCEDURE_NAMES, CanonicalTender, CompanyCard, Preferences
from app.reference import textvec
from app.reference.okved import match_okved_okpd
from app.reference.regions import BY_CODE
from app.scoring import fuzzy


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
    fuzzy: dict | None = None  # график нечёткой переменной для объяснения


@dataclass
class Context:
    tender: CanonicalTender
    company: CompanyCard | None
    customer: CompanyCard | None
    prefs: Preferences
    now: datetime
    committed: float = 0.0  # уже занято в обеспечениях по другим заявкам компании
    committed_count: int = 0


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
    code_score = best  # совпадение по кодам ОКПД 2 / ОКВЭД
    codes_conflict = bool(t.okpd2 and (okveds or p.okpd2_prefixes) and code_score == 0)
    kw_hits = textvec.keyword_hits(p.keywords, text)
    if kw_hits:
        trade_only = bool(okveds) and all(o.startswith(("46", "47")) for o in okveds)
        works = bool(t.okpd2) and all(c[:2] in WORKS_SERVICES for c in t.okpd2)
        if trade_only and works:
            # Торговая компания, а закупаются работы или услуги («обустройство помещений под оборудование»)
            best = max(best, 0.6)
            reasons.append("Слова профиля есть в предмете («" + ", ".join(kw_hits[:2]) + "»), но закупаются работы или услуги, а не поставка")
        else:
            best = max(best, 1.0)
            reasons.append("Ключевые слова профиля: " + ", ".join(kw_hits[:3]))

    profile_text = " ".join(p.keywords)
    if ctx.company and p.use_okved:
        profile_text += " " + " ".join(o.name or "" for o in ctx.company.okveds)
    if profile_text.strip():
        sim = textvec.cosine(textvec.embed(text), textvec.embed(profile_text))
        sem = max(0.0, min(1.0, (sim - 0.15) / 0.35)) * 0.85
        if codes_conflict:
            sem = min(sem, 0.35)  # коды закупки явно чужие — похожесть слов не делает её профильной
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

def _explain_fuzzy(r: FactorResult, inf: "fuzzy.Inference") -> None:
    """Пояснение только для пограничных значений, где нечёткая логика и правда что-то решает."""
    if 0.001 < r.score < 0.999:
        r.reasons.append("Нечёткая оценка — " + inf.describe())


# Разделы ОКПД 2 с работами и услугами (стройка, проектирование, охрана, медицина, мероприятия…)
WORKS_SERVICES = {"41", "42", "43", "71", "74", "80", "81", "82", "84", "85", "86", "87", "88", "90", "91", "93", "94", "96"}


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
    # Нечёткое множество «цена подходит»: ядро — ваш диапазон, плечи до ½ минимума и до 1,5 максимума.
    inf = fuzzy.price_fit(n, lo, hi)
    r.score = inf.memberships["подходит"]
    r.fuzzy = fuzzy.chart("price", n, inf, low=lo, high=hi)
    if (lo is None or n >= lo) and (hi is None or n <= hi):
        r.reasons = [f"{_rub(n)} в вашем диапазоне {rng}"]
    elif hi is not None and n > hi:
        r.reasons = [f"{_rub(n)} выше вашего максимума {_rub(hi)}"]
    else:
        r.reasons = [f"{_rub(n)} ниже вашего минимума {_rub(lo)}"]
    _explain_fuzzy(r, inf)
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
    for wh in p.warehouses:
        allowed.setdefault(wh, 0.9)  # склад или филиал в регионе — логистика своя
    if not allowed:
        r.active, r.score = False, 1.0
        r.reasons = ["Регионы не заданы — фактор не учитывается"]
        return r
    if code in allowed:
        r.score = float(allowed[code])
        r.reasons = [f"{r.value} — ваш регион" if r.score >= 1 else f"{r.value} — регион с пониженным приоритетом"]
        if code in p.warehouses:
            r.score = max(r.score, 0.9)
            r.reasons = [f"{r.value} — у вас там склад или филиал"]
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
        # Лингвистическая переменная «время на заявку»: мало / нормально / достаточно (вывод Сугено).
        inf = fuzzy.time_left(days, min_days)
        ds = inf.score
        r.fuzzy = fuzzy.chart("time_left", days, inf, min_days=min_days)
        if days < min_days and p.required:
            r.stop = f"До окончания подачи {left} — меньше вашего минимума ({_days(min_days)})"
        reasons.append(f"{left[0].upper() + left[1:]} на подготовку заявки" + (" — мало" if ds < 0.6 else ""))
        if sum(1 for m in inf.memberships.values() if m > 0.001) > 1:
            reasons.append("Нечёткая оценка времени — " + inf.describe())
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
            # Динамический лимит: часть денег уже заморожена в обеспечениях по другим заявкам.
            free = max(0.0, p.guarantee_limit_rub - ctx.committed)
            ratio = total / free if free > 0 else (float("inf") if total > 0 else 0.0)
            inf = fuzzy.guarantee_load(min(ratio, 10.0))
            gs = inf.score
            r.fuzzy = fuzzy.chart("guarantee_load", min(ratio, 10.0), inf)
            limit_txt = (f"свободном лимите {_rub(free)} (занято {_rub(ctx.committed)} в {ctx.committed_count} "
                         f"заявк{'е' if ctx.committed_count == 1 else 'ах'})") if ctx.committed else f"лимите {_rub(p.guarantee_limit_rub)}"
            reasons.append(f"Обеспечения {_rub(total)} при {limit_txt} — нагрузка «{inf.dominant}»")
            if sum(1 for m in inf.memberships.values() if m > 0.001) > 1:
                reasons.append("Нечёткая оценка нагрузки — " + inf.describe())
            if ratio > 1 and p.required:
                r.stop = f"Обеспечения {_rub(total)} больше свободного лимита {_rub(free)}"
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
    gap = next((x for x in (t.contract.findings if t.contract else []) if x.code == "cash_gap"), None)
    if gap:
        # Кассовый разрыв из проекта контракта: приёмка + оплата.
        parts.append(0.6 if gap.severity == "warn" else 1.0)
        reasons.append(gap.title)
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
    score = sum(parts) / len(parts)
    # Риски проекта контракта и ТЗ (если документы загружены): жёсткие санкции, долгая оплата, марка без аналога.
    risks = [x for x in supplier_findings(t) if x.severity in ("high", "warn")]
    if risks:
        penalty = sum(0.3 if x.severity == "high" else 0.15 for x in risks)
        score = max(0.0, score - penalty)
        reasons += ["Контракт: " + x.title for x in risks[:4]]
        high = next((x for x in risks if x.severity == "high"), None)
        if high:
            r.flag = "Контракт: " + high.title
        r.sources.append(Source("contract", "проект контракта", high.quote if high and high.quote else risks[0].title))
    elif t.contract:
        reasons.append("Проект контракта проверен — жёстких условий не найдено")
    r.score = round(score, 3)
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
               {"param": "warehouses", "type": "region_list", "label": "Склады и филиалы"},
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
