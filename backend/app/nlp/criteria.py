"""Текст критериев → предпочтения профиля.

Два движка с одним результатом:
• правила (регулярные выражения + справочники) — работают всегда, мгновенно и предсказуемо;
• LLM — разбирает свободные формулировки, которые правила не поняли.
Каждое распознанное правило помнит фразу-источник, нераспознанные фразы возвращаются пользователю.
"""

import json
import re
from dataclasses import dataclass, field

from app.domain import Preferences
from app.nlp import llm
from app.reference.regions import BY_CODE, find_districts, find_regions, normalize, regions_of_district

UNITS = {"тыс": 1e3, "т": 1e3, "к": 1e3, "млн": 1e6, "лям": 1e6, "кк": 1e6, "м": 1e6, "млрд": 1e9}
_NUM = r"(\d+(?:[.,]\d+)?)\s*(тыс|млн|млрд|лям\w*|кк|к)?\.?"

SOFT = re.compile(r"если выгодн|по возможност|иногда|желательн|тоже можно|можно и|рассматрива|при случае|реже")
NEG_STRONG = re.compile(r"не участв|не бер[её]м|исключ|никогда|не работаем|не рассматрива|без\b|кроме")
NEG_SOFT = re.compile(r"не люб|избега|не очень|неохотно|не хотим")

METHODS = [
    (r"аукцион", "e_auction", "аукционы"),
    (r"конкурс", "open_contest", "конкурсы"),
    (r"котиров", "quotation_request", "запросы котировок"),
    (r"запрос\w* предложени", "proposal_request", "запросы предложений"),
    (r"единствен", "single_supplier", "закупки у единственного поставщика"),
]
FACTOR_WORDS = {
    "geo": r"регион|географ|доставк|логист",
    "price": r"нмц|цен|сумм|бюджет",
    "profile": r"профил|товар|ассортимент",
    "timing": r"срок|время на заявк|успе",
    "finance": r"аванс|обеспечени|деньг|финанс",
    "customer": r"заказчик",
}


@dataclass
class Recognized:
    factor: str
    label: str
    source_text: str


@dataclass
class ParseOutcome:
    preferences: Preferences
    recognized: list[Recognized] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    engine: str = "rules"

    def to_dict(self) -> dict:
        return {
            "preferences": json.loads(self.preferences.model_dump_json()),
            "recognized": [r.__dict__ for r in self.recognized],
            "unparsed": self.unparsed,
            "engine": self.engine,
        }


def _amount(num: str, unit: str | None, default_unit: str | None = None) -> float:
    value = float(num.replace(",", "."))
    u = (unit or default_unit or "").lower()
    for key in sorted(UNITS, key=len, reverse=True):
        if u.startswith(key):
            return value * UNITS[key]
    return value


def _rub(v: float) -> str:
    if v >= 1e6:
        return f"{v / 1e6:g} млн ₽".replace(".", ",")
    if v >= 1e3:
        return f"{v / 1e3:g} тыс. ₽".replace(".", ",")
    return f"{v:g} ₽"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text.strip())
    return [p.strip(" .;") for p in parts if p.strip(" .;")]


def _clauses(sentence: str) -> list[str]:
    return [c.strip() for c in re.split(r",|\s—\s|\s-\s|;|\bа также\b|\bно\b", sentence) if c.strip()]


def parse_rules(text: str, base: Preferences | None = None) -> ParseOutcome:
    prefs = (base or Preferences()).model_copy(deep=True)
    out = ParseOutcome(preferences=prefs)
    for sentence in split_sentences(text):
        s = normalize(sentence)
        before = len(out.recognized)
        _price(s, sentence, out)
        _guarantee(s, sentence, out)
        _days(s, sentence, out)
        _regions(s, sentence, out)
        _methods(s, sentence, out)
        _advance(s, sentence, out)
        _laws(s, sentence, out)
        _smp_imports(s, sentence, out)
        _customers(s, sentence, out)
        _keywords(s, sentence, out)
        _importance(s, sentence, out)
        if len(out.recognized) == before:
            out.unparsed.append(sentence)
    return out


