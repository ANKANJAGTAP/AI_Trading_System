"""GATING CHECK for F&O paper trading: does this (equity-only-activated) account
have NFO market-data access — option quotes + OI + depth + historical — plus
INDIA VIX (IV-rank proxy)? Market-data access is usually separate from trading
activation; this confirms it before we build the F&O live layer. Run during market
hours for live quotes.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from broker.kite_adapter import KiteAdapter
from common.alerts import Alerter
from common.db import close_pool, fetch, fetchrow, fetchval, init_pool
from common.logging import configure_logging
from common.market_time import now_ist
from config.loader import get_config
from config.settings import get_settings
from data.rate_governor import RateGovernor


async def main():
    configure_logging()
    await init_pool()
    cfg, settings = get_config(), get_settings()
    adapter = KiteAdapter(settings, Alerter(settings))
    await asyncio.to_thread(adapter.ensure_token)
    gov = RateGovernor(cfg.data.rate_limits)
    out: dict = {}

    out["nfo_instruments"] = await fetchval("SELECT count(*) FROM instruments WHERE exchange='NFO'")
    out["nfo_option_names"] = await fetchval(
        "SELECT count(DISTINCT name) FROM instruments WHERE exchange='NFO' AND instrument_type IN ('CE','PE')")

    spot = None
    try:
        q = await gov.call("quote", adapter.quote, ["NSE:NIFTY 50"])
        spot = float(q["NSE:NIFTY 50"]["last_price"])
        out["nifty_spot"] = spot
    except Exception as e:
        out["nifty_spot_ERR"] = str(e)[:140]

    exps = [r["expiry"] for r in await fetch(
        "SELECT DISTINCT expiry FROM instruments WHERE exchange='NFO' AND name='NIFTY' "
        "AND instrument_type='CE' AND expiry>=current_date ORDER BY expiry LIMIT 6")]
    out["nifty_expiries"] = [str(e) for e in exps]

    ce = pe = None
    keys = []
    if spot and exps:
        exp = exps[0]
        atm = round(spot / 50) * 50
        out["expiry_used"], out["atm_strike"] = str(exp), atm
        ce = await fetchrow("SELECT tradingsymbol, instrument_token, lot_size, strike FROM instruments "
                            "WHERE exchange='NFO' AND name='NIFTY' AND instrument_type='CE' "
                            "AND expiry=$1 AND strike=$2", exp, atm)
        pe = await fetchrow("SELECT tradingsymbol, instrument_token, lot_size, strike FROM instruments "
                            "WHERE exchange='NFO' AND name='NIFTY' AND instrument_type='PE' "
                            "AND expiry=$1 AND strike=$2", exp, atm)
        out["atm_ce"] = ce["tradingsymbol"] if ce else "NOT FOUND"
        out["atm_ce_lot_size"] = ce["lot_size"] if ce else None
        keys = [f"NFO:{o['tradingsymbol']}" for o in (ce, pe) if o]

    if keys:
        try:
            oq = await gov.call("quote", adapter.quote, keys)
            for k in keys:
                d = oq.get(k, {})
                out[f"OPTQUOTE {k}"] = {
                    "ltp": d.get("last_price"), "oi": d.get("oi"),
                    "depth": bool((d.get("depth") or {}).get("buy")),
                    "volume": d.get("volume") or d.get("volume_traded"),
                }
        except Exception as e:
            out["option_quote_ERR"] = str(e)[:140]

    if ce:
        try:
            to = now_ist()
            hist = await gov.call("historical", adapter.historical,
                                  ce["instrument_token"], to - timedelta(days=4), to, "day", False, True)
            out["option_historical_candles"] = len(hist) if hist else 0
        except Exception as e:
            out["option_historical_ERR"] = str(e)[:140]

    try:
        vq = await gov.call("quote", adapter.quote, ["NSE:INDIA VIX"])
        out["india_vix"] = vq.get("NSE:INDIA VIX", {}).get("last_price")
    except Exception as e:
        out["india_vix_ERR"] = str(e)[:140]

    if ce:  # expected to FAIL without F&O activation -> paper must model margin
        try:
            order = {"exchange": "NFO", "tradingsymbol": ce["tradingsymbol"], "transaction_type": "BUY",
                     "variety": "regular", "product": "NRML", "order_type": "MARKET",
                     "quantity": ce["lot_size"], "price": 0}
            m = await gov.call("other", adapter.order_margins, [order])
            out["option_order_margin"] = float(m[0].get("total")) if m else None
        except Exception as e:
            out["option_order_margin_ERR(expected)"] = str(e)[:140]

    await close_pool()
    print("\n=== F&O DATA-ACCESS DIAG ===")
    for k, v in out.items():
        print(f"{k}: {v}")
    print("============================")


if __name__ == "__main__":
    asyncio.run(main())
