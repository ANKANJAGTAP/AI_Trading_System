import numpy as np
import pandas as pd

from fno_backtest.costs import CostConfig
from fno_backtest.engine import simulate_trade, EventDrivenBacktester, backtest_strategy
from fno_backtest.instruments import bull_call_spread

_ZERO_BROK = CostConfig(brokerage_per_order=0.0)


def test_simulate_trade_profit_and_net():
    s = bull_call_spread(100, 110, 50, 5, 2)
    r = simulate_trade(s, settle_spot=120, cfg=_ZERO_BROK)
    assert abs(r["gross"] - 350) < 1e-6
    assert r["costs"] > 0
    assert abs(r["net"] - (r["gross"] - r["costs"])) < 1e-9


def test_simulate_trade_worthless_legs_lapse():
    s = bull_call_spread(100, 110, 50, 5, 2)
    r = simulate_trade(s, settle_spot=90, cfg=_ZERO_BROK)
    assert abs(r["gross"] + 150) < 1e-6        # gross at/below lower strike
    assert r["exit_cost"] == 0.0               # both legs expire worthless -> no exit cost


def test_event_driven_run_and_report():
    s = bull_call_spread(100, 110, 50, 5, 2)
    sigs = [{
        "entry_date": pd.Timestamp("2026-01-05"),
        "exit_date": pd.Timestamp("2026-01-12"),
        "structure": s, "settle_spot": 120,
    }]
    res = EventDrivenBacktester(100_000, _ZERO_BROK).run(sigs)
    assert len(res.trades) == 1
    rep = res.report()
    assert rep["n_trades"] == 1
    assert "bias_audit" in rep and rep["bias_audit"]["costs_modelled"] is True
    assert np.isfinite(rep["net_pnl"])


def test_backtest_strategy_integration(eod):
    def strat(date, chain, spot):
        if date.weekday() != 0:                # only enter on Mondays
            return None
        ce = chain[chain["opt_type"] == "CE"]
        if ce.empty:
            return None
        strikes = sorted(ce["strike"].unique())
        atm = min(strikes, key=lambda k: abs(k - spot))
        higher = [k for k in strikes if k > atm]
        if not higher:
            return None
        k2 = higher[0]
        p1 = float(ce[ce["strike"] == atm]["close"].iloc[0])
        p2 = float(ce[ce["strike"] == k2]["close"].iloc[0])
        return bull_call_spread(atm, k2, 75, p1, p2)

    res = backtest_strategy(eod, "NIFTY", strat, starting_capital=500_000)
    assert len(res.trades) >= 1
    rep = res.report()
    assert rep["n_trades"] == len(res.trades)
    assert np.isfinite(rep["net_pnl"])
    assert np.isfinite(rep["max_drawdown_pct"])
