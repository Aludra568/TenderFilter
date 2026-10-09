"""Морфология русского языка: словарный анализатор pymorphy3 (OpenCorpora), без нейросетей.

Даёт начальные формы слов («Томской» → «томский», «лямов» → «лям», «поставляем» → «поставлять»)
с позициями в исходном тексте и токенизатор для формальных грамматик yargy.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

import pymorphy3
from yargy.morph import MorphAnalyzer
from yargy.tokenizer import MorphTokenizer

_WORD = re.compile(r"[a-zа-яё]+|\d+(?:[.,]\d+)?|[^\sa-zа-яё\d]", re.I)


@lru_cache(maxsize=1)
def analyzer() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


class _YargyMorph(MorphAnalyzer):
    """Адаптер: yargy 0.16 по умолчанию тянет устаревший pymorphy2 — подставляем pymorphy3."""

    def __init__(self) -> None:
        super().__init__(raw=analyzer())

    __call__ = lru_cache(maxsize=50_000)(MorphAnalyzer.__call__)


@lru_cache(maxsize=1)
def tokenizer() -> MorphTokenizer:
    return MorphTokenizer(morph=_YargyMorph())


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if not w.isalpha():
        return w
    return analyzer().parse(w)[0].normal_form.replace("ё", "е")


@dataclass(frozen=True)
class Token:
    text: str
    lemma: str
    start: int
    end: int


def tokens(text: str) -> list[Token]:
    return [Token(m.group(), lemma(m.group()), m.start(), m.end()) for m in _WORD.finditer(text)]


def lemmas(text: str) -> list[str]:
    return [t.lemma for t in tokens(text) if t.lemma[:1].isalnum()]


def lemma_text(text: str) -> str:
    return " ".join(lemmas(text))
