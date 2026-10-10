"""Текст критериев → предпочтения профиля. Гибридная экспертная система без нейросетей в основе.

Конвейер разбора:
1. Морфология (pymorphy3, словарь OpenCorpora): каждое слово приводится к начальной форме,
   поэтому «аукционах», «аукционы», «аукциона» — одно и то же.
2. Формальные грамматики (yargy) для сумм и сроков: «от 1 до 30 млн», «около 10 лямов»,
   «не больше 2 млн руб.», «минимум 5 рабочих дней».
3. Правила со справочниками (89 регионов, 8 федеральных округов, способы закупки) и областью
   действия отрицания внутри части предложения: «конкурсы не берём, аукционы — да».
4. Лингвистические модификаторы → нечёткая логика: «около» → нечёткий диапазон,
   «если выгодно / желательно» → пониженная степень принадлежности, «только / строго» → жёсткое условие.
5. LLM — необязательный модуль только для фраз, которые не поняли шаги 1–4.
Каждое распознанное правило помнит фразу-источник, нераспознанные фразы возвращаются пользователю.
"""

import json
import re
import time
from dataclasses import dataclass, field

from app.domain import Preferences
from app.nlp import llm
from app.nlp.grammar import extract_amounts, extract_durations
from app.nlp.morph import tokens as morph_tokens
from app.reference.regions import BY_CODE, find_districts, find_regions, normalize, regions_of_district

# Леммы-маркеры (сравниваются с начальными формами слов).
SOFT = {"выгодно", "выгодный", "возможность", "иногда", "желательно", "желательный", "случай", "реже", "можно", "тоже"}
STRICT = {"только", "строго", "исключительно", "обязательно", "обязательный", "жёстко", "жестко", "нужно", "нужный",
          "минимум", "необходимо"}
NEG_WORDS = {"без", "кроме", "исключить", "исключая", "никогда", "запрет", "исключение"}
NEG_VERBS_STRONG = {"брать", "участвовать", "рассматривать", "работать", "интересовать", "подходить", "заходить",
                    "поставлять", "возить", "смотреть", "интересный", "тянуть", "потянуть", "осилить", "ездить"}
NEG_PHRASES = re.compile(r"не\s+по\s+(?:силам|карману|зубам)|не\s+наш\w*\s+(?:уровень|масштаб)", re.I)
NEG_VERBS_SOFT = {"любить", "любим", "любимый", "хотеть", "нравиться", "жаловать"}
SOFT_AVOID = {"избегать", "неохотно"}
MONEY_CTX = {"нмцк", "нмц", "цена", "сумма", "контракт", "лот", "бюджет", "стоимость", "закупка", "рубль", "руб"}
GUARANTEE_CTX = {"обеспечение", "обеспечить", "банковский", "гарантия"}
EXEC_CTX = {"исполнение", "исполнять", "поставка", "поставить", "выполнение", "выполнить", "отгрузка"}
BID_CTX = {"заявка", "подготовка", "подача", "подготовить", "подать"}
SUPPLY_VERBS = {"поставлять", "продавать", "торговать", "заниматься", "специализироваться", "возить", "делать",
                "производить", "выпускать", "реализовывать", "оказывать", "выполнять", "привозить"}