def _add(out: ParseOutcome, factor: str, label: str, src: str) -> None:
    out.recognized.append(Recognized(factor=factor, label=label, source_text=src))


def _price(s: str, src: str, out: ParseOutcome) -> None:
    if "обеспечен" in s:
        return
    money_ctx = re.search(r"нмц|цен|сумм|контракт|лот|бюджет|руб|₽|млн|млрд|тыс|лям", s)
    if not money_ctx:
        return
    p = out.preferences.price
    m = re.search(r"от\s*" + _NUM + r"\s*(?:₽|руб\w*)?\s*до\s*" + _NUM, s)
    if m:
        unit_hi = m.group(4)
        lo = _amount(m.group(1), m.group(2), unit_hi)
        hi = _amount(m.group(3), unit_hi, m.group(2))
        p.min_rub, p.max_rub = lo, hi
        _add(out, "price", f"НМЦК от {_rub(lo)} до {_rub(hi)}", src)
        return
    m = re.search(r"(?:до|не (?:больше|более|выше)|максимум|не дороже)\s*" + _NUM, s)
    if m and (m.group(2) or re.search(r"млн|тыс|млрд", s)):
        p.max_rub = _amount(m.group(1), m.group(2), "млн" if "млн" in s else None)
        _add(out, "price", f"НМЦК до {_rub(p.max_rub)}", src)
    m = re.search(r"(?:от|не (?:меньше|менее|ниже)|минимум|дороже)\s*" + _NUM, s)
    if m and (m.group(2) or re.search(r"млн|тыс|млрд", s)) and not re.search(r"дн|день|дня", s[m.end():m.end() + 6]):
        p.min_rub = _amount(m.group(1), m.group(2), "млн" if "млн" in s else None)
        _add(out, "price", f"НМЦК от {_rub(p.min_rub)}", src)


def _guarantee(s: str, src: str, out: ParseOutcome) -> None:
    if "обеспечен" not in s:
        return
    m = re.search(r"(?:не (?:больше|более)|до|максимум|не выше|в пределах)\s*" + _NUM, s)
    if m:
        out.preferences.finance.guarantee_limit_rub = _amount(m.group(1), m.group(2), "млн" if "млн" in s else None)
        if re.search(r"строго|обязател|никак не больше|жестк", s):
            out.preferences.finance.required = True
        _add(out, "finance", f"Обеспечения не больше {_rub(out.preferences.finance.guarantee_limit_rub)}", src)


def _days(s: str, src: str, out: ParseOutcome) -> None:
    m = re.search(r"(\d{1,3})\s*(?:рабоч\w*|календарн\w*)?\s*(?:дн|день|дня|сут)", s)
    if not m:
        return
    days = int(m.group(1))
    if re.search(r"исполнени|поставк|выполнени", s) and not re.search(r"заявк|подготов|подач", s):
        out.preferences.timing.min_contract_days = days
        _add(out, "timing", f"Срок исполнения не меньше {days} дн.", src)
        return
    out.preferences.timing.min_days_to_deadline = days
    strict = bool(re.search(r"минимум|не меньше|не менее|обязател|нужно|нужен|нужны|строго", s))
    out.preferences.timing.required = strict
    _add(out, "timing", f"Минимум {days} дн. на подготовку заявки" + (" (обязатело)" if strict else ""), src)


def _regions(s: str, src: str, out: ParseOutcome) -> None:
    geo = out.preferences.geo
    clauses = _clauses(s)
    hit = False
    for i, clause in enumerate(clauses):
        regs = list(find_regions(clause))
        for d in find_districts(clause):
            regs += [r for r in regions_of_district(d) if r not in regs]
        if not regs:
            continue
        nxt = clauses[i + 1] if i + 1 < len(clauses) else ""
        excluded = bool(NEG_STRONG.search(clause))
        soft = bool(SOFT.search(clause)) or (bool(SOFT.search(nxt)) and not find_regions(nxt))
        for r in regs:
            if excluded:
                if r.code not in geo.excluded:
                    geo.excluded.append(r.code)
                geo.regions.pop(r.code, None)
            else:
                geo.regions[r.code] = 0.5 if soft else 1.0
        names = ", ".join(r.name for r in regs[:4]) + (f" и ещё {len(regs) - 4}" if len(regs) > 4 else "")
        label = ("Исключить регионы: " if excluded else ("Регионы с пониженным приоритетом: " if soft else "Регионы: ")) + names
        _add(out, "geo", label, src)
        hit = True
    if hit and re.search(r"только|строго|исключительно", s):
        geo.required = True


