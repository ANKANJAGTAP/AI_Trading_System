"""Live market-data dashboard endpoints (Phase 6b): Market scanner, Charts, Option
Chain. Built from persisted candles + Redis LTP + a read-only Kite adapter (cached)
for live option data. Degrades gracefully (nulls) when live data is unavailable.
"""
from __future__ import annotations

from datetime import time as dtime

from common.db import fetch, fetchrow
from common.logging import get_logger
from common.market_time import IST, now_ist
from common.redis_client import get_redis
from config.loader import get_config
from data import indicators
from data.gex import compute_gex
from data.instruments import get_instrument, resolve_tokens
from data.oi import classify_buildup
from data.option_chain import atm_strike, list_expiries, nearest_expiry, resolve_option, strike_step, vix_iv_rank
from data.options import greeks, implied_vol, year_fraction
from data.orderflow import book_imbalance
from data.store import load_candles_df
from data.volume_profile import volume_profile

from api.services import cached, governor, read_adapter

log = get_logger("api_marketdata")


async def _load_oi_snapshot(underlying: str, expiry) -> dict[str, tuple[float, float]]:
    """Previous-poll OI/LTP snapshot for an underlying+expiry (token -> (oi, ltp)),
    so the chain can show OI change + buildup vs the last poll."""
    try:
        raw = await (await get_redis()).hgetall(f"aegis:oi:{underlying}:{expiry}")
    except Exception:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for tok, val in (raw or {}).items():
        try:
            oi_s, ltp_s = val.split(":")
            out[tok] = (float(oi_s), float(ltp_s))
        except Exception:
            continue
    return out


async def _save_oi_snapshot(underlying: str, expiry, snap: dict[str, tuple[float, float]]) -> None:
    if not snap:
        return
    try:
        r = await get_redis()
        key = f"aegis:oi:{underlying}:{expiry}"
        await r.hset(key, mapping={t: f"{oi}:{ltp}" for t, (oi, ltp) in snap.items()})
        await r.expire(key, 86400)
    except Exception:
        pass


async def _today_5m(token: int):
    df = await load_candles_df(token, "5m", 400)
    if df.empty:
        return df
    idx = df.index.tz_convert(IST)
    return df[idx.date == now_ist().date()]


async def _row(key: str, token: int, ban: set, iv_rank: float | None) -> dict:
    inst = await get_instrument(token) or {}
    is_index = (inst.get("segment") == "INDICES")
    name = key.split(":")[-1]
    row = {"instrument": name, "key": key, "token": token,
           "sleeves": [] if is_index else (["intraday_stocks", "swing_stocks"]),
           "ltp": None, "chg": None, "chg_pct": None, "spark": [], "rvol": None, "vwap_dist": None,
           "or_state": None, "vol_vs_avg": None, "day_range": None,
           "oi": None, "oi_chg": None, "iv": None, "iv_rank": iv_rank, "pcr": None,
           "fno_ban": name in ban, "signal_state": None, "eligible": not is_index}
    try:
        r = await get_redis()
        v = await r.hget("md:ltp", str(token))
        last = float(v) if v else None
        tdf = await _today_5m(token)
        daily = await load_candles_df(token, "day", 40)
        if last is None and not tdf.empty:
            last = float(tdf["close"].iloc[-1])
        row["ltp"] = last
        if len(daily) >= 2:
            prev = float(daily["close"].iloc[-2])
            if prev and last:
                row["chg"], row["chg_pct"] = round(last - prev, 2), round((last - prev) / prev * 100, 2)
        if not tdf.empty:
            row["spark"] = [round(float(c), 2) for c in tdf["close"].tail(30).tolist()]
            vwap = float(indicators.session_vwap(tdf).iloc[-1])
            if last and vwap:
                row["vwap_dist"] = round((last - vwap) / vwap * 100, 2)
            rv = indicators.rvol(tdf["volume"], 20).iloc[-1]
            row["rvol"] = round(float(rv), 2) if rv == rv else None
            lo, hi = float(tdf["low"].min()), float(tdf["high"].max())
            row["day_range"] = {"lo": lo, "hi": hi,
                                "pos": round((last - lo) / (hi - lo), 2) if hi > lo and last else None}
            tmask = [dtime(9, 15) <= t.time() < dtime(9, 30) for t in tdf.index.tz_convert(IST)]
            orng = tdf[tmask]
            if len(orng) and last:
                orh, orl = float(orng["high"].max()), float(orng["low"].min())
                row["or_state"] = "above" if last > orh else ("below" if last < orl else "inside")
            if not daily.empty:
                avg_vol = float(daily["volume"].tail(20).mean())
                if avg_vol:
                    row["vol_vs_avg"] = round(float(tdf["volume"].sum()) / avg_vol, 2)
        sig = await fetchrow("SELECT decision, setup FROM signals WHERE instrument_token=$1 "
                             "ORDER BY ts DESC LIMIT 1", token)
        if sig:
            row["signal_state"] = f"{sig['decision']}:{sig['setup']}"
    except Exception as exc:
        log.warning("market_row_failed", key=key, error=str(exc))
    return row


