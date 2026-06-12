"""Verify everything that depends on the NSE F&O (NFO) segment now that it's
activated: account exchanges include NFO, margins, live option quote + OI, and the
NFO order-margin path (the live-order capability). Paper sim never places real orders;
this confirms the account + data + margin plumbing the F&O sleeve relies on.
"""
from __future__ import annotations

import asyncio

from broker.kite_adapter import KiteAdapter
from common.alerts import Alerter
from common.db import close_pool, init_pool
from common.logging import configure_logging
from config.loader import get_config
from config.settings import get_settings
from data.option_chain import atm_strike, nearest_expiry, resolve_option, strike_step
from data.rate_governor import RateGovernor


async def main():
    configure_logging()
    await init_pool()
    cfg, s = get_config(), get_settings()
    adapter = KiteAdapter(s, Alerter(s))
    await asyncio.to_thread(adapter.ensure_token)
    gov = RateGovernor(cfg.data.rate_limits)
    out: dict = {}

    try:
        prof = await asyncio.to_thread(adapter.kite.profile)
        ex = prof.get("exchanges") or []
        out["exchanges"] = ex
        out["NFO_activated"] = "NFO" in ex
        out["MCX_activated"] = "MCX" in ex
        out["CDS_activated"] = "CDS" in ex
    except Exception as e:
        out["profile_ERR"] = str(e)[:160]

    try:
        m = await asyncio.to_thread(adapter.margins)
        out["margin_segments"] = list(m.keys()) if isinstance(m, dict) else str(m)
        if isinstance(m, dict) and "equity" in m:
            out["equity_net"] = m["equity"].get("net")
    except Exception as e:
        out["margins_ERR"] = str(e)[:160]

    try:
        q = await gov.call("quote", adapter.quote, ["NSE:NIFTY 50"])
        spot = float(q["NSE:NIFTY 50"]["last_price"])
        out["nifty_spot"] = spot
        exp = await nearest_expiry("NIFTY", 15, 45)
        if exp:
            expiry, dte = exp
            step = await strike_step("NIFTY", expiry)
            atm = atm_strike(spot, step)
            ce = await resolve_option("NIFTY", expiry, atm, "CE")
            out["atm_option"] = ce["tradingsymbol"]
            out["dte"] = dte
            key = f"NFO:{ce['tradingsymbol']}"
            oq = await gov.call("quote", adapter.quote, [key])
            d = oq.get(key, {})
            out["option_quote"] = {"ltp": d.get("last_price"), "oi": d.get("oi"),
                                   "depth": bool((d.get("depth") or {}).get("buy"))}
            order = {"exchange": "NFO", "tradingsymbol": ce["tradingsymbol"], "transaction_type": "BUY",
                     "variety": "regular", "product": "NRML", "order_type": "MARKET",
                     "quantity": ce["lot_size"], "price": 0}
            try:
                mg = await gov.call("other", adapter.order_margins, [order])
                out["nfo_order_margin_per_lot"] = float(mg[0].get("total")) if mg else None
            except Exception as e:
                out["nfo_order_margin_ERR"] = str(e)[:160]
    except Exception as e:
        out["option_path_ERR"] = str(e)[:160]

    await close_pool()
    print("\n=== NSE F&O SEGMENT DIAG ===")
    for k, v in out.items():
        print(f"{k}: {v}")
    ok = out.get("NFO_activated") and out.get("option_quote", {}).get("ltp") is not None
    print("============================")
    print("NFO segment + F&O data/margins:", "WORKING ✅" if ok else "CHECK ABOVE ⚠️")


if __name__ == "__main__":
    asyncio.run(main())
