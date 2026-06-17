"""#25 — order-realism models: price-band rejection, freeze-qty slicing, rate limit."""
from backtest.execution_model import (freeze_slices, price_band_breached,
                                      rate_limit_ok)


def test_price_band_rejection():
    assert price_band_breached(118.0, 100.0, band_pct=0.20) is False   # +18% within 20%
    assert price_band_breached(121.0, 100.0, band_pct=0.20) is True    # +21% rejected
    assert price_band_breached(79.0, 100.0, band_pct=0.20) is True     # -21% rejected
    assert price_band_breached(100.0, 0.0) is False                    # unknown ref -> no judgement


def test_freeze_slices_splits_above_cap():
    assert freeze_slices(1800, 900) == [900, 900]
    assert freeze_slices(2000, 900) == [900, 900, 200]
    assert sum(freeze_slices(2000, 900)) == 2000
    assert all(s <= 900 for s in freeze_slices(2000, 900))
    assert freeze_slices(500, 900) == [500]            # under the cap -> single order
    assert freeze_slices(500, 0) == [500]              # no freeze limit
    assert freeze_slices(0, 900) == []


def test_rate_limit_gate():
    assert rate_limit_ok(5, 10) is True
    assert rate_limit_ok(10, 10) is False              # budget spent
    assert rate_limit_ok(11, 10) is False
    assert rate_limit_ok(999, 0) is True               # unlimited
