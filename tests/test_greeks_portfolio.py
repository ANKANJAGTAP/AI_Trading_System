"""§10 Phase 5 — portfolio Greeks aggregation + limits."""
from risk.greeks_portfolio import (greek_limit_breaches, portfolio_greeks,
                                   position_greeks)

_LONG_CE = {"S": 100, "K": 100, "t": 0.05, "iv": 0.2, "opt": "CE", "qty": 1, "lot_size": 50}
_SHORT_CE = {**_LONG_CE, "qty": -1}


def test_long_option_greek_signs():
    g = position_greeks(_LONG_CE)
    assert g["delta"] > 0 and g["gamma"] > 0 and g["vega"] > 0 and g["theta"] < 0


def test_short_flips_delta_and_theta():
    g = position_greeks(_SHORT_CE)
    assert g["delta"] < 0 and g["gamma"] < 0 and g["theta"] > 0   # short option: +theta


def test_non_option_is_linear_delta():
    g = position_greeks({"opt": None, "qty": 2, "lot_size": 1})
    assert g == {"delta": 2.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}


def test_portfolio_nets_to_zero_for_offsetting_legs():
    net = portfolio_greeks([_LONG_CE, _SHORT_CE])
    assert abs(net["delta"]) < 1e-6 and abs(net["gamma"]) < 1e-6 and abs(net["vega"]) < 1e-6


def test_limit_breaches():
    net = {"delta": 25.0, "vega": 5.0}
    assert greek_limit_breaches(net, {"delta": 20})  # 25 > 20 -> breach
    assert greek_limit_breaches(net, {"delta": 20})["delta"] == {"net": 25.0, "limit": 20.0}
    assert greek_limit_breaches(net, {"delta": 30}) == {}      # within cap
    assert greek_limit_breaches({"delta": -25.0}, {"delta": 20})  # abs value
