"""§10 Phase 6 — Structure Lab payoff + analytics."""
from api.structure_lab import analyze, expiry_payoff, payoff_curve


def test_long_call_expiry_payoff():
    leg = [{"opt": "CE", "K": 100, "qty": 1, "entry_px": 10}]
    assert expiry_payoff(leg, 100) == -10     # OTM at expiry -> lose the premium
    assert expiry_payoff(leg, 120) == 10      # 20 intrinsic - 10 premium


def test_short_call_and_put_payoff():
    assert expiry_payoff([{"opt": "CE", "K": 100, "qty": -1, "entry_px": 10}], 100) == 10
    assert expiry_payoff([{"opt": "PE", "K": 100, "qty": 1, "entry_px": 8}], 80) == 12


def test_payoff_curve_shape():
    c = payoff_curve([{"opt": "CE", "K": 100, "qty": 1, "entry_px": 5}], 100, points=41)
    assert len(c) == 41 and c[0]["spot"] < 100 < c[-1]["spot"]


def test_bull_call_spread_is_capped_debit():
    out = analyze(spot=100, iv=0.2, dte=30, lot_size=50, legs=[
        {"opt": "CE", "strike": 100, "side": "BUY", "lots": 1},
        {"opt": "CE", "strike": 105, "side": "SELL", "lots": 1},
    ])
    assert out["max_profit"] > 0 and out["max_loss"] < 0       # capped gain, defined loss
    assert out["max_profit"] <= 5 * 50 + 1                      # bounded by width*lot
    assert out["net_greeks"]["delta"] > 0                      # net long calls
    assert len(out["breakevens"]) >= 1


def test_short_straddle_profile():
    out = analyze(spot=100, iv=0.2, dte=30, lot_size=50, legs=[
        {"opt": "CE", "strike": 100, "side": "SELL", "lots": 1},
        {"opt": "PE", "strike": 100, "side": "SELL", "lots": 1},
    ])
    assert out["max_profit"] > 0 and out["max_loss"] < 0
    assert out["net_greeks"]["vega"] < 0                       # short vol
    assert len(out["breakevens"]) == 2                         # one each side
