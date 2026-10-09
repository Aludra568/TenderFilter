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
from functools import lru_cache

from app.config import get_settings
from app.nlp.morph import lemmas


STOPWORDS = {
    # служебные слова предметов закупки (в начальной форме) — встречаются почти везде и не говорят о профиле
    "поставка", "нужда", "оказание", "услуга", "выполнение", "работа", "закупка", "приобретение", "обеспечение",
    "государственный", "муниципальный", "учреждение", "бюджетный", "казённый", "казенный", "автономный",
    "областной", "городской", "район", "год", "период", "соответствие", "согласно", "товар", "предмет",
    "контракт", "договор", "право", "заключение", "для", "на", "по", "и", "в", "с", "из", "к", "от", "до", "или",
    "а", "не", "мбу", "мбоу", "гбу", "гбуз", "огбу", "фгбу", "мку", "оборудование", "техника", "материал",
    "изделие", "устройство", "средство", "продукция", "прочий", "организация", "нуждаться",
}


def tokens(text: str) -> list[str]:
    """Начальные формы значимых слов (морфология pymorphy3): «ноутбуков» → «ноутбук»."""
    return [w for w in lemmas(text) if w not in STOPWORDS and (len(w) >= 3 or w.isdigit())]


def stem(word: str) -> str:
    return word  # слова уже в начальной форме


def _features(text: str) -> list[tuple[str, float]]:
    feats: list[tuple[str, float]] = []
    for w in tokens(text):
        feats.append(("w:" + stem(w), 1.0))
        padded = f" {w} "
        for i in range(len(padded) - 2):
            feats.append(("c:" + padded[i : i + 3], 0.35))
    return feats


def embed(text: str, dim: int | None = None) -> list[float]:
    return list(_embed_cached(text, dim or get_settings().embedding_dim))


@lru_cache(maxsize=20_000)
def _embed_cached(text: str, dim: int) -> tuple[float, ...]:
    vec = [0.0] * dim
    for feat, weight in _features(text):
        h = zlib.crc32(feat.encode("utf-8"))
        idx = h % dim
        sign = 1.0 if (h >> 16) & 1 else -1.0
        vec[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return tuple(vec)
    return tuple(v / norm for v in vec)


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
