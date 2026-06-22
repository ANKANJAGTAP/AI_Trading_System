"""§10 Phase 3/5 — scenario / stress VaR (full BS repricing)."""
from risk.scenario_var import (position_pnl, scenario_pnl, stress_grid,
                               stress_var)

_LONG_CE = {"S": 100, "K": 100, "t": 0.05, "iv": 0.20, "opt": "CE", "qty": 1, "lot_size": 50}
_SHORT_CE = {**_LONG_CE, "qty": -1}
_SHORT_PE = {**_LONG_CE, "opt": "PE", "qty": -1}


def test_long_call_directional_pnl():
    assert position_pnl(_LONG_CE, 0.05, 0) > 0      # spot up -> long call gains
    assert position_pnl(_LONG_CE, -0.05, 0) < 0     # spot down -> loses
    assert position_pnl(_LONG_CE, 0, 3) > 0         # vol up -> +vega
    assert position_pnl(_LONG_CE, 0, -3) < 0


def test_no_move_is_flat():
    assert scenario_pnl([_LONG_CE], 0.0, 0.0) == 0.0


def test_stress_var_is_worst_case_loss():
    out = stress_var([_LONG_CE])
    assert out["grid_points"] == 15                 # 5 spot x 3 vol
    assert out["stress_var"] < 0                     # a long call can lose
    # worst case for a long call = biggest spot drop + vol drop
    assert out["worst_scenario"] == (-0.06, -3.0)


def test_short_straddle_loses_on_big_move_both_ways():
    book = [_SHORT_CE, _SHORT_PE]
    assert scenario_pnl(book, 0.0, 0.0) == 0.0       # flat at no move
    up = scenario_pnl(book, 0.06, 0.0)
    down = scenario_pnl(book, -0.06, 0.0)
    assert up < 0 and down < 0                        # short gamma: loses either way
    assert stress_var(book)["stress_var"] < 0


def test_grid_shape():
    grid = stress_grid([_LONG_CE], spot_shocks=(-0.02, 0, 0.02), vol_shocks=(0,))
    assert len(grid) == 3 and (0.0, 0.0) in grid
