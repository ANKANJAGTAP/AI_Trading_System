"""Confluence-breakout pure helpers (signals / backtest / OOS split) — no DB."""
import datetime as dt
import importlib.util
import os

import numpy as np
import pandas as pd

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "confluence_breakout.py")
_spec = importlib.util.spec_from_file_location("confluence_breakout", _PATH)
cb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cb)


def _uptrend(n: int = 200, start: float = 100.0, step: float = 0.3) -> pd.DataFrame:
    ts = pd.date_range("2025-07-01 03:45:00+00:00", periods=n, freq="5min")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {"open": close - step * 0.5, "high": close + 0.2, "low": close - 0.2,
         "close": close, "volume": np.linspace(1000, 5000, n).astype(int), "oi": 0},
        index=ts)


def test_compute_signals_range_and_columns():
    s = cb.compute_signals(_uptrend())
    for col in ("confluence", "atr", "vwap", "bars_left"):
        assert col in s.columns
    assert s["confluence"].min() >= 0 and s["confluence"].max() <= cb.N_SIGNALS
    assert s["confluence"].iloc[60:-6].max() >= 4          # a clean uptrend lights up many signals


def test_backtest_uptrend_wins_and_threshold_caps_trades():
    s = cb.compute_signals(_uptrend())
    trades = cb.backtest_symbol(s, k=3, atr_mult=1.5, reward_r=2.0, cost_bps=10, capital=100000)
    assert len(trades) >= 1
    assert sum(t["pnl"] for t in trades) > 0               # longs in an uptrend, net of costs
    # an impossible threshold (> N signals) can never confirm -> no trades
    assert cb.backtest_symbol(s, k=cb.N_SIGNALS + 1, atr_mult=1.5, reward_r=2.0,
                              cost_bps=10, capital=100000) == []


def test_split_net_buckets_by_date():
    trades = [{"ts": "2025-07-01 09:30:00", "pnl": 100.0},
              {"ts": "2025-09-01 10:00:00", "pnl": -40.0}]
    assert cb.split_net(trades, dt.date(2025, 8, 1)) == (100.0, -40.0)
