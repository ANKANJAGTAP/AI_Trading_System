"""§10 Phase 5 integration — structure pre-trade risk assessment."""
from risk.structure_risk import assess_structure

_SHORT_CE = {"S": 100, "K": 100, "t": 0.05, "iv": 0.20, "opt": "CE", "qty": -1, "lot_size": 50}
_SHORT_PE = {**_SHORT_CE, "opt": "PE"}
_LONG_CE = {**_SHORT_CE, "qty": 1}
_SHORT_STRADDLE = [_SHORT_CE, _SHORT_PE]


def test_short_straddle_metrics():
    a = assess_structure(_SHORT_STRADDLE, spot=100)
    assert abs(a["net_greeks"]["delta"]) < 6.0       # near-neutral (vs ~25 per leg; carry skews it slightly)
    assert a["net_greeks"]["gamma"] < 0 and a["net_greeks"]["vega"] < 0   # short gamma/vega
    assert a["stress_var"] < 0 and a["span_margin"] > 0
    assert a["blocked"] is False                      # no limits configured


def test_greek_limit_blocks():
    a = assess_structure(_SHORT_STRADDLE, spot=100, greek_limits={"vega": 1.0})
    assert a["blocked"] is True and "greek_limits" in a["reason"]


def test_stress_loss_cap_blocks():
    a = assess_structure(_SHORT_STRADDLE, spot=100, max_stress_loss=10.0)
    assert a["blocked"] is True and "stress_var" in a["reason"]


def test_expiry_day_atm_short_blocks():
    a = assess_structure(_SHORT_STRADDLE, spot=100, dte=0)   # expiry day, ATM shorts
    assert a["expiry_action"] == "block" and a["blocked"] is True


def test_long_call_allowed():
    a = assess_structure([_LONG_CE], spot=100, dte=30)
    assert a["net_greeks"]["delta"] > 0 and a["blocked"] is False
    assert a["expiry_action"] == "allow"
