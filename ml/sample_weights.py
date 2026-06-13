"""
Sample weighting (AFML ch. 4).

Overlapping labels (concurrent open positions) violate the IID assumption that
most ML estimators rely on. We down-weight observations that overlap many others
(low uniqueness) and optionally apply time-decay so recent regimes count more.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def num_concurrent_events(bar_index: pd.Index, t1: pd.Series) -> pd.Series:
    """Number of labels open over each bar in `bar_index`."""
    t1 = t1.dropna()
    count = pd.Series(0.0, index=bar_index)
    for t_in, t_out in t1.items():
        count.loc[t_in:t_out] += 1.0
    return count


def average_uniqueness(t1: pd.Series, num_co_events: pd.Series) -> pd.Series:
    """Average uniqueness of each label = mean(1 / concurrency) over its life."""
    out = pd.Series(index=t1.index, dtype=float)
    for t_in, t_out in t1.items():
        co = num_co_events.loc[t_in:t_out]
        out.loc[t_in] = (1.0 / co.replace(0, np.nan)).mean()
    return out


def time_decay_weights(av_uniqueness: pd.Series, last_weight: float = 1.0) -> pd.Series:
    """Linear time decay (AFML 4.11).

    last_weight in [0,1]: weight of the OLDEST observation (1.0 = no decay).
    Negative values let older observations decay to zero before the start.
    """
    clf = av_uniqueness.sort_index().cumsum()
    if clf.iloc[-1] == 0:
        return pd.Series(1.0, index=av_uniqueness.index)
    if last_weight >= 0:
        slope = (1.0 - last_weight) / clf.iloc[-1]
    else:
        slope = 1.0 / ((last_weight + 1) * clf.iloc[-1])
    const = 1.0 - slope * clf.iloc[-1]
    w = const + slope * clf
    w[w < 0] = 0.0
    return w.reindex(av_uniqueness.index)


def combined_weights(t1: pd.Series, bar_index: pd.Index,
                     last_weight: float = 1.0) -> pd.Series:
    """Convenience: uniqueness * time-decay, normalised to mean 1."""
    co = num_concurrent_events(bar_index, t1)
    au = average_uniqueness(t1, co)
    w = au * time_decay_weights(au, last_weight)
    return (w / w.mean()).rename("weight")