METHODS = [
    ({"аукцион"}, "e_auction", "аукционы"),
    ({"конкурс"}, "open_contest", "конкурсы"),
    ({"котировка"}, "quotation_request", "запросы котировок"),
    ({"предложение"}, "proposal_request", "запросы предложений"),
    ({"единственный"}, "single_supplier", "закупки у единственного поставщика"),
]
FACTOR_LEMMAS = {
    "geo": {"регион", "география", "доставка", "логистика"},
    "price": {"нмцк", "цена", "сумма", "бюджет"},
    "profile": {"профиль", "товар", "ассортимент"},
    "timing": {"срок", "время"},
    "finance": {"обеспечение", "деньга", "деньги", "финансы"},
    "customer": {"заказчик"},
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
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "preferences": json.loads(self.preferences.model_dump_json()),
            "recognized": [r.__dict__ for r in self.recognized],
            "unparsed": self.unparsed,
            "engine": self.engine,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


@dataclass
class Clause:
    text: str
    lemmas: list[str]

    @property
    def lset(self) -> set[str]:
        return set(self.lemmas)

    def has_bigram(self, a: set[str], b: set[str]) -> bool:
        return any(x in a and y in b for x, y in zip(self.lemmas, self.lemmas[1:], strict=False))

    def polarity(self) -> str:
        """strong — исключить, soft — без приоритета, none — утверждение."""
        if self.lset & NEG_WORDS or self.has_bigram({"не"}, NEG_VERBS_STRONG) or NEG_PHRASES.search(self.text):
            return "strong"
        if self.has_bigram({"не"}, NEG_VERBS_SOFT) or self.lset & SOFT_AVOID or self.has_bigram({"не"}, {"очень"}):
            return "soft"
        return "none"


def _rub(v: float) -> str:
    if v >= 1e6:
        return f"{v / 1e6:g}".replace(".", ",") + " млн ₽"
    if v >= 1e3:
        return f"{v / 1e3:g}".replace(".", ",") + " тыс. ₽"
    return f"{v:g} ₽"


_ABBR = re.compile(r"\b(?:тыс|руб|млн|млрд|обл|г|ул|д|р|см|п|ст|ч)\.$", re.I)


def split_sentences(text: str) -> list[str]:
    """Предложения по . ! ? ; и переводу строки, но не после сокращений («тыс.», «руб.», «обл.»)."""
    pieces = [p for p in re.split(r"(?<=[.!?;])\s+|\n+", text.strip()) if p]
    parts: list[str] = []
    for piece in pieces:
        # «500 тыс. до 30 млн» — после сокращения идёт строчная буква или цифра: это то же предложение.
        if parts and _ABBR.search(parts[-1]) and (piece[:1].islower() or piece[:1].isdigit()):
            parts[-1] = f"{parts[-1]} {piece}"
        else:
            parts.append(piece)
    return [p.strip(" .;") for p in parts if p.strip(" .;")]


def _clauses(sentence: str) -> list[Clause]:
    parts = [c.strip() for c in re.split(r",|\s—\s|\s-\s|;|\bа также\b|\bно\b", sentence) if c.strip()]
    return [Clause(p, [t.lemma for t in morph_tokens(p) if t.lemma[:1].isalnum()]) for p in parts]


def prenormalize(text: str) -> str:
    """Типографика, которую грамматикам удобнее видеть в одном виде."""
    text = re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", text)  # «2 000 000» → «2000000»
    text = re.sub(r"(?<!от )(?<![\d.,])(\d+(?:[.,]\d+)?)\s*[–—-]\s*(?=\d)", r"от \1 до ", text)  # «2–20 млн»
    text = re.sub(r"(?i)\b(не\s+меньше|не\s+менее|минимум|хотя\s+бы|как\s+минимум|до|не\s+больше|не\s+более|максимум)"
                  r"\s+(недел\w*|месяц\w*)", r"\1 1 \2", text)  # «не меньше недели» → «не меньше 1 недели»
    return text


def parse_rules(text: str, base: Preferences | None = None) -> ParseOutcome:
    text = prenormalize(text)
    prefs = (base or Preferences()).model_copy(deep=True)
    out = ParseOutcome(preferences=prefs)
    for sentence in split_sentences(text):
        s = normalize(sentence)
        clauses = _clauses(sentence)
        lem = {lemma for c in clauses for lemma in c.lemmas}
        before = len(out.recognized)
        _money(sentence, lem, clauses, out)
        _days(sentence, lem, out)
        _regions(s, sentence, clauses, out)
        _methods(sentence, clauses, out)
        _advance(sentence, lem, out)
        _laws(s, sentence, clauses, out)
        _smp_imports(sentence, lem, clauses, out)
        _customers(s, sentence, clauses, out)
        _keywords(sentence, out)
        _importance(sentence, lem, clauses, out)
        if len(out.recognized) == before:
            out.unparsed.append(sentence)
    return out


def _add(out: ParseOutcome, factor: str, label: str, src: str) -> None:
    out.recognized.append(Recognized(factor=factor, label=label, source_text=src))


def _clause_at(clauses: list[Clause], sentence: str, pos: int) -> Clause:
    acc = 0
    for c in clauses:
        idx = sentence.find(c.text, acc)
        if idx <= pos < idx + len(c.text):
            return c
        acc = max(acc, idx + len(c.text))
    return clauses[0] if clauses else Clause("", [])


def _money(sentence: str, lem: set[str], clauses: list[Clause], out: ParseOutcome) -> None:
    durations = extract_durations(sentence)
    default_unit = 1e6 if {"млн", "миллион", "лям"} & lem else 1e3 if {"тыс", "тысяча"} & lem else None
    for a in extract_amounts(sentence, default_unit=default_unit):
        if any(d.start <= a.start < d.end or a.start <= d.start < a.end for d in durations):
            continue  # «минимум 3 дня» — это срок, а не сумма
        clause = _clause_at(clauses, sentence, a.start)
        ctx = clause.lset | lem
        # Что ограничивает сумма — НМЦК или обеспечения? Решает ближайшее слово-контекст перед суммой.
        before = [t.lemma for t in morph_tokens(sentence[:a.start])][::-1]
        nearest = next((w for w in before if w in GUARANTEE_CTX or w in MONEY_CTX), None)
        is_guarantee = nearest in GUARANTEE_CTX if nearest else bool(lem & GUARANTEE_CTX and not lem & MONEY_CTX)
        if clause.lset & GUARANTEE_CTX:
            is_guarantee = True  # «обеспечение заявки и контракта до 3 млн» — про обеспечение, хоть рядом и «контракт»
        if not (a.has_unit or ctx & MONEY_CTX or is_guarantee):
            continue
        value_hi = a.high if a.high is not None else a.low
        if is_guarantee:
            fin = out.preferences.finance
            fin.guarantee_limit_rub = value_hi
            fin.required = bool(clause.lset & {"строго", "жёстко", "жестко", "обязательно"})
            _add(out, "finance", f"Обеспечения не больше {_rub(fin.guarantee_limit_rub)}", sentence)
            continue
        p = out.preferences.price
        kind = a.kind
        if clause.polarity() == "strong" and kind in ("min", "max", "exact"):
            # «до 100 тыс. не смотрим» = от 100 тыс.; «от 50 млн нам не по силам» = до 50 млн
            kind = {"min": "max", "max": "min"}.get(kind, "min" if {"до", "максимум"} & clause.lset else "max")
            a = type(a)(a.low if a.low is not None else a.high, a.high if a.high is not None else a.low,
                        kind, a.start, a.end, a.has_unit)
            value_hi = a.high
        if kind == "range":
            p.min_rub, p.max_rub = a.low, a.high
            _add(out, "price", f"НМЦК от {_rub(a.low)} до {_rub(a.high)}", sentence)
        elif kind == "around":
            # Нечёткий диапазон: «около N» = ядро N ±20 %, за краями — плавное убывание (см. scoring/fuzzy.py).
            p.min_rub, p.max_rub = round(a.low * 0.8), round(a.low * 1.2)
            _add(out, "price", f"НМЦК около {_rub(a.low)} (нечёткий диапазон {_rub(p.min_rub)} – {_rub(p.max_rub)})", sentence)
        elif kind == "max" or (kind == "exact" and {"до", "максимум"} & clause.lset and clause.polarity() != "strong"):
            p.max_rub = value_hi
            _add(out, "price", f"НМЦК до {_rub(value_hi)}", sentence)
        elif kind == "min":
            p.min_rub = a.low
            _add(out, "price", f"НМЦК от {_rub(a.low)}", sentence)


def _days(sentence: str, lem: set[str], out: ParseOutcome) -> None:
    for d in extract_durations(sentence):
        if lem & EXEC_CTX and not lem & BID_CTX:
            out.preferences.timing.min_contract_days = d.days
            _add(out, "timing", f"Срок исполнения не меньше {d.days} дн.", sentence)
            continue
        out.preferences.timing.min_days_to_deadline = d.days
        strict = d.kind == "min" or bool(lem & STRICT)
        out.preferences.timing.required = strict
        _add(out, "timing", f"Минимум {d.days} дн. на подготовку заявки" + (" (обязательно)" if strict else ""), sentence)
        return


WAREHOUSE = {"склад", "филиал", "представительство", "логистический", "дилер"}


def _regions(s: str, src: str, clauses: list[Clause], out: ParseOutcome) -> None:
    geo = out.preferences.geo
    hit = False
    for i, clause in enumerate(clauses):
        regs = list(find_regions(clause.text))
        for d in find_districts(clause.text):
            regs += [r for r in regions_of_district(d) if r not in regs]
        if not regs:
            continue
        if clause.lset & WAREHOUSE:
            # «склад в Красноярске», «филиал в Томске» — своя логистика в регионе
            for r in regs:
                if r.code not in geo.warehouses:
                    geo.warehouses.append(r.code)
            _add(out, "geo", "Склады и филиалы: " + ", ".join(r.name for r in regs[:4]), src)
            hit = True
            continue
        nxt = clauses[i + 1] if i + 1 < len(clauses) else None
        excluded = clause.polarity() == "strong"
        soft = bool(clause.lset & SOFT) or bool(nxt and nxt.lset & SOFT and not find_regions(nxt.text))
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
    if hit and any(c.lset & {"только", "строго", "исключительно"} for c in clauses):
        geo.required = True


def _methods(sentence: str, clauses: list[Clause], out: ParseOutcome) -> None:
    cond = out.preferences.conditions
    for clause in clauses:
        for lemmas, key, name in METHODS:
            if not clause.lset & lemmas:
                continue
            if key == "proposal_request" and "запрос" not in clause.lset:
                continue
            if key == "single_supplier" and "поставщик" not in clause.lset:
                continue
            pol = clause.polarity()
            if pol == "strong":
                cond.methods[key] = "exclude"
                _add(out, "conditions", f"Исключить {name}", sentence)
            elif pol == "soft":
                cond.methods[key] = "neutral"
                for _, other, _ in METHODS:
                    if other != key and cond.methods.get(other) != "exclude":
                        cond.methods.setdefault(other, "prefer")
                _add(out, "conditions", f"{name.capitalize()} — без приоритета", sentence)
            else:
                cond.methods[key] = "prefer"
                if clause.lset & {"только", "исключительно"}:
                    for _, other, _ in METHODS:
                        if other != key:
                            cond.methods[other] = "exclude"
                _add(out, "conditions", f"Предпочитаем {name}", sentence)


def _advance(sentence: str, lem: set[str], out: ParseOutcome) -> None:
    if not lem & {"аванс", "предоплата", "авансирование"}:
        return
    fin = out.preferences.finance
    words = morph_tokens(sentence)
    pairs = {(a.lemma, b.lemma) for a, b in zip(words, words[1:], strict=False)}
    if ("не", "важный") in pairs or ("не", "важно") in pairs or lem & {"неважный", "неважно", "разница", "принципиальный"}:
        fin.advance = "ignore"
        _add(out, "finance", "Аванс не важен", sentence)
    elif lem & {"обязательный", "обязательно", "только", "строго", "необходимо", "необходимый"} or ("без", "аванс") in pairs:
        fin.advance = "must"
        _add(out, "finance", "Аванс обязателен", sentence)
    else:
        fin.advance = "want"
        _add(out, "finance", "Аванс важен", sentence)
        if lem & {"очень", "критичный", "главный", "критично"}:
            fin.importance = 5


def _laws(s: str, src: str, clauses: list[Clause], out: ParseOutcome) -> None:
    has44, has223 = bool(re.search(r"44\s*-?\s*фз|\b44\b", s)), bool(re.search(r"223\s*-?\s*фз|\b223\b", s))
    if not (has44 or has223):
        return
    cond = out.preferences.conditions
    lem = {x for c in clauses for x in c.lset}
    if "только" in lem:
        cond.laws = ["44-FZ"] if has44 and not has223 else ["223-FZ"] if has223 and not has44 else ["44-FZ", "223-FZ"]
    elif any(c.polarity() == "strong" for c in clauses):
        cond.laws = ["223-FZ"] if has44 and not has223 else ["44-FZ"] if has223 and not has44 else cond.laws
    else:
        return
    _add(out, "conditions", "Законы: " + ", ".join(x.replace("-FZ", "-ФЗ") for x in cond.laws), src)


def _smp_imports(sentence: str, lem: set[str], clauses: list[Clause], out: ParseOutcome) -> None:
    cond = out.preferences.conditions
    if lem & {"смп", "мсп"} or ("малый" in lem and lem & {"предпринимательство", "бизнес"}):
        cond.prefer_smp = not any(c.polarity() == "strong" for c in clauses)
        _add(out, "conditions", "Приоритет закупкам для СМП" if cond.prefer_smp else "Без приоритета закупкам для СМП", sentence)
    if lem & {"импорт", "импортный"} and lem & (SUPPLY_VERBS | {"только"}):
        cond.imports_only = True
        _add(out, "conditions", "Поставляем импортные товары — нацрежим исключает закупку", sentence)


def _customers(s: str, src: str, clauses: list[Clause], out: ParseOutcome) -> None:
    inns = re.findall(r"\b(\d{10}|\d{12})\b", s)
    lem = {x for c in clauses for x in c.lset}
    if inns and "заказчик" in lem and any(c.polarity() == "strong" for c in clauses):
        for inn in inns:
            if inn not in out.preferences.customer.excluded_inns:
                out.preferences.customer.excluded_inns.append(inn)
        _add(out, "customer", "Не работаем с заказчиками: " + ", ".join(inns), src)


def _split_items(fragment: str) -> list[str]:
    items = re.split(r",|;|\bи\b|\bили\b|/", fragment)
    cleaned = []
    for it in items:
        it = re.sub(r"^\s*(а также|также|еще|ещё)\s+", "", it, flags=re.I).strip(" .:—-")
        if 2 < len(it) <= 60 and not find_regions(it) and not re.search(r"\d", it):
            cleaned.append(it.lower())
    return cleaned


def _keywords(sentence: str, out: ParseOutcome) -> None:
    prof = out.preferences.profile
    toks = morph_tokens(sentence)
    for i, t in enumerate(toks):
        if t.lemma not in SUPPLY_VERBS and not (t.lemma == "профиль" and i > 0 and toks[i - 1].lemma == "наш"):
            continue
        negated = i > 0 and toks[i - 1].lemma == "не"
        j = i + 1
        while j < len(toks) and toks[j].lemma in {"на", "с", "в", "по", ":", "—", "-"}:
            j += 1
        if j >= len(toks) or not toks[j].lemma[:1].isalnum():
            # «Мебель не поставляем»: объект стоит перед глаголом
            if negated and i > 1:
                fragment = re.sub(r"^\s*(мы|нам|у нас)\s+", "", sentence[:toks[i - 1].start], flags=re.I)
                items = _split_items(fragment)
                if items:
                    prof.exclude_keywords += [x for x in items if x not in prof.exclude_keywords]
                    _add(out, "profile", "Исключить, если в предмете: " + ", ".join(items), sentence)
            return
        rest = sentence[toks[j].start:]
        # «Поставляем канцтовары, кроме бумаги» — после «кроме» идут исключения
        parts = re.split(r"\b(?:кроме|за исключением|исключая|но не)\b", rest, maxsplit=1, flags=re.I)
        items = _split_items(parts[0])
        items = [x for x in items if not any(m & {t.lemma for t in morph_tokens(x)} for m, _, _ in METHODS)]
        excluded = _split_items(parts[1]) if len(parts) > 1 else []
        if not items and not excluded:
            return
        target = prof.exclude_keywords if negated else prof.keywords
        for it in items:
            if it not in target:
                target.append(it)
        for it in excluded:
            if it not in prof.exclude_keywords:
                prof.exclude_keywords.append(it)
        if items:
            label = "Исключить, если в предмете: " if negated else "Ключевые слова: "
            _add(out, "profile", label + ", ".join(items), sentence)
        if excluded:
            _add(out, "profile", "Исключить, если в предмете: " + ", ".join(excluded), sentence)
        return
    # «кроме / исключить X» без глагола поставки — исключаемые товары, если это не регион и не способ закупки.
    m = re.search(r"(?:исключить|кроме)\s+(.+)", sentence, flags=re.I)
    if m and not find_regions(m.group(1)):
        lem = {t.lemma for t in morph_tokens(m.group(1))}
        if not any(lemmas & lem for lemmas, _, _ in METHODS):
            items = _split_items(m.group(1))
            if items:
                prof.exclude_keywords += [x for x in items if x not in prof.exclude_keywords]
                _add(out, "profile", "Исключить, если в предмете: " + ", ".join(items), sentence)


def _importance(sentence: str, lem: set[str], clauses: list[Clause], out: ParseOutcome) -> None:
    pairs = {(a, b) for c in clauses for a, b in zip(c.lemmas, c.lemmas[1:], strict=False)}
    high = bool(lem & {"главный", "критичный", "критично", "приоритет"}) or ("очень", "важный") in pairs \
        or ("самый", "важный") in pairs or ("первый", "очередь") in pairs
    low = ("не", "важный") in pairs or bool(lem & {"неважный", "второстепенный"})
    if not (high or low):
        return
    for key, words in FACTOR_LEMMAS.items():
        if lem & words:
            if key == "finance" and lem & {"аванс", "предоплата"}:
                continue  # аванс обрабатывается отдельно
            getattr(out.preferences, key).importance = 5 if high else 1
            _add(out, key, f"Важность «{key}» — {'высокая' if high else 'низкая'}", sentence)


# ---------------- LLM ----------------

_SYSTEM = """Ты переводишь критерии отбора госзакупок поставщика в JSON. Отвечай только JSON.
Поля (заполняй только упомянутые):
price_min_rub, price_max_rub — числа в рублях;
regions — список {name, priority: 1 или 0.5}; excluded_regions — список названий;
min_days_to_deadline — дней на подготовку заявки; days_required — true, если «минимум/обязательно»;
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


def parse_criteria(text: str, base: Preferences | None = None, use_llm: bool = True,
                   timeout: float | None = None) -> ParseOutcome:
    """Сначала правила; затем, если LLM доступна, она разбирает то, что правила не поняли.

    timeout ограничивает ожидание LLM: не успела — остаётся результат правил (ТЗ: оценка < 10 с).
    """
    started = time.perf_counter()
    outcome = parse_rules(text, base)
    outcome.elapsed_ms = (time.perf_counter() - started) * 1000
    if not use_llm or not outcome.unparsed:
        return outcome
    if not llm.provider_status().get("ready"):
        return outcome
    leftover = ". ".join(outcome.unparsed)
    data = llm.complete_json(
        _SYSTEM,
        f"Пример.\nТекст: {_EXAMPLE_IN}\nJSON: {json.dumps(_EXAMPLE_OUT, ensure_ascii=False)}\n\nТекст: {leftover}\nJSON:",
        timeout=timeout,
    )
    outcome.elapsed_ms = (time.perf_counter() - started) * 1000
    if not isinstance(data, dict):
        outcome.engine = "rules (LLM не ответила вовремя)"
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
