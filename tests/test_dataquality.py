"""#29 — market-data quality gate (pure)."""
from common.dataquality import validate_tick


def test_good_tick_passes():
    assert validate_tick(100.0, prev_price=99.5, ts_age_s=2, bid=99.9, ask=100.1).ok


def test_non_positive_price_rejected():
    assert not validate_tick(0).ok
    assert not validate_tick(-5).ok


def test_stale_tick_rejected():
    assert not validate_tick(100.0, ts_age_s=120, max_age_s=30).ok
    assert validate_tick(100.0, ts_age_s=10, max_age_s=30).ok


def test_crossed_book_rejected():
    assert not validate_tick(100.0, bid=101.0, ask=100.0).ok   # bid > ask
    assert not validate_tick(100.0, bid=-1, ask=100.0).ok


def test_unrealistic_jump_rejected():
    assert not validate_tick(150.0, prev_price=100.0, max_jump_pct=0.20).ok  # +50%
    assert validate_tick(110.0, prev_price=100.0, max_jump_pct=0.20).ok   # +10% ok


def test_negative_volume_rejected():
    assert not validate_tick(100.0, volume=-10).ok
