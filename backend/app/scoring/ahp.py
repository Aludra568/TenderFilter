"""Метод анализа иерархий (Т. Саати) для весов факторов.

Пользователь отвечает на несколько вопросов «что важнее и во сколько раз» по шкале Саати 1–9.
Полная матрица 7×7 требует 21 сравнения, поэтому используем неполные сравнения и метод
логарифмических наименьших квадратов (LLSM): веса w минимизируют Σ (ln w_a − ln w_b − ln a_ab)².
Пропущенные элементы матрицы достраиваются как w_i / w_j (метод Харкера), затем считается
индекс согласованности CR = (λmax − n) / (n − 1) / RI. CR ≤ 0,1 — ответы согласованы.
"""

import math

import numpy as np

# Случайный индекс согласованности Саати для n = 1..10
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def weights_from_pairs(keys: list[str], pairs: list[tuple[str, str, float]]) -> dict:
    """pairs: (a, b, v) — «a важнее b в v раз» (v < 1 — наоборот). Возвращает веса, CR и худшие пары."""
    n = len(keys)
    idx = {k: i for i, k in enumerate(keys)}
    pairs = [(a, b, v) for a, b, v in pairs if a in idx and b in idx and a != b and v > 0]
    w = _llsm(idx, pairs)

    # Достроенная матрица (Харкер): известные сравнения + отношения весов для пропусков.
    matrix = np.outer(w, 1 / w)
    for a, b, v in pairs:
        matrix[idx[a], idx[b]] = v
        matrix[idx[b], idx[a]] = 1 / v
    lam = float(np.max(np.real(np.linalg.eigvals(matrix))))
    ci = (lam - n) / (n - 1) if n > 1 else 0.0
    cr = ci / RANDOM_INDEX.get(n, 1.49) if RANDOM_INDEX.get(n) else 0.0

    # Какой ответ сильнее всего спорит с остальными: убираем его, пересчитываем веса по остальным
    # и сравниваем «как ответили» с «что следует из остальных ответов» (leave-one-out).
    deviations = []
    for i, (a, b, v) in enumerate(pairs):
        rest = pairs[:i] + pairs[i + 1:]
        if not connected(idx, rest, a, b):
            continue  # без этого ответа пара не связана — сравнивать не с чем
        wr = _llsm(idx, rest)
        implied = wr[idx[a]] / wr[idx[b]]
        deviations.append({"a": a, "b": b, "given": v, "implied": round(float(implied), 4),
                           "error": round(abs(math.log(v) - math.log(implied)), 3)})
    deviations.sort(key=lambda d: -d["error"])
    return {
        "weights": {k: round(float(w[idx[k]]), 4) for k in keys},
        "lambda_max": round(lam, 4),
        "cr": round(max(cr, 0.0), 4),
        "consistent": cr <= 0.1,
        "worst_pairs": deviations[:3],
    }


def _llsm(idx: dict[str, int], pairs: list[tuple[str, str, float]]) -> np.ndarray:
    n = len(idx)
    rows, rhs = [], []
    for a, b, v in pairs:
        row = np.zeros(n)
        row[idx[a]], row[idx[b]] = 1.0, -1.0
        rows.append(row)
        rhs.append(math.log(v))
    # Нормировка: Σ ln w = 0 (иначе система определена с точностью до множителя).
    rows.append(np.ones(n))
    rhs.append(0.0)
    logw, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    w = np.exp(logw)
    return w / w.sum()


def connected(idx: dict[str, int], pairs: list[tuple[str, str, float]], a: str, b: str) -> bool:
    seen, stack = {a}, [a]
    while stack:
        x = stack.pop()
        for p, q, _ in pairs:
            for y in ((q,) if p == x else (p,) if q == x else ()):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
    return b in seen


# Набор вопросов: связный граф по 7 факторам с циклами — хватает для весов и проверки согласованности.
DEFAULT_PAIRS = [
    ("profile", "price"), ("profile", "geo"), ("profile", "timing"), ("profile", "conditions"),
    ("price", "geo"), ("price", "finance"), ("geo", "timing"), ("timing", "finance"),
    ("finance", "conditions"), ("conditions", "customer"),
]


def roc_weights(ranking: list[str]) -> dict[str, float]:
    """Веса по ранжированию (Rank Order Centroid, Barron & Barrett 1996).

    Пользователь просто упорядочивает факторы от важного к неважному — без 10–21 попарного сравнения.
    w_i = (1/n) · Σ_{k=i..n} 1/k. Для 7 факторов: 37 %, 23 %, 16 %, 11 %, 7 %, 4 %, 2 %.
    """
    n = len(ranking)
    return {key: round(sum(1 / k for k in range(i + 1, n + 1)) / n, 4) for i, key in enumerate(ranking)}


def advise(result: dict, keys_label: dict[str, str] | None = None) -> list[str]:
    """Подсказки вместо отказа: при CR > 0,1 веса всё равно считаются, а пользователю показываем,
    какие ответы противоречат остальным и какое значение было бы согласованным."""
    if result["consistent"]:
        return []
    label = (keys_label or {}).get
    tips = [f"Ответы противоречивы (CR = {result['cr']:.2f} > 0,10) — веса посчитаны, но стоит перепроверить:"
            .replace(".", ",", 1)]
    for p in result["worst_pairs"][:2]:
        a, b = label(p["a"], p["a"]), label(p["b"], p["b"])
        tips.append(f"«{a}» против «{b}»: вы указали {_fmt(p['given'])}, "
                    f"остальные ответы говорят ≈ {_fmt(p['implied'])}")
    return tips


def _fmt(v: float) -> str:
    x = v if v >= 1 else 1 / v
    num = f"{x:.3g}".replace(".", ",")
    times = "раза" if ("," in num or (int(x) % 10 in (2, 3, 4) and int(x) % 100 not in (12, 13, 14))) else "раз"
    return f"важнее в {num} {times}" if v >= 1 else f"менее важно в {num} {times}"