async def _market() -> list[dict]:
    cfg = get_config()
    subs = (cfg.data.universe or {}).get("subscribe", [])
    ban = set((cfg.strategy.fno or {}).get("ban_list") or [])
    iv_rank = await vix_iv_rank()
    token_map = await resolve_tokens(subs)
    return [await _row(k, t, ban, iv_rank) for k, t in token_map.items()]


async def market() -> list[dict]:
    return await cached("aegis:cache:market", 5, _market)


async def _breadth() -> dict:
    from data.breadth import market_breadth
    subs = (get_config().data.universe or {}).get("subscribe", [])
    token_map = await resolve_tokens(subs)
    return await market_breadth(list(token_map.values()))


async def breadth() -> dict:
    return await cached("aegis:cache:breadth", 30, _breadth)


async def chart(instrument: str, interval: str = "5m", limit: int = 200) -> dict:
    """Candles + overlays + signal/trade markers (DB) + live depth (cached adapter)."""
    inst = await fetchrow("SELECT instrument_token, exchange, tradingsymbol FROM instruments "
                          "WHERE tradingsymbol=$1 ORDER BY (exchange='NSE') DESC LIMIT 1", instrument)
    if not inst:
        return {"error": f"unknown instrument {instrument}", "candles": []}
    token = inst["instrument_token"]
    df = await load_candles_df(token, interval, limit)
    candles, overlays = [], {"vwap": [], "emas": {}, "sma200": [], "bb_upper": [], "bb_lower": [],
                             "supertrend": [], "or_box": None, "atr_stop": None, "sr": []}
    if not df.empty:
        d = indicators.add_core_indicators(df, intraday=(interval != "day"))

        def _ov(col: str, key: str, ts_iso: str, row) -> None:
            v = row.get(col)
            if v is not None and v == v:   # finite (NaN-safe)
                overlays[key].append({"ts": ts_iso, "value": round(float(v), 2)})

        for ts, row in d.iterrows():
            t = ts.isoformat()
            candles.append({"ts": t, "open": float(row["open"]), "high": float(row["high"]),
                            "low": float(row["low"]), "close": float(row["close"]), "volume": float(row["volume"])})
            _ov("vwap", "vwap", t, row)
            _ov("sma200", "sma200", t, row)
            _ov("bb_upper", "bb_upper", t, row)
            _ov("bb_lower", "bb_lower", t, row)
            _ov("supertrend", "supertrend", t, row)
    markers = []
    for s in await fetch("SELECT ts, correlation_id, decision, setup, side, entry_price FROM signals "
                         "WHERE instrument_token=$1 ORDER BY ts DESC LIMIT 50", token):
        markers.append({"ts": s["ts"].isoformat(), "type": "signal", "decision": s["decision"],
                        "correlation_id": str(s["correlation_id"]), "setup": s["setup"],
                        "side": s["side"], "price": float(s["entry_price"] or 0)})
    for p in await fetch("SELECT opened_at, closed_at, side, entry_price, status, realized_pnl FROM positions "
                         "WHERE instrument_token=$1 ORDER BY opened_at DESC LIMIT 50", token):
        markers.append({"ts": p["opened_at"].isoformat(), "type": "entry", "side": p["side"],
                        "price": float(p["entry_price"] or 0)})
    depth = {"bids": [], "asks": []}
    ad = read_adapter()
    if ad is not None:
        try:
            key = f"{inst['exchange']}:{instrument}"
            q = await cached(f"aegis:cache:depth:{key}", 2,
                             lambda: governor().call("quote", ad.quote, [key]))
            dp = (q.get(key, {}) or {}).get("depth") or {}
            depth = {"bids": dp.get("buy", []), "asks": dp.get("sell", [])}
        except Exception:
            pass
    depth["imbalance"] = book_imbalance(depth.get("bids"), depth.get("asks"))  # Phase 3.4
    vol_profile = volume_profile(df) if not df.empty else {"poc": None, "vah": None, "val": None, "bins": []}
    return {"instrument": instrument, "interval": interval, "candles": candles,
            "overlays": overlays, "markers": markers, "depth": depth, "volume_profile": vol_profile}


