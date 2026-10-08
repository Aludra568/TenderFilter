"""Векторные представления текста без скачивания моделей.

Хэшированные признаки (основы слов + символьные триграммы) дают устойчивое
семантическое сходство для коротких русских формулировок: «ноутбук» близко к
«ноутбуки портативные», «картридж» — к «расходные материалы для МФУ» через
общие триграммы и основы. Векторы сохраняются в pgvector и используются для
поиска похожих закупок и сравнения предмета закупки с профилем компании.
"""

import math
import re
import zlib

from app.config import get_settings

_WORD = re.compile(r"[a-zа-я0-9]+")

STOPWORDS = {
    "поставка", "поставку", "поставки", "для", "нужд", "нужды", "оказание", "оказанию", "услуг", "услуги",
    "выполнение", "работ", "работы", "закупка", "закупки", "приобретение", "обеспечения", "обеспечение",
    "государственного", "муниципального", "учреждения", "учреждений", "бюджетного", "казенного", "автономного",
    "областного", "городского", "района", "года", "году", "году", "период", "соответствии", "согласно",
    "товара", "товаров", "товар", "предмет", "контракта", "договора", "право", "заключения", "на", "по", "и",
    "в", "с", "из", "к", "от", "до", "или", "а", "не", "мбу", "мбоу", "гбу", "гбуз", "огбу", "фгбу", "мку",
    # общие слова почти любого предмета закупки — ничего не говорят о профиле
    "оборудование", "оборудования", "оборудованием", "техника", "техники", "технику", "материалы", "материалов",
    "изделия", "изделий", "устройства", "устройств", "средства", "средств", "продукция", "продукции", "прочих",
}


def tokens(text: str) -> list[str]:
    t = text.lower().replace("ё", "е")
    return [w for w in _WORD.findall(t) if w not in STOPWORDS and (len(w) >= 3 or w.isdigit())]


def stem(word: str) -> str:
    return word[:6] if len(word) > 6 else word


def _features(text: str) -> list[tuple[str, float]]:
    feats: list[tuple[str, float]] = []
    for w in tokens(text):
        feats.append(("w:" + stem(w), 1.0))
        padded = f" {w} "
        for i in range(len(padded) - 2):
            feats.append(("c:" + padded[i : i + 3], 0.35))
    return feats


def embed(text: str, dim: int | None = None) -> list[float]:
    dim = dim or get_settings().embedding_dim
    vec = [0.0] * dim
    for feat, weight in _features(text):
        h = zlib.crc32(feat.encode("utf-8"))
        idx = h % dim
        sign = 1.0 if (h >> 16) & 1 else -1.0
        vec[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def keyword_hits(keywords: list[str], text: str) -> list[str]:
    """Ключевые слова профиля, чьи основы встречаются в тексте."""
    words = {stem(w) for w in tokens(text)}
    hits = []
    for kw in keywords:
        kw_tokens = tokens(kw)
        if kw_tokens and all(stem(w) in words for w in kw_tokens):
            hits.append(kw)
    return hits
