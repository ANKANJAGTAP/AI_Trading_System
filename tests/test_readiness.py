"""#32 — pure overall-readiness roll-up."""
from api.readiness import DOWN, OK, WARN, overall_ready


def test_all_ok_is_pass():
    assert overall_ready([{"status": OK}, {"status": OK}]) == "pass"


def test_any_down_is_fail():
    assert overall_ready([{"status": OK}, {"status": DOWN}, {"status": WARN}]) == "fail"


def test_any_warn_without_down_is_warn():
    assert overall_ready([{"status": OK}, {"status": WARN}]) == "warn"


def test_empty_is_warn():
    assert overall_ready([]) == "warn"


def test_down_dominates_warn():
    assert overall_ready([{"status": WARN}, {"status": DOWN}]) == "fail"
