"""
Execution intent — translate an accepted TradeDecision into Kite order params.

This module BUILDS orders; it does not fire them. Placing real orders is a
side-effectful, irreversible action that must be an explicit, reviewed step you
take yourself — `place_orders` refuses to run unless you pass confirm=True, and
even then you should have a human in the loop and the SEBI-2026 controls
(Algo-ID, static IP, OPS limits) satisfied.
"""
from __future__ import annotations


def to_kite_orders(decision, expiry, instruments,
                   exchange: str = "NFO", product: str = "NRML",
                   order_type: str = "MARKET") -> list[dict]:
    """Convert an accepted decision's structure into Kite order param dicts.

    `instruments` is a KiteInstruments (to resolve tradingsymbols). Returns one
    order dict per leg; empty list if the decision was rejected.
    """
    if not getattr(decision, "accepted", False) or decision.structure is None:
        return []
    orders = []
    for leg in decision.structure.legs:
        opt = leg.opt_type if leg.opt_type in ("CE", "PE") else "FUT"
        tsym = instruments.tradingsymbol_for(decision.underlying, expiry,
                                             None if opt == "FUT" else leg.strike, opt)
        if tsym is None:
            raise ValueError(
                f"no tradingsymbol for {decision.underlying} {expiry} "
                f"{leg.strike} {opt} — check the instruments dump")
        orders.append({
            "tradingsymbol": tsym,
            "exchange": exchange,
            "transaction_type": leg.side.upper(),    # BUY / SELL
            "quantity": int(leg.qty),
            "order_type": order_type,
            "product": product,
            "variety": "regular",
        })
    return orders


def place_orders(kite, orders: list[dict], confirm: bool = False) -> list:
    """Place the built orders via a KiteConnect client.

    GUARDED: raises unless confirm=True. Executing trades is irreversible and is
    your explicit responsibility — review every order first. This function exists
    so the path is complete, not so it runs unattended.
    """
    if not confirm:
        raise PermissionError(
            "Refusing to place orders without confirm=True. Review the orders, "
            "ensure compliance (Algo-ID/static-IP/OPS), then opt in explicitly.")
    ids = []
    for o in orders:
        ids.append(kite.place_order(**o))
    return ids
