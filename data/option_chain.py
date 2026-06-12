"""Live F&O option-chain resolution + IV-rank proxy (Phase 5 F&O enablement).

Resolves expiries/strikes/option instruments from the NFO instruments master, and
derives an IV-rank proxy from INDIA VIX history (per-instrument IV history isn't
maintained in v1; VIX percentile is the regime proxy the spec allows).
"""
from __future__ import annotations

from datetime import date

from common.db import fetch, fetchrow
from common.market_time import today_ist
from data.instruments import get_token
from data.options import implied_vol
from data.options import iv_rank as _iv_rank
from data.store import load_candles_df


async def list_expiries(name: str) -> list[date]:
    rows = await fetch(
        "SELECT DISTINCT expiry FROM instruments WHERE exchange='NFO' AND name=$1 "
        "AND instrument_type IN ('CE','PE') AND expiry>=current_date ORDER BY expiry", name)
    return [r["expiry"] for r in rows]


async def nearest_expiry(name: str, min_dte: int, max_dte: int) -> tuple[date, int] | None:
    """First expiry whose DTE is within [min_dte, max_dte]; else the nearest beyond."""
    today = today_ist()
    beyond = None
    for e in await list_expiries(name):
        dte = (e - today).days
        if min_dte <= dte <= max_dte:
            return e, dte
        if dte > max_dte and beyond is None:
            beyond = (e, dte)
    return beyond


async def strike_step(name: str, expiry: date) -> float:
    rows = await fetch(
        "SELECT DISTINCT strike FROM instruments WHERE exchange='NFO' AND name=$1 "
        "AND instrument_type='CE' AND expiry=$2 AND strike>0 ORDER BY strike", name, expiry)
    strikes = [float(r["strike"]) for r in rows]
    if len(strikes) < 2:
        return 0.0
    diffs = sorted(b - a for a, b in zip(strikes, strikes[1:]) if b > a)
    return diffs[len(diffs) // 2] if diffs else 0.0  # median spacing (robust to gaps)


def atm_strike(spot: float, step: float) -> float:
    return round(spot / step) * step if step else round(spot)


async def resolve_option(name: str, expiry: date, strike: float, opt: str) -> dict | None:
    row = await fetchrow(
        "SELECT instrument_token, tradingsymbol, lot_size, strike, exchange, instrument_type "
        "FROM instruments WHERE exchange='NFO' AND name=$1 AND expiry=$2 "
        "AND instrument_type=$3 AND strike=$4", name, expiry, opt, float(strike))
    return dict(row) if row else None


async def option_band(name: str, expiry: date, spot: float, step: float, n: int = 3) -> list[dict]:
    """ATM +/- n strikes, both CE and PE — the tokens to subscribe for live quotes."""
    atm = atm_strike(spot, step)
    out = []
    for i in range(-n, n + 1):
        for opt in ("CE", "PE"):
            o = await resolve_option(name, expiry, atm + i * step, opt)
            if o:
                out.append(o)
    return out


async def vix_iv_rank(lookback_days: int = 250) -> float | None:
    """IV-rank proxy = INDIA VIX percentile-rank over its recent range (0..100)."""
    tok = await get_token("NSE:INDIA VIX")
    if not tok:
        return None
    df = await load_candles_df(tok, "day", lookback_days)
    if df.empty or len(df) < 20:
        return None
    closes = [float(c) for c in df["close"].tolist()]
    return round(_iv_rank(closes[-1], closes), 1)


async def atm_iv(adapter, governor, name: str, underlying_key: str,
                 risk_free: float = 0.065) -> float | None:
    """Current ATM implied vol for an underlying (mean of ATM CE+PE IV from live
    quotes). Used by the nightly IV-history snapshot job (Phase 2.2)."""
    ex = await nearest_expiry(name, 0, 60)
    if not ex:
        return None
    expiry, dte = ex
    q = await governor.call("quote", adapter.quote, [underlying_key])
    spot = float(q[underlying_key]["last_price"])
    step = await strike_step(name, expiry)
    if not step:
        return None
    atm = atm_strike(spot, step)
    ce = await resolve_option(name, expiry, atm, "CE")
    pe = await resolve_option(name, expiry, atm, "PE")
    if not ce or not pe:
        return None
    keys = [f"NFO:{ce['tradingsymbol']}", f"NFO:{pe['tradingsymbol']}"]
    oq = await governor.call("quote", adapter.quote, keys)
    t = max(dte, 1) / 365.0
    ivs = []
    for o, opt in ((ce, "CE"), (pe, "PE")):
        ltp = oq.get(f"NFO:{o['tradingsymbol']}", {}).get("last_price")
        if ltp:
            v = implied_vol(float(ltp), spot, atm, t, risk_free, opt)
            if v and v > 0:
                ivs.append(v)
    return sum(ivs) / len(ivs) if ivs else None
