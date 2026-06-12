"""Probe which Kite endpoint categories are enabled for this app/account.

Helps distinguish a code issue from an account/subscription issue: data APIs
(profile, ltp, instruments) vs trading/RMS APIs (margins, positions, holdings,
orders). Uses the cached token (or logs in). Prints OK / FAIL per endpoint.
"""
from __future__ import annotations

from broker.kite_adapter import KiteAdapter
from config.settings import get_settings


def probe(name, fn):
    try:
        r = fn()
        size = f"{len(r)} items" if isinstance(r, (list, dict)) else repr(r)[:60]
        print(f"[OK]   {name}: {type(r).__name__} {size}")
    except Exception as exc:
        print(f"[FAIL] {name}: {exc}")


def main():
    adapter = KiteAdapter(get_settings())
    adapter.ensure_token()
    k = adapter.kite

    print("--- data APIs ---")
    try:
        prof = k.profile()
        print(f"[OK]   profile: exchanges={prof.get('exchanges')} "
              f"products={prof.get('products')} order_types={prof.get('order_types')}")
    except Exception as exc:
        print(f"[FAIL] profile: {exc}")
    probe("ltp NSE:INFY", lambda: k.ltp("NSE:INFY"))

    print("--- trading / RMS APIs ---")
    probe("margins()", k.margins)
    probe("margins('equity')", lambda: k.margins("equity"))
    probe("margins('commodity')", lambda: k.margins("commodity"))
    probe("positions", k.positions)
    probe("holdings", k.holdings)
    probe("orders", k.orders)


if __name__ == "__main__":
    main()
