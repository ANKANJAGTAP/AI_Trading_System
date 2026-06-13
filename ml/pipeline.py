"""
End-to-end research pipeline: price + features -> events -> triple-barrier labels
-> point-in-time dataset -> CPCV-evaluated model.

This is the spine that the world-class plan's Pillar 3 describes: nothing gets
promoted on a single in-sample curve; everything is judged on the DISTRIBUTION
of out-of-sample scores from combinatorial purged CV.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .labeling import get_daily_vol, get_vertical_barriers, apply_triple_barrier
from .cv import combinatorial_purged_cv, num_cpcv_paths
from .models import LogisticMetaModel


def make_events(close: pd.Series, vol_span: int = 20, vertical_bars: int = 10,
                t_events: pd.Index | None = None) -> pd.DataFrame:
    vol = get_daily_vol(close, vol_span)
    t_events = close.index if t_events is None else t_events
    t1 = get_vertical_barriers(close, t_events, vertical_bars)
    ev = pd.DataFrame({"t1": t1})
    ev["trgt"] = vol.reindex(ev.index)
    ev = ev.dropna()
    return ev[ev["trgt"] > 0]


def label_events(close: pd.Series, events: pd.DataFrame,
                 pt_sl: tuple[float, float] = (1.5, 1.5)) -> pd.DataFrame:
    out = apply_triple_barrier(close, events, pt_sl)
    return out.dropna(subset=["ret"])


def build_dataset(feature_matrix: pd.DataFrame, barrier_out: pd.DataFrame):
    """Align features (as-of event start = point-in-time) with binary labels."""
    common = feature_matrix.index.intersection(barrier_out.index)
    X = feature_matrix.loc[common].dropna(how="any").sort_index()  # chronological
    idx = X.index
    y = (barrier_out.loc[idx, "ret"] > 0).astype(int)
    t1 = barrier_out.loc[idx, "touch"]
    return X, y, t1


def evaluate_cpcv(X: pd.DataFrame, y: pd.Series, t1: pd.Series,
                  model_factory=LogisticMetaModel,
                  n_groups: int = 6, n_test_groups: int = 2,
                  embargo_pct: float = 0.01) -> dict:
    """Run combinatorial purged CV; return the OOS accuracy distribution."""
    t1s = pd.Series(pd.to_datetime(t1.values), index=X.index)
    yv = y.to_numpy()
    scores = []
    for train, test in combinatorial_purged_cv(X, t1s, n_groups, n_test_groups, embargo_pct):
        if len(train) < 10 or len(test) == 0 or len(np.unique(yv[train])) < 2:
            continue
        m = model_factory().fit(X.iloc[train].to_numpy(), yv[train])
        pred = m.predict(X.iloc[test].to_numpy())
        scores.append(float((pred == yv[test]).mean()))
    scores = np.array(scores)
    return {
        "scores": scores,
        "mean": float(scores.mean()) if scores.size else float("nan"),
        "std": float(scores.std()) if scores.size else float("nan"),
        "pct_above_half": float((scores > 0.5).mean()) if scores.size else float("nan"),
        "n_splits_used": int(scores.size),
        "n_paths": num_cpcv_paths(n_groups, n_test_groups),
    }
