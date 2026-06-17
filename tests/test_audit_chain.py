"""#18 — audit hash-chain digest (pure): deterministic, order-sensitive,
tamper-evident, and chained across days."""
from common.audit_chain import chain_digest, row_fingerprint, verify_chain

ROWS = [
    {"id": 1, "event_type": "order", "message": "placed", "payload": {"qty": 50}},
    {"id": 2, "event_type": "fill", "message": "filled", "payload": {"qty": 50}},
    {"id": 3, "event_type": "exit", "message": "closed", "payload": {"pnl": 1200}},
]


def test_digest_is_deterministic():
    assert chain_digest(ROWS) == chain_digest(ROWS)


def test_verify_passes_for_untampered_rows():
    digest, n = chain_digest(ROWS)
    assert n == 3
    assert verify_chain(ROWS, digest) is True


def test_tampering_a_row_breaks_the_chain():
    digest, _ = chain_digest(ROWS)
    tampered = [dict(r) for r in ROWS]
    tampered[2]["payload"] = {"pnl": 999999}  # cook the books
    assert verify_chain(tampered, digest) is False


def test_reordering_breaks_the_chain():
    digest, _ = chain_digest(ROWS)
    assert verify_chain(list(reversed(ROWS)), digest) is False


def test_deletion_breaks_the_chain():
    digest, _ = chain_digest(ROWS)
    assert verify_chain(ROWS[:-1], digest) is False


def test_prev_digest_chains_days():
    d1, _ = chain_digest(ROWS)
    # the same rows under a different prior-day digest yield a different result
    d2a, _ = chain_digest(ROWS, prev_digest=d1)
    d2b, _ = chain_digest(ROWS, prev_digest="different")
    assert d2a != d2b
    assert verify_chain(ROWS, d2a, prev_digest=d1) is True


def test_fingerprint_changes_with_prev():
    assert row_fingerprint("a", {"x": 1}) != row_fingerprint("b", {"x": 1})
