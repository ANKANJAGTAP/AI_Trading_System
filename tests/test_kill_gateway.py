"""P1#14 — single order gate: ENTRY blocked when the kill-switch is active or new
entries are blocked; EXIT/CANCEL always allowed so risk can always be closed."""
from execution.policy import order_allowed


def test_entry_blocked_when_kill_active():
    assert order_allowed("ENTRY", kill_active=True, block_new_entries=False) is False


def test_entry_blocked_when_new_entries_blocked():
    assert order_allowed("ENTRY", kill_active=False, block_new_entries=True) is False


def test_entry_allowed_when_clear():
    assert order_allowed("ENTRY", kill_active=False, block_new_entries=False) is True


def test_exit_and_cancel_always_allowed():
    assert order_allowed("EXIT", kill_active=True, block_new_entries=True) is True
    assert order_allowed("CANCEL", kill_active=True, block_new_entries=True) is True
