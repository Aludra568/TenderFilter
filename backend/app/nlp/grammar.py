"""Формальные грамматики (yargy) для денежных сумм и сроков в критериях.

Разбирают «от 1 до 30 млн», «не больше 2 млн рублей», «около 10 лямов», «полтора миллиона»,
«минимум 3 рабочих дня», «до двух недель». Слова сравниваются по начальной форме (pymorphy3),
поэтому падежи и числа не важны.
"""

from dataclasses import dataclass
from functools import lru_cache

from yargy import Parser, or_, rule
from yargy.predicates import caseless, dictionary, in_, in_caseless, normalized, type as token_type

from app.nlp.morph import tokenizer

INT = token_type("INT")
WORD_NUMBERS = {"полтора": 1.5, "полторы": 1.5, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
                "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "пятнадцать": 15,
                "двадцать": 20, "тридцать": 30, "сто": 100}
NUMBER = or_(
    rule(INT, in_({",", "."}), INT),
    rule(INT),
    rule(dictionary(set(WORD_NUMBERS))),
)
UNITS = {"тысяча": 1e3, "тыс": 1e3, "т": 1e3, "к": 1e3, "тыщ": 1e3, "млн": 1e6, "миллион": 1e6, "лям": 1e6,
         "лимон": 1e6, "кк": 1e6, "млрд": 1e9, "миллиард": 1e9, "ярд": 1e9}
UNIT = rule(dictionary(set(UNITS)), in_({"."}).optional())
CURRENCY = rule(dictionary({"рубль", "руб", "р", "₽"}), in_({"."}).optional())
AMOUNT = rule(NUMBER, UNIT.optional(), CURRENCY.optional())

MAX_WORDS = rule(caseless("не"), in_caseless({"более", "больше", "выше", "дороже", "свыше"}))
MIN_WORDS = rule(caseless("не"), in_caseless({"менее", "меньше", "ниже", "дешевле"}))
PREFIX = or_(
    rule(in_caseless({"до", "максимум", "потолок", "в пределах"})),
    rule(in_caseless({"пределах"})),
    MAX_WORDS,
    rule(in_caseless({"от", "минимум", "свыше", "больше", "дороже", "выше"})),
    MIN_WORDS,
    rule(in_caseless({"дешевле", "ниже", "меньше"})),
    rule(in_caseless({"около", "примерно", "порядка", "приблизительно", "ориентировочно"})),
    rule(caseless("в"), in_caseless({"районе", "район"})),
)
RANGE = rule(caseless("от"), AMOUNT, in_caseless({"до", "-", "—"}), AMOUNT)
BOUNDED = rule(PREFIX, AMOUNT)
MONEY = or_(RANGE, BOUNDED, AMOUNT)

DAY_UNITS = {"день": 1, "сутки": 1, "неделя": 7, "месяц": 30}
DURATION = rule(PREFIX.optional(), NUMBER, dictionary({"рабочий", "календарный"}).optional(),
                dictionary(set(DAY_UNITS)))

MAX_SET = {"до", "максимум", "потолок", "пределах", "более", "больше", "выше", "дороже", "свыше"}
MIN_SET = {"от", "минимум", "менее", "меньше", "ниже", "дешевле"}
AROUND_SET = {"около", "примерно", "порядка", "приблизительно", "ориентировочно", "районе", "район"}


@dataclass
class Amount:
    low: float | None
    high: float | None
    kind: str  # range | min | max | around | exact
    start: int
    end: int
    has_unit: bool


@dataclass
class Duration:
    days: int
    kind: str  # min | max | exact
    start: int
    end: int
    working: bool


@lru_cache(maxsize=1)
def _parsers() -> tuple[Parser, Parser]:
    tok = tokenizer()
    return Parser(MONEY, tokenizer=tok), Parser(DURATION, tokenizer=tok)


def _number(tokens: list, i: int) -> tuple[float | None, int]:
    t = tokens[i]
    if t.type == "INT":
        if i + 2 < len(tokens) and tokens[i + 1].value in ",." and tokens[i + 2].type == "INT":
            return float(f"{t.value}.{tokens[i + 2].value}"), i + 3
        return float(t.value), i + 1
    norm = t.value.lower()
    for form in _forms(t):
        if form.normalized in WORD_NUMBERS:
            return float(WORD_NUMBERS[form.normalized]), i + 1
    return (float(WORD_NUMBERS[norm]), i + 1) if norm in WORD_NUMBERS else (None, i + 1)


