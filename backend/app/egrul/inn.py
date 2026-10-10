"""Проверка контрольной суммы ИНН до обращения к внешним сервисам."""

_W10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
_W12_1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
_W12_2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]


def _check(digits: list[int], weights: list[int]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(inn: str) -> bool:
    if not inn or not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(c) for c in inn]
    if len(inn) == 10:
        return _check(d, _W10) == d[9]
    return _check(d, _W12_1) == d[10] and _check(d, _W12_2) == d[11]


def make_valid_inn(prefix9: str) -> str:
    """Достраивает контрольную цифру к 9 цифрам — для демо-данных."""
    d = [int(c) for c in prefix9]
    return prefix9 + str(_check(d, _W10))
