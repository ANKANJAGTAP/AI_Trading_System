from fno_backtest.instruments import (
    bull_call_spread, intrinsic, settlement_pnl,
)


def test_intrinsic():
    assert intrinsic("CE", 100, 110) == 10
    assert intrinsic("PE", 100, 90) == 10
    assert intrinsic("CE", 100, 90) == 0
    assert intrinsic("PE", 100, 110) == 0


def test_bull_call_spread_defined_risk():
    s = bull_call_spread(100, 110, qty=50, price_lo=5, price_hi=2)
    assert abs(s.net_premium() - (5 - 2) * 50) < 1e-9       # 150 net debit
    assert abs(s.payoff_at(90) - (-150)) < 1e-9             # max loss below lower strike
    assert abs(s.payoff_at(120) - 350) < 1e-9               # (width - debit) * qty


def test_bull_call_spread_profile():
    s = bull_call_spread(100, 110, qty=50, price_lo=5, price_hi=2)
    prof = s.profile(80, 130)
    assert abs(prof["max_loss"] + 150) < 1.0
    assert abs(prof["max_profit"] - 350) < 1.0
    assert any(abs(be - 103) < 1.0 for be in prof["breakevens"])   # BE = 100 + 3


def test_settlement_equals_payoff():
    s = bull_call_spread(100, 110, qty=50, price_lo=5, price_hi=2)
    assert settlement_pnl(s, 105) == s.payoff_at(105)
