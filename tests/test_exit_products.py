"""P0#3 — only (exchange, product) pairs we can place AND exit are allowed; the
rest fail closed at entry and at exit."""
from execution.policy import exit_product_supported


def test_supported_pairs():
    assert exit_product_supported("NSE", "CNC")
    assert exit_product_supported("NSE", "MIS")
    assert exit_product_supported("NFO", "NRML")
    assert exit_product_supported("MCX", "NRML")


def test_unsupported_pairs_fail_closed():
    assert not exit_product_supported("NFO", "CNC")     # nonsense pairing
    assert not exit_product_supported("MCX", "MIS")
    assert not exit_product_supported("XYZ", "NRML")    # unknown exchange


def test_missing_fields_fail_closed():
    assert not exit_product_supported(None, "MIS")
    assert not exit_product_supported("NSE", None)
    assert not exit_product_supported(None, None)
