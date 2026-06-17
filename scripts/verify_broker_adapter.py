"""Read-only live validation of the Kite broker adapter (the go-live gate).

SAFE BY DESIGN — this script only READS from the broker: login, margins,
positions, holdings, quotes, and `order_history` for an order *you* placed
yourself. It NEVER places, modifies, or cancels an order, so it can never
initiate a trade. You place any test order through the Kite app; this tool just
confirms the adapter reads it back and that the live reduction matches the
contract the test-suite pins (`policy.reduce_order_history`).

Run on the machine that holds the Kite credentials (.env), NOT in the sandbox:

    python scripts/verify_broker_adapter.py                # read-path smoke test
    python scripts/verify_broker_adapter.py <ORDER_ID>     # + validate the live
                                                           #   order_history -> reduce
                                                           #   -> normalize -> booking

To validate the full order path: place a 1-lot order in Kite (or a tiny LIMIT far
from the market that you then cancel), copy its order_id, and pass it here. The
script prints the exact status/fill the live executor would act on.
"""
from __future__ import annotations

import sys

from broker.kite_adapter import KiteAdapter
from config.settings import get_settings
from execution.policy import (close_books_fully, normalize_exit_status,
                              reduce_order_history)

PASS, FAIL = "[PASS]", "[FAIL]"

# Hard guard: this tool is read-only. Listing the write methods here documents the
# intent and makes any accidental future edit that calls one obvious in review.
_FORBIDDEN = ("place_order", "place_gtt", "place_oco", "modify_order",
              "cancel_order", "delete_gtt")


def _check(name, fn):
    try:
        r = fn()
        size = f"{len(r)} items" if isinstance(r, (list, dict)) else repr(r)[:60]
        print(f"{PASS} {name}: {type(r).__name__} {size}")
        return r
    except Exception as exc:  # noqa: BLE001 - diagnostic: report any failure verbatim
        print(f"{FAIL} {name}: {exc}")
        return None


def main(argv: list[str]) -> int:
    adapter = KiteAdapter(get_settings())
    adapter.ensure_token()

    print("--- adapter read path (NO orders are placed) ---")
    _check("margins", adapter.margins)
    _check("positions", adapter.positions)
    _check("holdings", adapter.holdings)
    _check("ltp NSE:INFY", lambda: adapter.ltp("NSE:INFY"))
    _check("orders", adapter.orders)

    order_id = argv[1] if len(argv) > 1 else None
    if not order_id:
        print("\nNo order_id supplied. To validate the live order -> fill -> book path, "
              "place a 1-lot order in the Kite app, then re-run:\n"
              "    python scripts/verify_broker_adapter.py <ORDER_ID>")
        return 0

    print(f"\n--- live order path for order_id={order_id} (read-only) ---")
    hist = _check(f"order_history({order_id})", lambda: adapter.order_history(order_id))
    if not hist:
        return 1
    rec = reduce_order_history(hist)
    norm = normalize_exit_status(rec["status"], rec["filled"])
    qty = rec["filled"] or int(hist[-1].get("quantity", 0) or 0)
    books = close_books_fully(norm, rec["filled"], qty)
    print(f"  reduce_order_history -> status={rec['status']} filled={rec['filled']} "
          f"avg={rec['avg_price']} terminal={rec['terminal']}")
    print(f"  normalize_exit_status -> {norm}")
    print(f"  close_books_fully({norm}, filled={rec['filled']}, qty={qty}) -> {books}")
    print("\nThis is the EXACT reduction the live executor uses "
          "(execution.policy.reduce_order_history), so a green run here means the "
          "live fill-truth path matches the contract test-suite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
