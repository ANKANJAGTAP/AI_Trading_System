"""P1#9 — risk dependencies fail closed in live, degrade in paper. Pure policy."""
from risk.dependencies import DEGRADED, FAILED, OK, dep_disposition, must_block


def test_available_is_ok_either_mode():
    assert dep_disposition("live", True) == OK
    assert dep_disposition("paper", True) == OK
    assert must_block("live", True) is False
    assert must_block("paper", True) is False


def test_missing_in_live_fails_closed():
    assert dep_disposition("live", False) == FAILED
    assert must_block("live", False) is True


def test_missing_in_paper_degrades():
    assert dep_disposition("paper", False) == DEGRADED
    assert must_block("paper", False) is False
