"""§10 Phase 3 — Greeks P&L attribution."""
from backtest.greeks_pnl import attribute_pnl


def test_pure_delta():
    out = attribute_pnl({"delta": 1.0, "gamma": 0, "vega": 0, "theta": 0}, dS=10, dVol_pts=0, dDays=0)
    assert out["delta"] == 10.0 and out["explained"] == 10.0


def test_gamma_is_second_order_positive():
    out = attribute_pnl({"delta": 0, "gamma": 0.1, "vega": 0, "theta": 0}, dS=10, dVol_pts=0, dDays=0)
    assert out["gamma"] == round(0.5 * 0.1 * 100, 4)     # 0.5*gamma*dS^2 = 5


def test_theta_decay_and_vega():
    out = attribute_pnl({"delta": 0, "gamma": 0, "vega": 2.0, "theta": -0.5}, dS=0, dVol_pts=3, dDays=1)
    assert out["vega"] == 6.0 and out["theta"] == -0.5


def test_residual_and_mult():
    g = {"delta": 1.0, "gamma": 0, "vega": 0, "theta": 0}
    out = attribute_pnl(g, dS=10, dVol_pts=0, dDays=0, actual_pnl=12.0, mult=1.0)
    assert out["explained"] == 10.0 and out["residual"] == 2.0 and out["actual"] == 12.0
    scaled = attribute_pnl(g, dS=10, dVol_pts=0, dDays=0, mult=50)
    assert scaled["delta"] == 500.0 and scaled["explained"] == 500.0
