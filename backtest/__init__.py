"""Backtesting / research layer (Phase 1).

Replays historical candles through the SAME gate pipelines, confidence model, cost
model, and R-sizing used live (via the pure `*_from_frames` context builders), so
backtest decisions are identical to live by construction. Phase 1 supports the
intraday-equity sleeve; swing/F&O are documented extensions.
"""
from backtest.engine import BacktestParams, run_backtest

__all__ = ["BacktestParams", "run_backtest"]
