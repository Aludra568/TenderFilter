"""Нечёткая логика для факторов скоринга.

Вместо жёстких порогов («до 30 млн — да, 30,1 млн — нет») каждый числовой параметр — лингвистическая
переменная с термами и функциями принадлежности. Итоговый балл фактора — нечёткий вывод Сугено
нулевого порядка: среднее значений термов, взвешенное степенями принадлежности.

Пример: до окончания подачи 5 дней при минимуме 3 → μ(«мало»)=0, μ(«нормально»)=0,5, μ(«достаточно»)=0,5,
балл = (0,6·0,5 + 1,0·0,5) / 1 = 0,8.
"""

from dataclasses import dataclass


def trapezoid(x: float, a: float, b: float, c: float, d: float) -> float:
    """0 до a, линейный рост a→b, 1 на [b, c], линейный спад c→d, 0 после d."""
    if x <= a or x >= d:
        return 1.0 if b <= x <= c else 0.0
    if x < b:
        return (x - a) / (b - a) if b > a else 1.0
    if x <= c:
        return 1.0
    return (d - x) / (d - c) if d > c else 1.0


def rising(x: float, a: float, b: float) -> float:
    """0 до a, 1 после b."""
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    return (x - a) / (b - a)


def falling(x: float, a: float, b: float) -> float:
    return 1.0 - rising(x, a, b)


@dataclass
class Inference:
    score: float
    memberships: dict[str, float]  # терм → степень принадлежности
    dominant: str

    def describe(self) -> str:
        parts = [f"«{t}» {m:.2f}".replace(".", ",") for t, m in self.memberships.items() if m > 0.001]
        return "μ: " + ", ".join(parts)


def sugeno(memberships: dict[str, float], outputs: dict[str, float]) -> Inference:
    total = sum(memberships.values())
    score = sum(memberships[t] * outputs[t] for t in memberships) / total if total else 0.0
    dominant = max(memberships, key=memberships.get)
    return Inference(round(score, 3), {t: round(m, 3) for t, m in memberships.items()}, dominant)


# ---------- лингвистические переменные ----------

def price_fit(nmck: float, low: float | None, high: float | None) -> Inference:
    """«Подходит ли цена»: ядро — ваш диапазон, плечи — до ½ минимума и до 1,5 максимума."""
    lo = low or 0.0
    hi = high if high is not None else float("inf")
    if hi == float("inf"):
        mu = rising(nmck, 0.5 * lo, lo) if lo else 1.0
    else:
        mu = trapezoid(nmck, 0.5 * lo if lo else -1.0, lo if lo else -0.5, hi, 1.5 * hi)
    return sugeno({"подходит": mu, "не подходит": 1 - mu}, {"подходит": 1.0, "не подходит": 0.0})


def time_left(days: float, min_days: float) -> Inference:
    """Время на подготовку заявки: «мало» (меньше минимума), «нормально», «достаточно» (от недели)."""
    full = max(7.0, min_days)
    short = falling(days, min_days - 1, min_days)
    enough = rising(days, min_days, full) if full > min_days else (1.0 if days >= full else 0.0)
    normal = max(0.0, 1.0 - short - enough)
    return sugeno({"мало": short, "нормально": normal, "достаточно": enough},
                  {"мало": 0.2, "нормально": 0.6, "достаточно": 1.0})


def guarantee_load(ratio: float) -> Inference:
    """Нагрузка обеспечений относительно вашего лимита: «лёгкая», «заметная», «тяжёлая»."""
    light = falling(ratio, 0.5, 0.6)
    heavy = rising(ratio, 1.0, 1.4)
    medium = max(0.0, 1.0 - light - heavy)
    return sugeno({"лёгкая": light, "заметная": medium, "тяжёлая": heavy},
                  {"лёгкая": 1.0, "заметная": 0.7, "тяжёлая": 0.0})


def curves(min_rub: float | None, max_rub: float | None, min_days: int) -> dict:
    """Точки функций принадлежности для графиков в интерфейсе."""
    top = (max_rub or (min_rub or 1e7) * 3) * 2
    price_points = [{"x": round(top * i / 60), "mu": price_fit(top * i / 60, min_rub, max_rub).memberships["подходит"]}
                    for i in range(61)]
    days_points = []
    for i in range(0, 61):
        d = i * 15 / 60
        inf = time_left(d, min_days)
        days_points.append({"x": round(d, 2), **inf.memberships})
    load_points = [{"x": round(r * 2 / 60, 3), **guarantee_load(r * 2 / 60).memberships} for r in range(61)]
    return {"price": price_points, "time_left": days_points, "guarantee_load": load_points}
