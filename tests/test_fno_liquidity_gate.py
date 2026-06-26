"""Live FnoPipeline liquidity-floor resolution (pure)."""
from strategies.fno import liquidity_floor


def test_per_underlying_override_beats_global():
    cfg = {"min_atm_oi": 5000, "min_atm_volume": 100, "per_underlying": {"FINNIFTY": 20000}}
    assert liquidity_floor(cfg, "FINNIFTY") == (20000.0, 100.0)   # override
    assert liquidity_floor(cfg, "NIFTY") == (5000.0, 100.0)       # global fallback


def test_global_used_when_symbol_absent():
    cfg = {"min_atm_oi": 8000, "per_underlying": {"FINNIFTY": 20000}}
    assert liquidity_floor(cfg, "BANKNIFTY") == (8000.0, 0.0)


def test_disabled_when_zero_or_missing():
    assert liquidity_floor({}, "NIFTY") == (0.0, 0.0)
    assert liquidity_floor({"min_atm_oi": 0, "min_atm_volume": 0}, "X") == (0.0, 0.0)
    assert liquidity_floor(None, "X") == (0.0, 0.0)
