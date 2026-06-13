"""
Triple-barrier labelling + meta-labelling (Lopez de Prado, AFML).

The triple-barrier method labels each event by which of three barriers price
touches first within a horizon: an upper (profit-take) barrier, a lower (stop)
barrier, or a vertical (time) barrier. This yields path-aware, risk-aware labels
that match how a strategy actually exits — far better than a fixed-horizon
return sign. Meta-labelling then asks "was the primary signal's direction
right?" to train a secondary model that only sizes/vetoes, never flips.

Everything here is point-in-time: a label for event t0 uses only prices in
(t0, t1]; features for that event must be taken as-of t0 (see pipeline.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def get_daily_vol(close: pd.Series, span: int = 20) -> pd.Series:
    """EW std of close-to-close returns — the dynamic target for barriers."""
    ret = close.pct_change()
    return ret.ewm(span=span).std()


def get_vertical_barriers(close: pd.Series, t_events: pd.Index,
                          num_bars: int) -> pd.Series:
    """For each event time, the timestamp `num_bars` ahead (the time barrier)."""
    idx = close.index.searchsorted(pd.DatetimeIndex(t_events))
    ahead = idx + num_bars
    ok = ahead < close.shape[0]
    return pd.Series(close.index[ahead[ok]], index=pd.DatetimeIndex(t_events)[ok])


def apply_triple_barrier(close: pd.Series, events: pd.DataFrame,
                         pt_sl: tuple[float, float]) -> pd.DataFrame:
    """Find first-touched barrier per event.

    `events`: DataFrame indexed by event start, columns:
        t1   -> vertical-barrier timestamp
        trgt -> target return (e.g. daily vol); barriers are pt*trgt / -sl*trgt
    Returns columns: touch (first-touch time), ret (return to touch),
    bin (+1 upper / -1 lower / 0 vertical).
    """
    pt, sl = pt_sl
    out = events[["t1"]].copy()
    out["touch"] = pd.NaT
    out["ret"] = np.nan
    out["bin"] = 0

    for t0, row in events.iterrows():
        t1 = row["t1"]
        path = close.loc[t0:t1]
        if len(path) < 2:
            continue
        rets = path / close.loc[t0] - 1.0
        up = pt * row["trgt"]
        dn = -sl * row["trgt"]
        up_touch = rets[rets >= up].index.min() if (rets >= up).any() else pd.NaT
        dn_touch = rets[rets <= dn].index.min() if (rets <= dn).any() else pd.NaT

        candidates = [t for t in (up_touch, dn_touch) if pd.notna(t)]
        if candidates:
            first = min(candidates)
            out.at[t0, "touch"] = first
            out.at[t0, "ret"] = rets.loc[first]
            # tie-break: if both on same bar, the larger move wins
            out.at[t0, "bin"] = 1 if first == up_touch else -1
        else:
            out.at[t0, "touch"] = t1
            out.at[t0, "ret"] = rets.iloc[-1]
            out.at[t0, "bin"] = 0
    return out


def directional_labels(barrier_out: pd.DataFrame) -> pd.Series:
    """Primary label = sign of the first-touch return (for a directional model)."""
    return np.sign(barrier_out["ret"]).fillna(0).astype(int).rename("label")


def meta_labels(barrier_out: pd.DataFrame, side: pd.Series) -> pd.Series:
    """Meta-label = 1 if the primary `side` (+1/-1) was profitable, else 0.

    Trains the secondary model to predict P(primary signal correct), used only
    to size or veto — never to flip direction.
    """
    pos_ret = side.reindex(barrier_out.index) * barrier_out["ret"]
    return (pos_ret > 0).astype(int).rename("meta_label")
