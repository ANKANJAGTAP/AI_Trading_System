"""Transparent meta-labeler: logistic regression in numpy (no sklearn).

Train on (feature -> win) pairs; the learned coefficients are inspectable feature
importances. `MetaLabeler.assess` turns a signal's gate scores + confidence into a
multiplier in [0.5, 1.0] (it can only REDUCE confidence — filter, never inflate).
"""
from __future__ import annotations

import numpy as np


def train(X, y, lr: float = 0.3, epochs: int = 800, l2: float = 1e-3,
          sample_weight=None, class_weight: bool = False) -> dict:
    """Fit logistic regression with standardized features + L2. Returns the params
    (weights, bias, and the standardization mean/std so predict matches training).

    `sample_weight` lets recent trades matter more (markets drift — exponential
    recency decay); `class_weight=True` balances win/loss frequencies so a lopsided
    sample can't be solved by always predicting the majority class."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    n, d = X.shape
    sw = np.ones(n) if sample_weight is None else np.asarray(sample_weight, dtype=float)
    if class_weight:
        pos = max(1.0, float(y.sum()))
        neg = max(1.0, float(n - y.sum()))
        sw = sw * np.where(y == 1, n / (2.0 * pos), n / (2.0 * neg))
    sw = sw / max(1e-12, float(sw.mean()))
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    xs = (X - mu) / sd
    w = np.zeros(d)
    b = 0.0
    for _ in range(epochs):
        z = np.clip(xs @ w + b, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        err = (p - y) * sw
        w -= lr * (xs.T @ err / n + l2 * w)
        b -= lr * float(err.mean())
    return {"w": w.tolist(), "b": float(b), "mu": mu.tolist(), "sd": sd.tolist()}


def predict_proba(params: dict, x) -> float:
    w = np.asarray(params["w"], dtype=float)
    mu = np.asarray(params["mu"], dtype=float)
    sd = np.asarray(params["sd"], dtype=float)
    xs = (np.asarray(x, dtype=float) - mu) / sd
    z = float(xs @ w) + float(params["b"])
    return float(1.0 / (1.0 + np.exp(-max(-30.0, min(30.0, z)))))


def evaluate(params: dict, X, y) -> dict:
    """Accuracy + class-1 precision/recall + lift over base rate. Precision on
    predicted winners is the number that matters for a trade FILTER: of the trades
    the model would let through, how many actually won."""
    y = list(y)
    if not y:
        return {"accuracy": 0.0, "base_rate": 0.0, "n_samples": 0,
                "precision_1": 0.0, "recall_1": 0.0, "lift": 0.0}
    preds = [1 if predict_proba(params, row) >= 0.5 else 0 for row in X]
    acc = sum(int(pr == int(t)) for pr, t in zip(preds, y)) / len(y)
    base = sum(int(t) for t in y) / len(y)
    tp = sum(1 for pr, t in zip(preds, y) if pr == 1 and int(t) == 1)
    fp = sum(1 for pr, t in zip(preds, y) if pr == 1 and int(t) == 0)
    fn = sum(1 for pr, t in zip(preds, y) if pr == 0 and int(t) == 1)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {"accuracy": round(acc, 3), "base_rate": round(base, 3), "n_samples": len(y),
            "precision_1": round(precision, 3), "recall_1": round(recall, 3),
            "lift": round(precision - base, 3)}


def feature_importance(params: dict, features: list[str]) -> list[dict]:
    return sorted(
        ({"feature": f, "weight": round(float(wt), 3)} for f, wt in zip(features, params["w"])),
        key=lambda r: abs(r["weight"]), reverse=True)


class MetaLabeler:
    """Holds a trained model and scores live signals from a feature dict.

    `assess` implements FILTER-with-dead-band semantics (the research consensus:
    when predicted probabilities cluster mid-range, a meta-model is a trade filter,
    not a size dial):
      p <  veto_below    -> 0.0  (hard veto: confidence -> 0, trade skipped)
      p in dead band     -> linear soft_floor..1.0 (mild shrink, no strong opinion)
      p >= neutral_above -> 1.0  (no change — it can NEVER inflate confidence)
    Thresholds ship inside the model params (set from config at training time)."""

    def __init__(self, features: list[str], params: dict) -> None:
        self.features = features
        self.params = params
        dep = (params.get("deploy") or {}) if isinstance(params, dict) else {}
        self.veto_below = float(dep.get("veto_below", 0.40))
        self.neutral_above = float(dep.get("neutral_above", 0.55))
        self.soft_floor = float(dep.get("soft_floor", 0.6))

    def win_probability(self, features: dict) -> float:
        x = [float((features or {}).get(f, 0.0)) for f in self.features]
        return predict_proba(self.params, x)

    def assess(self, features: dict) -> float:
        p = self.win_probability(features)
        if p < self.veto_below:
            return 0.0
        if p >= self.neutral_above or self.neutral_above <= self.veto_below:
            return 1.0
        frac = (p - self.veto_below) / (self.neutral_above - self.veto_below)
        return round(self.soft_floor + (1.0 - self.soft_floor) * frac, 4)
