"""#18 Tamper-evident audit — pure hash-chain helpers (no I/O, safe to import
anywhere). A day's audit rows are folded into a single sha256 chain; any edit,
reorder, insertion, or deletion changes the final digest. Days are chained too
(each digest seeds the next), so the whole history is one tamper-evident chain."""
from __future__ import annotations

import hashlib
import json


def row_fingerprint(prev: str | None, row: dict) -> str:
    """sha256 of (previous hash || canonical row). Order-sensitive by construction."""
    body = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev or ''}|{body}".encode()).hexdigest()


def chain_digest(rows, prev_digest: str | None = None) -> tuple[str, int]:
    """Fold rows into a single digest, seeded by the prior day's digest. Returns
    (digest, row_count)."""
    h = prev_digest or ""
    n = 0
    for r in rows:
        h = row_fingerprint(h, r)
        n += 1
    return h, n


def verify_chain(rows, expected_digest: str, prev_digest: str | None = None) -> bool:
    """True iff rows reproduce expected_digest — i.e. nothing was tampered with."""
    return chain_digest(rows, prev_digest)[0] == expected_digest
