"""
Meta-model — a self-contained standardising logistic regression (no sklearn),
matching the repo's documented meta-labeler math, plus the deployment rule that
turns P(win) into a size multiplier that can only veto or shrink, never inflate.
"""
from __future__ import annotations

import numpy as np


class LogisticMetaModel:
    """Standardising logistic regression trained by gradient descent with L2.

    Deliberately interpretable and dependency-free: the baseline every fancier
    model must beat out-of-sample (per the plan's Pillar 3).
    """

    def __init__(self, lr: float = 0.1, n_iter: int = 1000, l2: float = 1e-3,
                 class_weight: bool = False):
        self.lr, self.n_iter, self.l2 = lr, n_iter, l2
        self.class_weight = class_weight

    def fit(self, X, y, sample_weight=None):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ == 0] = 1.0
        Xs = (X - self.mean_) / self.std_
        n, d = Xs.shape

        sw = np.ones(n) if sample_weight is None else np.asarray(sample_weight, float)
        if self.class_weight:
            pos = max(y.sum(), 1.0)
            neg = max(n - y.sum(), 1.0)
            sw = sw * np.where(y == 1, n / (2 * pos), n / (2 * neg))
        sw = sw / sw.mean()

        w = np.zeros(d)
        b = 0.0
        for _ in range(self.n_iter):
            z = np.clip(Xs @ w + b, -30, 30)
            p = 1.0 / (1.0 + np.exp(-z))
            err = (p - y) * sw
            w -= self.lr * (Xs.T @ err / n + self.l2 * w)
            b -= self.lr * err.mean()
        self.w_, self.b_ = w, b
        return self

    def predict_proba(self, X):
        Xs = (np.asarray(X, float) - self.mean_) / self.std_
        z = np.clip(Xs @ self.w_ + self.b_, -30, 30)
        return 1.0 / (1.0 + np.exp(-z))

    def predict(self, X):
        return (self.predict_proba(X) >= 0.5).astype(int)


def size_multiplier(p_win, veto_below: float = 0.4, neutral_above: float = 0.6,
                    soft_floor: float = 0.0):
    """Map P(win) -> position-size multiplier in [0,1].

    Below `veto_below` -> 0 (veto). At/above `neutral_above` -> 1 (full size).
    In between -> linear ramp from `soft_floor` to 1. NEVER exceeds 1: the
    meta-model can only shrink or veto risk, never add it.
    """
    p = np.asarray(p_win, dtype=float)
    ramp = soft_floor + (1 - soft_floor) * (p - veto_below) / (neutral_above - veto_below)
    out = np.where(p < veto_below, 0.0, np.where(p >= neutral_above, 1.0, ramp))
    return float(out) if np.ndim(p_win) == 0 else out
