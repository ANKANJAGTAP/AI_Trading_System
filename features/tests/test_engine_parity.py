"""End-to-end: build a feature matrix from synthetic EOD data and prove
train/serve parity + no look-ahead."""
import numpy as np
import pandas as pd
import pytest

from dataplatform.vendors import SyntheticEODAdapter
from features import FeatureEngine, build_feature_matrix, underlying_daily_from_eod
from features.base import REGISTRY


@pytest.fixture(scope="module")
def eod():
    ad = SyntheticEODAdapter()
    days = pd.bdate_range("2026-03-02", "2026-06-05")
    frames = [ad.fetch_eod_fno(d.date()) for d in days]
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def matrix(eod):
    return build_feature_matrix(eod, "NIFTY")


def test_matrix_has_ta_and_option_columns(matrix):
    assert not matrix.empty
    for c in ["ema_20", "rsi_14", "atr_14", "macd_hist", "rvol_20"]:
        assert c in matrix.columns
    for c in ["pcr_oi", "atm_iv", "net_gex", "max_pain", "skew"]:
        assert c in matrix.columns
    assert np.isfinite(matrix["ema_20"].iloc[-1])
    assert matrix["atm_iv"].notna().any()


def test_train_serve_parity(eod):
    daily = underlying_daily_from_eod(eod, "NIFTY")
    eng = FeatureEngine(["ema_20", "rsi_14", "atr_14"])
    batch = eng.compute(daily)
    ts = daily.index[-1]
    live = eng.compute_at(daily, ts)        # uses only rows <= ts
    for c in ["ema_20", "rsi_14", "atr_14"]:
        a, b = batch.loc[ts, c], live[c]
        if not (np.isnan(a) and np.isnan(b)):
            assert abs(a - b) < 1e-9, f"train/serve mismatch in {c}"


def test_no_lookahead_in_matrix(eod):
    daily = underlying_daily_from_eod(eod, "NIFTY")
    eng = FeatureEngine(["ema_20", "rsi_14"])
    k = 40
    full = eng.compute(daily)
    trunc = eng.compute(daily.iloc[:k])
    for c in ["ema_20", "rsi_14"]:
        a, b = full[c].iloc[k - 1], trunc[c].iloc[k - 1]
        if not (np.isnan(a) and np.isnan(b)):
            assert abs(a - b) < 1e-9, f"look-ahead leak in {c}"


def test_registry_populated():
    # framework wired: a healthy catalog across categories
    assert len(REGISTRY) >= 20
    cats = {REGISTRY[f].category for f in REGISTRY}
    assert {"trend", "momentum", "volatility", "volume"}.issubset(cats)
