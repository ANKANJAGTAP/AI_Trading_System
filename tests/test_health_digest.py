"""Daily health digest — the formatter is pure and rendered correctly."""
from research.health_digest import format_digest


def test_format_digest_contains_key_fields():
    s = {"date": "2026-06-17", "mode": "simulated_fill", "kill_switch": False,
         "block_new_entries": False, "heartbeat": "hb", "feed_last": "ft",
         "lake_rows": 3252, "lake_days": 12, "open_positions": 0,
         "realized": 0.0, "unrealized": 0.0, "day_pnl": 0.0,
         "prelive_overall": "fail", "prelive_failed": ["kill_switch_ready"]}
    txt = format_digest(s)
    assert "simulated_fill" in txt
    assert "3,252 rows / 12 trading days" in txt
    assert "Go-live ready    : fail" in txt
    assert "kill_switch_ready" in txt


def test_format_digest_flags_active_states():
    txt = format_digest({"date": "d", "kill_switch": True, "block_new_entries": True})
    assert "ACTIVE" in txt and "BLOCKED" in txt
