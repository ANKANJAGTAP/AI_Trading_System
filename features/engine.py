"""
Feature engine — turn raw EOD F&O data into a point-in-time feature matrix.

It bridges the data platform (Pillar 1) and the feature library:
  * builds a daily OHLCV series for an underlying from its front-month future,
  * computes the registered TA features over that series,
  * computes option-chain features (PCR/max-pain/GEX/ATM-IV/skew) per date from
    the front-expiry chain,
  * joins them into one matrix indexed by trade_date.

Train/serve parity: `compute` (batch, research) and `compute_at` (one timestamp,
live) call the SAME feature functions; the value at T depends only on rows <= T.
"""
from __future__ import annotations

import pandas as pd

from . import indicators  # noqa: F401  (populates the registry)
from .base import REGISTRY, list_features
from .options import chain_features


class FeatureEngine:
    def __init__(self, feature_ids: list[str] | None = None):
        self.feature_ids = feature_ids or list_features()

    # -- TA features over an OHLCV frame --------------------------------- #
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Batch: full feature matrix aligned to df.index."""
        cols = {fid: REGISTRY[fid].compute(df) for fid in self.feature_ids
                if REGISTRY[fid].category != "options"}
        return pd.DataFrame(cols, index=df.index)

    def compute_at(self, df: pd.DataFrame, ts) -> pd.Series:
        """Live: feature vector as-of `ts` (uses only rows <= ts)."""
        hist = df.loc[:ts]
        return self.compute(hist).iloc[-1]


# --------------------------------------------------------------------------- #
# building inputs from canonical EOD F&O data
# --------------------------------------------------------------------------- #
def underlying_daily_from_eod(eod: pd.DataFrame, underlying: str) -> pd.DataFrame:
    """Daily OHLCV for an underlying built from its FRONT-month future."""
    fut = eod[(eod["underlying"] == underlying) & (eod["instrument"] == "FUT")].copy()
    if fut.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "oi"])
    fut["trade_date"] = pd.to_datetime(fut["trade_date"])
    fut["expiry"] = pd.to_datetime(fut["expiry"])
    fut = fut[fut["expiry"] >= fut["trade_date"]]
    front_idx = fut.groupby("trade_date")["expiry"].idxmin()
    front = fut.loc[front_idx].sort_values("trade_date").set_index("trade_date")
    return front[["open", "high", "low", "close", "volume", "oi"]]


def option_features_timeseries(eod: pd.DataFrame, underlying: str,
                               r: float = 0.065) -> pd.DataFrame:
    """Per-date option-chain features from the front-expiry chain."""
    opt = eod[(eod["underlying"] == underlying) & (eod["instrument"] == "OPT")].copy()
    if opt.empty:
        return pd.DataFrame()
    opt["trade_date"] = pd.to_datetime(opt["trade_date"])
    opt["expiry"] = pd.to_datetime(opt["expiry"])
    daily = underlying_daily_from_eod(eod, underlying)

    rows = []
    for date, chain_all in opt.groupby("trade_date"):
        future = chain_all[chain_all["expiry"] >= date]
        if future.empty:
            continue
        front_exp = future["expiry"].min()
        chain = chain_all[chain_all["expiry"] == front_exp]
        spot = float(daily.loc[date, "close"]) if date in daily.index \
            else float(chain["strike"].median())
        t = max((front_exp - date).days, 1) / 365.0
        feats = chain_features(chain, spot, t, r)
        feats["trade_date"] = date
        rows.append(feats)
    return pd.DataFrame(rows).set_index("trade_date").sort_index() if rows else pd.DataFrame()


def build_feature_matrix(eod: pd.DataFrame, underlying: str,
                         feature_ids: list[str] | None = None,
                         r: float = 0.065) -> pd.DataFrame:
    """Full point-in-time feature matrix (TA + options) for one underlying."""
    daily = underlying_daily_from_eod(eod, underlying)
    ta = FeatureEngine(feature_ids).compute(daily)
    opt = option_features_timeseries(eod, underlying, r)
    return ta.join(opt, how="left") if not opt.empty else ta
