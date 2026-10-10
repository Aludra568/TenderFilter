"""Классификатор ОКПД 2 по тексту: TF-IDF → LSA → голосование ближайших соседей.

Обучающие данные — позиции реальных извещений ЕИС (название товара/услуги и код ОКПД 2, который
поставил заказчик), app/reference/okpd_train.json. Без нейросети и без внешних моделей:
  1. Текст → начальные формы слов (pymorphy3) и пары соседних слов; веса TF-IDF.
  2. Латентно-семантический анализ: усечённое SVD матрицы TF-IDF сжимает слова в ~100 «тем»,
     поэтому «ноутбук» и «портативный компьютер» оказываются рядом, даже если слова разные.
  3. Ближайшие соседи по косинусу голосуют за код (уровень класса «26.20» и раздела «26»),
     сумма сходств даёт уверенность.
Качество меряется кросс-валидацией с разбиением по извещениям: `python -m app.reference.okpd_model`.
"""

import json
import math
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.reference.textvec import tokens

TRAIN = Path(__file__).resolve().parent / "okpd_train.json"


def _features(text: str) -> list[str]:
    words = tokens(text)
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


class OkpdModel:
    def __init__(self, items: list[dict], dims: int = 100, min_df: int = 2):
        docs = [_features(it["name"]) for it in items]
        df = Counter(f for d in docs for f in set(d))
        vocab = sorted(f for f, c in df.items() if c >= min_df)
        self.index = {f: i for i, f in enumerate(vocab)}
        n = len(docs)
        self.idf = np.array([math.log((1 + n) / (1 + df[f])) + 1 for f in vocab], dtype=np.float32)
        x = np.zeros((n, len(vocab)), dtype=np.float32)
        for r, d in enumerate(docs):
            for f, c in Counter(d).items():
                if f in self.index:
                    x[r, self.index[f]] = 1 + math.log(c)
        x *= self.idf
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)
        k = max(2, min(dims, min(x.shape) - 1))
        _, s, vt = np.linalg.svd(x, full_matrices=False)
        self.components = vt[:k]  # проекция TF-IDF → темы LSA
        emb = x @ self.components.T
        self.emb = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
        self.codes = [it["code"] for it in items]
        self.names = [it["name"] for it in items]

    def _vector(self, text: str) -> np.ndarray | None:
        v = np.zeros(len(self.index), dtype=np.float32)
        for f, c in Counter(_features(text)).items():
            if f in self.index:
                v[self.index[f]] = 1 + math.log(c)
        if not v.any():
            return None
        v *= self.idf
        e = self.components @ (v / np.linalg.norm(v))
        norm = np.linalg.norm(e)
        return e / norm if norm else None

    def predict(self, text: str, k: int = 7, level: int = 5) -> list[dict]:
        """Коды уровня level символов («26.20» — 5, «26» — 2) с уверенностью и примером из обучения."""
        v = self._vector(text)
        if v is None:
            return []
        sims = self.emb @ v
        top = np.argsort(-sims)[:k]
        votes: dict[str, float] = defaultdict(float)
        example: dict[str, str] = {}
        for i in top:
            if sims[i] <= 0:
                continue
            code = self.codes[i][:level]
            votes[code] += float(sims[i])
            example.setdefault(code, self.names[i])
        total = sum(votes.values()) or 1
        best_sim = float(sims[top[0]]) if len(top) else 0.0
        return [{"code": c, "confidence": round(w / total * min(1.0, best_sim / 0.6), 3), "example": example[c]}
                for c, w in sorted(votes.items(), key=lambda kv: -kv[1])]


@lru_cache(maxsize=1)
def model() -> OkpdModel | None:
    if not TRAIN.exists():
        return None
    items = json.loads(TRAIN.read_text(encoding="utf-8"))
    return OkpdModel(items) if len(items) >= 50 else None


def classify(text: str, level: int = 5) -> list[dict]:
    m = model()
    return m.predict(text, level=level) if m else []


def cross_validate(folds: int = 5) -> dict:
    items = json.loads(TRAIN.read_text(encoding="utf-8"))
    groups = sorted({it["notice"] for it in items})
    fold_of = {g: i % folds for i, g in enumerate(groups)}
    stats = {lvl: {"top1": 0, "top3": 0} for lvl in (2, 5)}
    n = 0
    for f in range(folds):
        train = [it for it in items if fold_of[it["notice"]] != f]
        test = [it for it in items if fold_of[it["notice"]] == f]
        m = OkpdModel(train)
        for it in test:
            n += 1
            for lvl in (2, 5):
                pred = [p["code"] for p in m.predict(it["name"], level=lvl)]
                gold = it["code"][:lvl]
                stats[lvl]["top1"] += bool(pred) and pred[0] == gold
                stats[lvl]["top3"] += gold in pred[:3]
    return {"items": len(items), "notices": len(groups), "folds": folds,
            "section_2_digits": {k: round(v / n, 3) for k, v in stats[2].items()},
            "class_5_chars": {k: round(v / n, 3) for k, v in stats[5].items()}}


def main() -> int:
    r = cross_validate()
    (TRAIN.parent.parent.parent / "eval" / "okpd_report.json").write_text(json.dumps(r, ensure_ascii=False, indent=2),
                                                                         encoding="utf-8")
    print(f"ОКПД 2 по тексту: {r['items']} позиций из {r['notices']} извещений, {r['folds']}-кратная проверка по извещениям. "
          f"Раздел (2 цифры): top-1 {r['section_2_digits']['top1']:.0%}, top-3 {r['section_2_digits']['top3']:.0%}; "
          f"класс (26.20): top-1 {r['class_5_chars']['top1']:.0%}, top-3 {r['class_5_chars']['top3']:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