def _methods(s: str, src: str, out: ParseOutcome) -> None:
    cond = out.preferences.conditions
    for clause in _clauses(s):
        _methods_clause(clause, src, out, cond)


def _methods_clause(s: str, src: str, out: ParseOutcome, cond) -> None:
    for pattern, key, name in METHODS:
        if not re.search(pattern, s):
            continue
        if NEG_STRONG.search(s):
            cond.methods[key] = "exclude"
            _add(out, "conditions", f"Исключить {name}", src)
        elif NEG_SOFT.search(s):
            cond.methods[key] = "neutral"
            for _, other, _ in METHODS:
                if other != key and cond.methods.get(other) != "exclude":
                    cond.methods.setdefault(other, "prefer")
            _add(out, "conditions", f"{name.capitalize()} — без приоритета", src)
        else:
            cond.methods[key] = "prefer"
            if re.search(r"только|исключительно", s):
                for _, other, _ in METHODS:
                    if other != key:
                        cond.methods[other] = "exclude"
            _add(out, "conditions", f"Предпочитаем {name}", src)


def _advance(s: str, src: str, out: ParseOutcome) -> None:
    if "аванс" not in s and "предоплат" not in s:
        return
    fin = out.preferences.finance
    if re.search(r"не важ|неваж|без разницы|не принцип", s):
        fin.advance = "ignore"
        _add(out, "finance", "Аванс не важен", src)
    elif re.search(r"обязател|только с аванс|без аванса не|строго|нужен обязатело", s):
        fin.advance = "must"
        _add(out, "finance", "Аванс обязателен", src)
    else:
        fin.advance = "want"
        _add(out, "finance", "Аванс важен", src)
        if re.search(r"очень|критичн|главн", s):
            fin.importance = 5


def _laws(s: str, src: str, out: ParseOutcome) -> None:
    has44, has223 = bool(re.search(r"44\s*-?\s*фз|\b44\b", s)), bool(re.search(r"223\s*-?\s*фз|\b223\b", s))
    if not (has44 or has223):
        return
    cond = out.preferences.conditions
    if re.search(r"только", s):
        cond.laws = ["44-FZ"] if has44 and not has223 else ["223-FZ"] if has223 and not has44 else ["44-FZ", "223-FZ"]
    elif NEG_STRONG.search(s):
        cond.laws = ["223-FZ"] if has44 and not has223 else ["44-FZ"] if has223 and not has44 else cond.laws
    else:
        return
    _add(out, "conditions", "Законы: " + ", ".join(x.replace("-FZ", "-ФЗ") for x in cond.laws), src)


def _smp_imports(s: str, src: str, out: ParseOutcome) -> None:
    cond = out.preferences.conditions
    if re.search(r"\bсмп\b|малого (и среднего )?(бизнеса|предпринимательства)|мсп", s):
        cond.prefer_smp = not NEG_STRONG.search(s)
        _add(out, "conditions", "Приоритет закупкам для СМП" if cond.prefer_smp else "Без приоритета закупкам для СМП", src)
    if re.search(r"импорт", s) and re.search(r"поставля|торгу|только|везем|возим", s):
        cond.imports_only = True
        _add(out, "conditions", "Поставляем импортные товары — нацрежим исключает закупку", src)


def _customers(s: str, src: str, out: ParseOutcome) -> None:
    inns = re.findall(r"\b(\d{10}|\d{12})\b", s)
    if inns and "заказчик" in s and NEG_STRONG.search(s):
        for inn in inns:
            if inn not in out.preferences.customer.excluded_inns:
                out.preferences.customer.excluded_inns.append(inn)
        _add(out, "customer", "Не работаем с заказчиками: " + ", ".join(inns), src)


