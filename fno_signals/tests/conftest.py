import pandas as pd
import pytest

from features.options import bs_price
from fno_signals.context import MarketContext


def make_chain(spot=22000.0, step=50.0, n=12, t=7 / 365, iv=0.18,
               oi=20_000, vol=5_000):
    atm = round(spot / step) * step
    rows = []
    for k in range(-n, n + 1):
        K = atm + k * step
        for opt in ("CE", "PE"):
            rows.append({
                "opt_type": opt, "strike": float(K),
                "close": round(bs_price(spot, K, t, 0.065, iv, opt), 2),
                "oi": oi, "volume": vol,
            })
    return pd.DataFrame(rows)


def _ctx(features, iv_rank, oi=20_000, vol=5_000):
    spot = 22000.0
    return MarketContext(
        underlying="NIFTY", timestamp=pd.Timestamp("2026-06-08"), spot=spot,
        features=features, iv_rank=iv_rank, atm_iv=0.18,
        chain=make_chain(spot, oi=oi, vol=vol),
        dte=7, expiry=pd.Timestamp("2026-06-09"), lot_size=65, step=50.0,
    )


@pytest.fixture
def ctx_bull_lowiv():
    return _ctx({"dma_dist_200": 3.0, "macd_hist": 5.0, "adx_14": 30.0,
                 "rsi_14": 58.0, "supertrend_dir": 1.0}, iv_rank=20.0)


@pytest.fixture
def ctx_neutral_highiv():
    return _ctx({"dma_dist_200": 0.1, "macd_hist": 0.0, "adx_14": 12.0,
                 "rsi_14": 50.0, "supertrend_dir": 0.0}, iv_rank=75.0)


@pytest.fixture
def ctx_illiquid():
    return _ctx({"dma_dist_200": 3.0, "macd_hist": 5.0, "adx_14": 30.0,
                 "rsi_14": 58.0, "supertrend_dir": 1.0}, iv_rank=20.0,
                oi=100, vol=10)
