"""P0#6 — live F&O structures are blocked (paper-only) by default, fail-closed."""
from execution.policy import live_structures_block_reason


def test_sim_always_allowed():
    assert live_structures_block_reason("simulated_fill", False) is None
    assert live_structures_block_reason("simulated_fill", True) is None


def test_live_blocked_when_flag_off():
    r = live_structures_block_reason("live", False)
    assert r is not None and "paper-only" in r


def test_live_fail_closed_when_flag_on_but_unimplemented():
    r = live_structures_block_reason("live", True)
    assert r is not None and "not implemented" in r
