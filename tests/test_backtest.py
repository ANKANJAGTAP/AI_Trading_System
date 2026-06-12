"""Backtest metrics + sim-broker fills (pure, no DB)."""
from backtest.metrics import compute_metrics
from backtest.sim_broker import BacktestBroker
from execution.costs import CostModel


def test_metrics_basic():
    trades = [
        {"ts": "t1", "pnl": 200.0, "r_multiple": 2.0},
        {"ts": "t2", "pnl": -100.0, "r_multiple": -1.0},
        {"ts": "t3", "pnl": 300.0, "r_multiple": 1.5},
    ]
    m = compute_metrics(trades, 100_000)
    assert m["trades"] == 3
    assert m["net_pnl"] == 400.0
    assert round(m["win_rate"], 1) == 66.7
    assert m["profit_factor"] == round(500 / 100, 2)
    assert m["largest_win"] == 300.0
    assert m["largest_loss"] == -100.0
    assert len(m["equity_curve"]) == 3 and m["equity_curve"][-1]["value"] == 400.0


def test_metrics_empty():
    m = compute_metrics([], 100_000)
    assert m["trades"] == 0 and m["net_pnl"] == 0.0 and m["equity_curve"] == []


def test_sim_broker_slippage_direction():
    b = BacktestBroker(CostModel({}), slippage_bps=10)  # 0.10%
    # BUY entry pays up; its exit (a SELL) fills down
    assert b.entry_fill("BUY", 100.0) > 100.0
    assert b.exit_fill("BUY", 100.0) < 100.0
    # SELL entry fills down; its exit (a BUY) fills up
    assert b.entry_fill("SELL", 100.0) < 100.0
    assert b.exit_fill("SELL", 100.0) > 100.0


def test_sim_broker_fees_nonnegative():
    b = BacktestBroker(CostModel({}), slippage_bps=2)
    assert b.fees("equity_intraday", "BUY", 100, 100.0) >= 0.0
