"""§10 Phase 3 — SPAN-style scan-risk margin."""
from backtest.span_margin import scan_scenarios, span_margin

_LONG_CE = {"S": 100, "K": 100, "t": 0.05, "iv": 0.20, "opt": "CE", "qty": 1, "lot_size": 50}
_SHORT_CE = {**_LONG_CE, "qty": -1}
_SHORT_PE = {**_LONG_CE, "opt": "PE", "qty": -1}


def test_scenario_array_shape():
    scns = scan_scenarios(0.06, 3.0, n_steps=3)
    assert len(scns) == 14                       # (2*3+1) spots x 2 vols
    assert (0.0, 3.0) in scns and (0.0, -3.0) in scns


def test_short_straddle_has_positive_scan_margin():
    out = span_margin([_SHORT_CE, _SHORT_PE])
    assert out["margin"] > 0 and out["scenarios"] == 14
    # worst case for a short straddle is one of the extreme spot moves
    assert abs(out["worst_scenario"][0]) == 0.06


def test_long_call_margin_is_bounded_but_positive():
    out = span_margin([_LONG_CE])
    assert out["margin"] > 0                      # loses in down scenarios


def test_empty_book_zero_margin():
    out = span_margin([])
    assert out["margin"] == 0.0 and out["worst_scenario"] is None