def _split_items(fragment: str) -> list[str]:
    items = re.split(r",|;|\bи\b|\bили\b|/", fragment)
    cleaned = []
    for it in items:
        it = re.sub(r"^\s*(а также|также|еще|ещё)\s+", "", it).strip(" .:—-")
        if 2 < len(it) <= 60 and not find_regions(it) and not re.search(r"\d", it):
            cleaned.append(it)
    return cleaned


def _keywords(s: str, src: str, out: ParseOutcome) -> None:
    prof = out.preferences.profile
    m = re.search(r"(?:поставляем|продаем|торгуем|занимаемся|специализируемся на|наш профиль[:\s—-]*|работаем с|возим|делаем)\s+(.+)", s)
    if m and not re.search(r"не (поставляем|продаем|торгуем)", s):
        items = _split_items(m.group(1))
        if items:
            for it in items:
                if it not in prof.keywords:
                    prof.keywords.append(it)
            _add(out, "profile", "Ключевые слова: " + ", ".join(items), src)
    m = re.search(r"(?:не (?:поставляем|продаем|торгуем|берем|берём)|исключить|кроме)\s+(.+)", s)
    if m and not find_regions(m.group(1)) and not any(re.search(p, m.group(1)) for p, _, _ in METHODS):
        items = _split_items(m.group(1))
        if items:
            for it in items:
                if it not in prof.exclude_keywords:
                    prof.exclude_keywords.append(it)
            _add(out, "profile", "Исключить, если в предмете: " + ", ".join(items), src)


def _importance(s: str, src: str, out: ParseOutcome) -> None:
    high = re.search(r"очень важн|самое главное|главное|критичн|в первую очередь|приоритет", s)
    low = re.search(r"не важн|неважн|не так важн|не критичн|без разницы", s)
    if not (high or low):
        return
    for key, pattern in FACTOR_WORDS.items():
        if re.search(pattern, s):
            if key == "finance" and "аванс" in s:
                continue  # аванс обрабатывается отдельно
            settings = getattr(out.preferences, key)
            settings.importance = 5 if high else 1
            _add(out, key, f"Важность «{key}» — {'высокая' if high else 'низкая'}", src)


# ---------------- LLM ----------------

_SYSTEM = """Ты переводишь критерии отбора госзакупок поставщика в JSON. Отвечай только JSON.
Поля (заполняй только упомянутые):
price_min_rub, price_max_rub — числа в рублях;
regions — список {name, priority: 1 или 0.5}; excluded_regions — список названий;
min_days_to_deadline — дней на подготовку заявки; days_required — true, если «минимум/обязатело»;
min_contract_days; guarantee_limit_rub; advance — "ignore" | "want" | "must";
methods — объект {e_auction|open_contest|quotation_request|proposal_request: "prefer"|"neutral"|"exclude"};
laws — список из "44-FZ", "223-FZ"; keywords, exclude_keywords — товары/работы;
importance — объект {profile|price|geo|timing|finance|conditions|customer: 0..5};
recognized — список {label, source_text} по-русски; unparsed — фразы, которые не удалось понять."""

_EXAMPLE_IN = "Работаем в Томской области, в Кемеровской — если выгодно. Контракты до 10 млн. Конкурсы не берём."
_EXAMPLE_OUT = {
    "regions": [{"name": "Томская область", "priority": 1}, {"name": "Кемеровская область", "priority": 0.5}],
    "price_max_rub": 10000000,
    "methods": {"open_contest": "exclude"},
    "recognized": [
        {"label": "Регионы: Томская обл., Кемеровская обл. (пониженный приоритет)", "source_text": "Работаем в Томской области, в Кемеровской — если выгодно"},
        {"label": "НМЦК до 10 млн ₽", "source_text": "Контракты до 10 млн"},
        {"label": "Исключить конкурсы", "source_text": "Конкурсы не берём"},
    ],
    "unparsed": [],
}