def _unit(tokens: list, i: int) -> tuple[float | None, int]:
    if i < len(tokens):
        for form in _forms(tokens[i]):
            if form.normalized in UNITS:
                j = i + 1
                if j < len(tokens) and tokens[j].value == ".":
                    j += 1
                return UNITS[form.normalized], j
    return None, i


def _amounts_in(tokens: list) -> list[tuple[float, bool]]:
    """Все числа с множителями внутри совпадения: [(значение, был_ли_множитель)]."""
    out, i = [], 0
    while i < len(tokens):
        if tokens[i].type == "INT" or any(f.normalized in WORD_NUMBERS for f in _forms(tokens[i])):
            value, i = _number(tokens, i)
            mult, i = _unit(tokens, i)
            if value is not None:
                out.append((value * (mult or 1), mult is not None))
        else:
            i += 1
    return out


def extract_amounts(text: str, default_unit: float | None = None) -> list[Amount]:
    """Денежные суммы. default_unit — множитель для чисел без «млн/тыс», если он ясен из контекста."""
    money_parser, _ = _parsers()
    results: list[Amount] = []
    for match in money_parser.findall(text):
        toks = match.tokens
        first = toks[0].value.lower()
        values = _amounts_in(toks)
        if not values:
            continue
        if len(values) >= 2 and first == "от":
            (lo, lo_unit), (hi, hi_unit) = values[0], values[1]
            # «от 1 до 30 млн»: множитель второго числа относится и к первому.
            if not lo_unit and hi_unit:
                mult = hi / _strip(toks, 1) if _strip(toks, 1) else 1
                lo = lo * mult
            results.append(Amount(lo, hi, "range", match.span.start, match.span.stop, lo_unit or hi_unit))
            continue
        value, has_unit = values[-1]
        if not has_unit and default_unit:
            value *= default_unit
        words = {t.value.lower() for t in toks[:2]}
        kind = "max" if words & MAX_SET and not (first == "не" and words & MIN_SET) else "exact"
        if first == "от" or words & MIN_SET and (first in ("от", "минимум") or "не" in words):
            kind = "min" if not words & {"более", "больше", "выше", "дороже", "свыше"} else "max"
        if first in ("свыше", "больше", "дороже", "выше"):
            kind = "min"  # «дороже 500 тыс.» — нижняя граница
        elif first in ("дешевле", "ниже", "меньше"):
            kind = "max"
        if words & AROUND_SET:
            kind = "around"
        lo = value if kind in ("min", "exact", "around") else None
        hi = value if kind in ("max", "exact", "around") else None
        results.append(Amount(lo, hi, kind, match.span.start, match.span.stop, has_unit or bool(default_unit)))
    return results


def _strip(tokens: list, n: int) -> float | None:
    """Чистое число n-й группы (без множителя) — для переноса множителя в диапазонах."""
    nums = []
    i = 0
    while i < len(tokens):
        if tokens[i].type == "INT" or any(f.normalized in WORD_NUMBERS for f in _forms(tokens[i])):
            v, i = _number(tokens, i)
            nums.append(v)
        else:
            i += 1
    return nums[n] if len(nums) > n else None


def extract_durations(text: str) -> list[Duration]:
    _, duration_parser = _parsers()
    out: list[Duration] = []
    for match in duration_parser.findall(text):
        toks = match.tokens
        words = {t.value.lower() for t in toks}
        idx = next(i for i, t in enumerate(toks) if t.type == "INT" or any(f.normalized in WORD_NUMBERS for f in _forms(t)))
        value, _ = _number(toks, idx)
        unit = next((DAY_UNITS[f.normalized] for t in toks for f in _forms(t) if f.normalized in DAY_UNITS), 1)
        working = any(f.normalized == "рабочий" for t in toks for f in _forms(t))
        days = round((value or 0) * unit * (1.4 if working else 1))
        kind = "min" if words & {"минимум", "от", "менее", "меньше"} else "max" if words & {"до", "максимум", "более", "больше"} else "exact"
        out.append(Duration(days, kind, match.span.start, match.span.stop, working))
    return out


def _forms(token) -> list:
    """У числовых и пунктуационных токенов yargy нет морфологических форм."""
    return getattr(token, "forms", None) or []
