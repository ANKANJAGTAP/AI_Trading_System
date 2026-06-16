"""P0#7 — never send a market exit when the broker already shows the position flat
(the bracket already filled). Pure duplicate-exit guard."""
from execution.policy import BRACKET_ACTIVE, BRACKET_CANCELLED, duplicate_exit_risk


def test_duplicate_exit_risk_when_broker_flat():
    assert duplicate_exit_risk(0) is True


def test_no_duplicate_when_still_open():
    assert duplicate_exit_risk(75) is False
    assert duplicate_exit_risk(-75) is False   # short position still open


def test_bracket_state_constants():
    assert BRACKET_ACTIVE == "BRACKET_ACTIVE"
    assert BRACKET_CANCELLED == "CANCELLED"