async def _optionchain(underlying: str, n: int = 10, expiry_str: str | None = None) -> dict:
    cfg = get_config()
    ad = read_adapter()
    ukey = None
    for e in (cfg.data.universe or {}).get("fno", []):
        if e.get("name") == underlying:
            ukey = e.get("underlying")
    if ad is None or not ukey:
        return {"underlying": underlying, "error": "live adapter/underlying unavailable", "strikes": []}
    q = await governor().call("quote", ad.quote, [ukey])
    spot = float(q[ukey]["last_price"])
    expiries = await list_expiries(underlying)
    expiry = next((e for e in expiries if str(e) == expiry_str), None) if expiry_str else None
    if expiry is None:
        ex = await nearest_expiry(underlying, 0, 365)
        if not ex:
            return {"underlying": underlying, "error": "no expiry", "strikes": []}
        expiry = ex[0]
    dte = (expiry - now_ist().date()).days
    step = await strike_step(underlying, expiry)
    atm = atm_strike(spot, step)
    strikes = [atm + i * step for i in range(-n, n + 1)]
    legs = {}
    for k in strikes:
        for opt in ("CE", "PE"):
            o = await resolve_option(underlying, expiry, k, opt)
            if o:
                legs[(k, opt)] = o
    keys = [f"NFO:{o['tradingsymbol']}" for o in legs.values()]
    qd = await governor().call("quote", ad.quote, keys)
    t = max(dte, 1) / 365.0
    prev_snap = await _load_oi_snapshot(underlying, expiry)   # token -> (oi, ltp) last poll
    new_snap: dict[str, tuple[float, float]] = {}
    matrix = (cfg.strategy.fno or {}).get("oi_buildup")
    rows, ce_oi, pe_oi, skew, pain = [], 0.0, 0.0, [], {}
    for k in strikes:
        entry = {"strike": k, "call": None, "put": None}
        for opt in ("CE", "PE"):
            o = legs.get((k, opt))
            if not o:
                continue
            d = qd.get(f"NFO:{o['tradingsymbol']}", {})
            ltp = float(d.get("last_price") or 0)
            oi = float(d.get("oi") or 0)
            iv = implied_vol(ltp, spot, k, t, 0.065, opt) if ltp > 0 else 0.0
            g = greeks(spot, k, t, 0.065, iv or 0.2, opt)
            tok = str(o["instrument_token"])
            prev_oi, prev_ltp = prev_snap.get(tok, (oi, ltp))
            oi_chg = round(oi - prev_oi, 0)
            new_snap[tok] = (oi, ltp)
            cell = {"ltp": ltp, "oi": oi, "oi_chg": oi_chg, "volume": d.get("volume"), "iv": round(iv, 4),
                    "buildup": classify_buildup(ltp - prev_ltp, oi - prev_oi, matrix),
                    "delta": round(g["delta"], 3), "theta": round(g["theta"], 3),
                    "gamma": round(g["gamma"], 5), "vega": round(g["vega"], 3)}
            entry["call" if opt == "CE" else "put"] = cell
            if opt == "CE":
                ce_oi += oi
            else:
                pe_oi += oi
            if opt == "CE":
                skew.append({"strike": k, "iv": round(iv, 4)})
        rows.append(entry)
    await _save_oi_snapshot(underlying, expiry, new_snap)
    # max pain: the strike that minimises total option-holder payout at expiry.
    def _oi_at(strike: float, opt: str) -> float:
        o = legs.get((strike, opt))
        if not o:
            return 0.0
        return float(qd.get(f"NFO:{o['tradingsymbol']}", {}).get("oi") or 0)

    for k in strikes:
        call_payout = sum(max(0.0, k - s) * _oi_at(s, "CE") for s in strikes)
        put_payout = sum(max(0.0, s - k) * _oi_at(s, "PE") for s in strikes)
        pain[k] = call_payout + put_payout
    max_pain = min(pain, key=pain.get) if pain else atm
    vix = await vix_iv_rank()
    lot = float(next(iter(legs.values()), {}).get("lot_size") or 1)
    gex = compute_gex(rows, spot, lot)   # dealer-gamma regime (Phase 3.1)
    return {"underlying": underlying, "expiry": str(expiry), "expiries": [str(e) for e in expiries[:8]],
            "dte": dte, "spot": spot, "atm": atm,
            "strikes": rows, "pcr": round(pe_oi / ce_oi, 2) if ce_oi else None,
            "max_pain": max_pain, "ce_oi": ce_oi, "pe_oi": pe_oi, "iv_skew": skew, "vix_rank": vix,
            "gex": gex, "suggested_strikes": [atm, atm + step, atm - step]}


async def optionchain(underlying: str, expiry: str | None = None) -> dict:
    return await cached(f"aegis:cache:chain:{underlying}:{expiry or 'near'}", 5,
                        lambda: _optionchain(underlying, expiry_str=expiry))
