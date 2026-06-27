"""Live FnoPipeline structure-risk leg conversion (§10 P5 gate input). Pure."""
from strategies.fno import structure_risk_legs


def test_credit_spread_legs_signed():
    s = {"type": "bull_put_credit", "opt": "PE", "long_leg": 23450, "short_leg": 23550,
         "max_loss_per_lot": 5000}
    legs = structure_risk_legs(s, spot=23500.0, t=0.08, iv=0.13)
    assert len(legs) == 2
    buy = next(l for l in legs if l["qty"] > 0)
    sell = next(l for l in legs if l["qty"] < 0)
    assert buy["opt"] == "PE" and buy["K"] == 23450.0 and buy["qty"] == 1     # BUY long leg -> +1
    assert sell["opt"] == "PE" and sell["K"] == 23550.0 and sell["qty"] == -1  # SELL short leg -> -1
    assert all(l["S"] == 23500.0 and l["t"] == 0.08 and l["iv"] == 0.13 and l["lot_size"] == 1
               for l in legs)


def test_iron_condor_four_legs_two_short_two_long():
    s = {"type": "iron_condor", "short_legs": [24000, 23000], "long_legs": [24100, 22900]}
    legs = structure_risk_legs(s, 23500.0, 0.08, 0.13)
    assert len(legs) == 4
    assert sum(1 for l in legs if l["qty"] < 0) == 2   # two shorts
    assert sum(1 for l in legs if l["qty"] > 0) == 2   # two long wings
    assert {l["opt"] for l in legs} == {"CE", "PE"}
