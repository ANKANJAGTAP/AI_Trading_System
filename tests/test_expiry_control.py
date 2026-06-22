"""§10 Phase 5 — pin risk + expiry-day controls."""
from datetime import date, timedelta

from risk.expiry_control import (days_to_expiry, expiry_action, moneyness,
                                 pin_risk)


def test_days_to_expiry_and_moneyness():
    assert days_to_expiry(date.today() + timedelta(days=5)) == 5
    assert abs(moneyness(100, 101) - 0.01) < 1e-9
    assert moneyness(100, 100) == 0.0


def test_pin_risk_atm_near_expiry():
    assert pin_risk(100, 100.5, dte=0, atm_band=0.01) is True    # 0.5% ATM on expiry
    assert pin_risk(100, 110, dte=0) is False                    # far OTM
    assert pin_risk(100, 100, dte=5) is False                    # not near expiry


def test_expiry_action_blocks_atm_short_on_expiry():
    assert expiry_action(dte=-1, mny=0.0, is_short=True) == "block"   # expired
    assert expiry_action(dte=0, mny=0.005, is_short=True) == "block"  # ATM short, expiry day
    assert expiry_action(dte=1, mny=0.005, is_short=True) == "reduce" # day before
    assert expiry_action(dte=5, mny=0.005, is_short=True) == "allow"
    assert expiry_action(dte=0, mny=0.005, is_short=False) == "allow" # long is defined-risk
    assert expiry_action(dte=0, mny=0.10, is_short=True) == "allow"   # far OTM short
