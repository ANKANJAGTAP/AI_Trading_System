import numpy as np

from features.options import bs_price
from fno_backtest.analysis import monte_carlo_paths, scenario_grid
from fno_backtest.instruments import Leg, Structure


def test_montecarlo_all_positive():
    res = monte_carlo_paths([10, 20, 30, 5], n_paths=500)
    assert res["prob_profit"] == 1.0
    assert res["terminal_p05"] > 0


def test_montecarlo_mixed_bounds():
    res = monte_carlo_paths([100, -50, 30, -80, 60], n_paths=500)
    assert 0.0 <= res["prob_profit"] <= 1.0
    assert res["maxdd_worst_p05"] <= 0.0


def test_scenario_long_call_directional_and_vega():
    spot, t, iv = 100.0, 7 / 365, 0.20
    entry = bs_price(spot, 100, t, 0.065, iv, "CE")
    s = Structure("long_call", [Leg("CE", 100, "BUY", 50, entry)])
    g = scenario_grid(s, spot, t, iv=iv, spot_shocks=[-0.05, 0.0, 0.05],
                      iv_shocks=[0.0, 0.05])
    # higher spot -> long call gains (same IV column)
    assert g.iloc[-1, 0] > g.iloc[0, 0]
    # higher IV -> long call gains (positive vega), at the ATM row
    assert g.iloc[1, 1] > g.iloc[1, 0]