def _apply_llm(data: dict, prefs: Preferences) -> list[Recognized]:
    rec: list[Recognized] = []
    p = prefs
    if isinstance(data.get("price_min_rub"), (int, float)):
        p.price.min_rub = float(data["price_min_rub"])
    if isinstance(data.get("price_max_rub"), (int, float)):
        p.price.max_rub = float(data["price_max_rub"])
    for item in data.get("regions") or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        prio = float(item.get("priority", 1)) if isinstance(item, dict) else 1.0
        for r in find_regions(name or ""):
            p.geo.regions[r.code] = 0.5 if prio < 1 else 1.0
        for d in find_districts(name or ""):
            for r in regions_of_district(d):
                p.geo.regions.setdefault(r.code, 0.5 if prio < 1 else 1.0)
    for name in data.get("excluded_regions") or []:
        for r in find_regions(str(name)):
            p.geo.excluded.append(r.code)
            p.geo.regions.pop(r.code, None)
    if isinstance(data.get("min_days_to_deadline"), int):
        p.timing.min_days_to_deadline = data["min_days_to_deadline"]
        p.timing.required = bool(data.get("days_required"))
    if isinstance(data.get("min_contract_days"), int):
        p.timing.min_contract_days = data["min_contract_days"]
    if isinstance(data.get("guarantee_limit_rub"), (int, float)):
        p.finance.guarantee_limit_rub = float(data["guarantee_limit_rub"])
    if data.get("advance") in ("ignore", "want", "must"):
        p.finance.advance = data["advance"]
    for k, v in (data.get("methods") or {}).items():
        if k in ("e_auction", "open_contest", "quotation_request", "proposal_request", "single_supplier") and v in ("prefer", "neutral", "exclude"):
            p.conditions.methods[k] = v
    laws = [x for x in data.get("laws") or [] if x in ("44-FZ", "223-FZ")]
    if laws:
        p.conditions.laws = laws
    for kw in data.get("keywords") or []:
        if isinstance(kw, str) and kw not in p.profile.keywords:
            p.profile.keywords.append(kw)
    for kw in data.get("exclude_keywords") or []:
        if isinstance(kw, str) and kw not in p.profile.exclude_keywords:
            p.profile.exclude_keywords.append(kw)
    for k, v in (data.get("importance") or {}).items():
        if hasattr(p, k) and isinstance(v, (int, float)) and k not in ("custom_rules", "thresholds"):
            getattr(p, k).importance = max(0, min(5, int(v)))
    for r in data.get("recognized") or []:
        if isinstance(r, dict) and r.get("label"):
            rec.append(Recognized(factor="llm", label=str(r["label"]), source_text=str(r.get("source_text", ""))))
    return rec


def parse_criteria(text: str, base: Preferences | None = None, use_llm: bool = True) -> ParseOutcome:
    """Сначала правила; затем, если LLM доступна, она разбирает то, что правила не поняли."""
    outcome = parse_rules(text, base)
    if not use_llm or not outcome.unparsed:
        return outcome
    if not llm.provider_status().get("ready"):
        return outcome
    leftover = ". ".join(outcome.unparsed)
    data = llm.complete_json(
        _SYSTEM,
        f"Пример.\nТекст: {_EXAMPLE_IN}\nJSON: {json.dumps(_EXAMPLE_OUT, ensure_ascii=False)}\n\nТекст: {leftover}\nJSON:",
    )
    if not isinstance(data, dict):
        return outcome
    try:
        recognized = _apply_llm(data, outcome.preferences)
    except (TypeError, ValueError):
        return outcome
    outcome.preferences = Preferences.model_validate(outcome.preferences.model_dump())
    outcome.recognized += recognized
    unparsed = [u for u in data.get("unparsed") or [] if isinstance(u, str)]
    outcome.unparsed = unparsed if recognized else outcome.unparsed
    outcome.engine = "rules+llm"
    return outcome


def describe_regions(codes: dict[str, float]) -> str:
    return ", ".join(f"{BY_CODE[c].name}{' (½)' if v < 1 else ''}" for c, v in codes.items() if c in BY_CODE)
