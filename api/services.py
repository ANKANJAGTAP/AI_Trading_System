"""Data-access layer for the dashboard API (Phase 6 / Section 9).

Pure reads from Postgres + Redis (LTP, heartbeats) shaped to the frontend's
Appendix B contract. Capital in paper mode is the configured paper_capital;
otherwise today's recorded starting_capital.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta

from common.db import fetch, fetchrow
from common.logging import get_logger
from common.market_time import IST, is_within, now_ist
from common.redis_client import get_redis
from common.state import get_state
from config.loader import get_config
from config.settings import get_settings
from data.store import load_candles_df
from risk.heat import compute_heat

log = get_logger("api_services")

_ADAPTER = None      # shared read-only KiteAdapter (uses the engine's cached token)
_GOVERNOR = None


def read_adapter():
    """Read-only KiteAdapter using the engine's cached daily token (NO login — never
    re-auth from the API, which would invalidate the engine's token). The token is
    RE-READ on every call so it survives the daily 08:00 rotation without an API
    restart. None if no valid token, so live-data endpoints degrade gracefully."""
    global _ADAPTER
    try:
        from broker.kite_adapter import KiteAdapter
        if _ADAPTER is None:
            _ADAPTER = KiteAdapter(get_settings())
        tok = _ADAPTER.token_store.valid_token_for_today()
        if not tok:
            return None
        if _ADAPTER._access_token != tok:   # rotated -> refresh the cached adapter
            _ADAPTER.kite.set_access_token(tok)
            _ADAPTER._access_token = tok
        return _ADAPTER
    except Exception as exc:
        log.warning("read_adapter_unavailable", error=str(exc))
        return None


def governor():
    global _GOVERNOR
    if _GOVERNOR is None:
        from data.rate_governor import RateGovernor
        _GOVERNOR = RateGovernor(get_config().data.rate_limits)
    return _GOVERNOR


async def cached(key: str, ttl: int, factory):
    """Redis-cached get-or-compute (JSON), to bound live Kite calls under dashboard polling."""
    r = await get_redis()
    hit = await r.get(key)
    if hit is not None:
        try:
            return json.loads(hit)
        except Exception:
            pass
    val = await factory()
    try:
        await r.setex(key, ttl, json.dumps(val, default=str))
    except Exception:
        pass
    return val


async def current_mode() -> str:
    return await get_state("execution_mode", get_config().execution.mode)


async def capital_value() -> float:
    """Effective capital — MUST match what the engine sizes with. In paper mode with
    `paper_compound`, that is the RUNNING balance (base + cumulative realized P&L),
    not the static notional: every derived number on the dashboard (kill-switch line,
    portfolio R limit, margin, sleeve caps, heat) scales off this."""
    cfg = get_config()
    paper = float(getattr(cfg.risk, "paper_capital", 0) or 0)
    if paper > 0:
        if getattr(cfg.risk, "paper_compound", False):
            realized = await fetchrow(
                "SELECT COALESCE(SUM(realized_pnl),0) AS r FROM positions WHERE status='closed'")
            return max(0.0, paper + float(realized["r"] if realized else 0))
        return paper
    row = await fetchrow("SELECT starting_capital FROM daily_pnl WHERE trade_date=$1 AND mode=$2",
                         now_ist().date(), await current_mode())
    return float(row["starting_capital"]) if row and row["starting_capital"] else 0.0


def _daily_pct() -> float:
    cfg = get_config()
    return float(getattr(cfg.risk, "paper_daily_max_loss_pct", 0) or 0) or cfg.risk.daily_max_loss_pct.default


async def _ltp_map(tokens: list[int]) -> dict[int, float]:
    toks = [t for t in tokens if t]
    if not toks:
        return {}
    r = await get_redis()
    vals = await r.hmget("md:ltp", [str(t) for t in toks])
    return {t: float(v) for t, v in zip(toks, vals) if v}


async def _open_positions() -> list[dict]:
    return [dict(r) for r in await fetch("SELECT * FROM positions WHERE status='open' ORDER BY opened_at")]


async def account() -> dict:
    cap = await capital_value()
    pos = await _open_positions()
    deployed = sum(float(p["entry_price"] or 0) * abs(int(p["quantity"] or 0)) for p in pos)
    return {"live_capital": cap, "available_margin": max(0.0, cap - deployed),
            "used_margin": round(deployed, 2),
            "deployed_pct": round(deployed / cap * 100, 2) if cap else 0.0, "mode": await current_mode()}


async def pnl_today() -> dict:
    cap = await capital_value()
    start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
    # Realized = positions CLOSED today (any open date); unrealized = all open.
    rows = await fetch("SELECT status, COALESCE(realized_pnl,0) rp, COALESCE(unrealized_pnl,0) up "
                       "FROM positions WHERE (status='closed' AND closed_at>=$1) OR status='open'", start)
    realized = sum(float(r["rp"]) for r in rows if r["status"] == "closed")
    unrealized = sum(float(r["up"]) for r in rows if r["status"] == "open")
    net = realized + unrealized
    limit = cap * _daily_pct() / 100.0
    # intraday equity curve: cumulative realized stepped at each close + live final point
    closed = await fetch("SELECT closed_at, COALESCE(realized_pnl,0) rp FROM positions "
                         "WHERE status='closed' AND closed_at>=$1 AND closed_at IS NOT NULL ORDER BY closed_at", start)
    curve, cum = [], 0.0
    for c in closed:
        cum += float(c["rp"])
        curve.append({"ts": c["closed_at"].isoformat(), "value": round(cum, 2)})
    curve.append({"ts": now_ist().isoformat(), "value": round(net, 2)})
    return {"realized": round(realized, 2), "unrealized": round(unrealized, 2), "net": round(net, 2),
            "pct_of_capital": round(net / cap * 100, 4) if cap else 0.0,
            "killswitch_limit": round(limit, 2), "killswitch_used": round(max(0.0, -net), 2),
            "equity_curve": curve}


def _fno_underlying_key(name: str) -> str | None:
    for e in (get_config().data.universe or {}).get("fno", []):
        if e.get("name") == name:
            return e.get("underlying")
    return None


async def _spark(token: int | None, n: int = 30) -> list[float]:
    if not token:
        return []
    try:
        df = await load_candles_df(token, "5m", n)
        return [round(float(c), 2) for c in df["close"].tail(n).tolist()] if not df.empty else []
    except Exception:
        return []


async def _structure_greeks(legs: list[dict], name: str) -> dict | None:
    """Best-effort net Greeks for an F&O structure (BS from live leg quotes). None if
    the read-only adapter / data is unavailable."""
    ad = read_adapter()
    ukey = _fno_underlying_key(name)
    if ad is None or not ukey:
        return None
    try:
        from data.options import greeks, implied_vol, year_fraction
        keys = [ukey] + [f"NFO:{leg['tradingsymbol']}" for leg in legs]
        q = await governor().call("quote", ad.quote, keys)
        spot = float(q[ukey]["last_price"])
        net = {"delta": 0.0, "theta": 0.0, "gamma": 0.0, "vega": 0.0}
        for leg in legs:
            inst = await fetchrow("SELECT strike, expiry, instrument_type FROM instruments "
                                  "WHERE instrument_token=$1", leg["instrument_token"])
            d = q.get(f"NFO:{leg['tradingsymbol']}", {})
            ltp = float(d.get("last_price") or 0)
            if not inst or not inst["expiry"] or ltp <= 0:
                return None
            t = year_fraction(inst["expiry"])
            opt = inst["instrument_type"]
            iv = implied_vol(ltp, spot, float(inst["strike"]), t, 0.065, opt)
            g = greeks(spot, float(inst["strike"]), t, 0.065, iv or 0.2, opt)
            sign = 1 if leg["side"] == "BUY" else -1
            qty = abs(int(leg["quantity"] or 0))
            for k in net:
                net[k] += sign * qty * float(g.get(k, 0.0))
        return {k: round(v, 2) for k, v in net.items()}
    except Exception as exc:
        log.warning("structure_greeks_failed", name=name, error=str(exc))
        return None


async def _fno_meta(correlation_id) -> tuple[str, float]:
    """(underlying name, structure net max-loss). Prefer the structure_meta blob
    persisted on the legs — it is the authoritative, restart/migration-safe source
    (also used to rebuild guards on cold start). Fall back to the structure_executed
    audit event for legacy rows whose legs predate structure_meta."""
    name, max_loss = "F&O", 0.0
    row = await fetchrow(
        "SELECT raw->'structure_meta' AS meta FROM positions "
        "WHERE correlation_id=$1 AND raw->'structure_meta' IS NOT NULL LIMIT 1", correlation_id)
    if row and row["meta"]:
        meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"])
        name = meta.get("name") or name
        max_loss = float(meta.get("max_loss_total") or 0)
    if max_loss <= 0:   # fallback: audit trail (orchestrator-executed structures)
        sig = await fetchrow("SELECT tradingsymbol FROM signals WHERE correlation_id=$1 LIMIT 1", correlation_id)
        if sig and name == "F&O":
            name = sig["tradingsymbol"]
        ev = await fetchrow("SELECT payload FROM audit_log WHERE correlation_id=$1 AND event_type='structure_executed' "
                            "ORDER BY ts DESC LIMIT 1", correlation_id)
        if ev and ev["payload"]:
            p = ev["payload"] if isinstance(ev["payload"], dict) else json.loads(ev["payload"])
            max_loss = float(p.get("max_loss") or 0)
    return name, max_loss


async def positions() -> list[dict]:
    pos = await _open_positions()
    lm = await _ltp_map([p["instrument_token"] for p in pos])
    out: list[dict] = []
    fno_groups: dict[str, list[dict]] = defaultdict(list)
    for p in pos:
        if p["sleeve"] == "fno":
            fno_groups[str(p["correlation_id"])].append(p)
    handled: set[str] = set()
    for p in pos:
        if p["sleeve"] == "fno":
            cid = str(p["correlation_id"])
            if cid in handled:
                continue
            handled.add(cid)
            legs = fno_groups[cid]
            name, net_max_loss = await _fno_meta(p["correlation_id"])
            unreal = round(sum(float(leg["unrealized_pnl"] or 0) for leg in legs), 2)
            out.append({
                "id": cid, "instrument": name, "sleeve": "fno", "side": "STRUCTURE",
                "qty": sum(abs(int(leg["quantity"] or 0)) for leg in legs),
                "entry": 0.0, "ltp": 0.0, "stop": 0.0, "target": 0.0,
                "R_at_risk": round(net_max_loss, 2),
                "R_multiple": round(unreal / net_max_loss, 2) if net_max_loss else 0.0,
                "unrealized": unreal,
                "mae": round(sum(float(leg["mae"] or 0) for leg in legs), 2),
                "mfe": round(sum(float(leg["mfe"] or 0) for leg in legs), 2),
                "opened_at": legs[0]["opened_at"].isoformat() if legs and legs[0]["opened_at"] else None,
                "spark": [],
                "structure": {
                    "net_max_loss": round(net_max_loss, 2),
                    "greeks": await _structure_greeks(legs, name),
                    "legs": [{"instrument": leg["tradingsymbol"], "side": leg["side"],
                              "qty": int(leg["quantity"] or 0), "entry": float(leg["entry_price"] or 0),
                              "ltp": lm.get(leg["instrument_token"], float(leg["entry_price"] or 0))}
                             for leg in legs],
                },
                "state": "open",
            })
        else:
            tok = p["instrument_token"]
            r_risk, unreal = float(p["r_rupees"] or 0), float(p["unrealized_pnl"] or 0)
            out.append({"id": p["id"], "instrument": p["tradingsymbol"], "sleeve": p["sleeve"],
                        "side": p["side"], "qty": int(p["quantity"] or 0), "entry": float(p["entry_price"] or 0),
                        "ltp": lm.get(tok, float(p["entry_price"] or 0)), "stop": float(p["stop_price"] or 0),
                        "target": float(p["target_price"] or 0), "R_at_risk": r_risk,
                        "R_multiple": round(unreal / r_risk, 2) if r_risk else 0.0,
                        "unrealized": unreal, "mae": float(p["mae"] or 0), "mfe": float(p["mfe"] or 0),
                        "opened_at": p["opened_at"].isoformat() if p["opened_at"] else None,
                        "spark": await _spark(tok), "state": p["status"]})
    return out


async def sleeves() -> list[dict]:
    cfg = get_config()
    cap = await capital_value()
    start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
    pos = await _open_positions()
    today = [dict(r) for r in await fetch(
        "SELECT sleeve, status, COALESCE(realized_pnl,0) rp, COALESCE(unrealized_pnl,0) up "
        "FROM positions WHERE opened_at>=$1", start)]
    # TRADE-level history: a structure's legs share one correlation_id and count as
    # ONE win/loss on combined P&L (legs counted W21/L41 where the truth was W13/L18).
    closed_all = defaultdict(list)
    for c in await fetch(
            "SELECT sleeve, SUM(COALESCE(realized_pnl,0)) AS rp, SUM(r_rupees) AS r_rupees, "
            "MAX(closed_at) AS closed_at FROM positions WHERE status='closed' "
            "GROUP BY sleeve, COALESCE(correlation_id::text, id::text) ORDER BY MAX(closed_at)"):
        closed_all[c["sleeve"]].append(c)
    out = []
    for name, sc in cfg.sleeves.sleeves.items():
        spos = [p for p in pos if p["sleeve"] == name]
        deployed = sum(float(p["entry_price"] or 0) * abs(int(p["quantity"] or 0)) for p in spos)
        cap_rupees = sc.cap_pct / 100.0 * cap
        day_pnl = sum(float(r["rp"] if r["status"] == "closed" else r["up"]) for r in today if r["sleeve"] == name)
        enabled = await get_state(f"sleeve_{name}_enabled", sc.enabled)
        sclosed = closed_all.get(name, [])
        wins = sum(1 for c in sclosed if float(c["rp"]) > 0)
        losses = sum(1 for c in sclosed if float(c["rp"]) < 0)
        rmults = [float(c["rp"]) / float(c["r_rupees"]) for c in sclosed if c["r_rupees"] and float(c["r_rupees"]) > 0]
        curve, cum = [], 0.0
        for c in sclosed:
            cum += float(c["rp"])
            curve.append({"ts": c["closed_at"].isoformat() if c["closed_at"] else None, "value": round(cum, 2)})
        cum_pnl = cum + sum(float(p["unrealized_pnl"] or 0) for p in spos)
        n_open_trades = len({str(p["correlation_id"]) if p["correlation_id"] else f"id{p['id']}" for p in spos})
        out.append({"sleeve": name, "cap_pct": sc.cap_pct, "deployed": round(deployed, 2),
                    "margin_headroom": round(max(0.0, cap_rupees - deployed), 2),
                    "day_pnl": round(day_pnl, 2), "cum_pnl": round(cum_pnl, 2), "curve": curve,
                    "wins": wins, "losses": losses, "avg_R": round(sum(rmults) / len(rmults), 2) if rmults else 0.0,
                    "enabled": bool(enabled), "positions": n_open_trades})
    return out


async def _correlation_matrix(pos: list[dict], lookback: int = 120) -> dict:
    import pandas as pd
    toks = {}
    for p in pos:
        if p["instrument_token"] and p["instrument_token"] not in toks:
            toks[p["instrument_token"]] = p["tradingsymbol"]
    series = {}
    for t, sym in toks.items():
        try:
            df = await load_candles_df(t, "day", lookback)
            if not df.empty and len(df) > 5:
                series[sym] = df["close"].pct_change().dropna()
        except Exception:
            pass
    if len(series) < 2:
        return {"instruments": list(series.keys()), "matrix": []}
    corr = pd.DataFrame(series).dropna().corr()
    syms = list(corr.columns)
    return {"instruments": syms, "matrix": [[round(float(corr.loc[a, b]), 2) for b in syms] for a in syms]}


async def risk() -> dict:
    cfg = get_config()
    cap = await capital_value()
    pos = await _open_positions()
    paper = float(getattr(cfg.risk, "paper_capital", 0) or 0)
    eff_pt = (float(getattr(cfg.risk, "paper_per_trade_pct", 0) or 0) if paper > 0 else 0) or None
    snap = await compute_heat(cfg, pos, cap, per_trade_pct=eff_pt)
    deployed = sum(float(p["entry_price"] or 0) * abs(int(p["quantity"] or 0)) for p in pos)
    by_sleeve_exp: dict = defaultdict(float)
    by_side = {"long": 0.0, "short": 0.0}
    for p in pos:
        notional = float(p["entry_price"] or 0) * abs(int(p["quantity"] or 0))
        by_sleeve_exp[p["sleeve"]] += notional
        by_side["long" if p["side"] == "BUY" else "short"] += notional
    pnl = await pnl_today()
    dd, peak = [], 0.0
    for pt in pnl.get("equity_curve", []):
        peak = max(peak, pt["value"])
        dd.append({"ts": pt["ts"], "value": round(pt["value"] - peak, 2)})
    ksh = [{"date": str(r["trade_date"]),
            "day_pnl": round(float(r["realized_pnl"] or 0) + float(r["unrealized_pnl"] or 0), 2),
            "limit": float(r["max_loss_limit"] or 0)}
           for r in await fetch("SELECT trade_date, realized_pnl, unrealized_pnl, max_loss_limit FROM daily_pnl "
                                "WHERE kill_switch_tripped = true ORDER BY trade_date DESC LIMIT 30")]
    return {"open_R": round(snap.total_open_r, 2), "portfolio_limit_R": round(snap.portfolio_risk_limit_r, 2),
            "max_positions": snap.max_concurrent_positions, "num_positions": snap.num_open_positions,
            "heat_pct": round(snap.heat_pct, 2), "heat": snap.correlated_clusters,
            "clusters": snap.correlated_clusters, "correlation_matrix": await _correlation_matrix(pos),
            "by_sleeve": snap.by_sleeve,
            "exposure": {"by_sleeve": {k: round(v, 2) for k, v in by_sleeve_exp.items()},
                         "by_side": {k: round(v, 2) for k, v in by_side.items()}, "by_sector": {}},
            "margin": {"used": round(deployed, 2), "available": round(max(0.0, cap - deployed), 2), "timeline": []},
            "leverage_x": round(deployed / cap, 2) if cap else 0.0,
            "drawdown_curve": dd, "killswitch_history": ksh}


async def signals(limit: int = 50, flt: str | None = None) -> list[dict]:
    where, args = "", []
    if flt in ("PASS", "REJECT"):
        where, args = "WHERE decision=$1", [flt]
    rows = await fetch(f"SELECT * FROM signals {where} ORDER BY ts DESC LIMIT {int(limit)}", *args)
    # Batch the gate trail for all signals in ONE query (was N+1: one per signal).
    ids = [s["id"] for s in rows]
    gates_by_sig: dict = defaultdict(list)
    if ids:
        for g in await fetch("SELECT signal_id, gate_name, passed, score FROM gate_results "
                             "WHERE signal_id = ANY($1::bigint[]) ORDER BY id", ids):
            gates_by_sig[g["signal_id"]].append(g)
    out = []
    for s in rows:
        glist = [{"name": g["gate_name"], "pass": g["passed"], "score": float(g["score"] or 0)}
                 for g in gates_by_sig.get(s["id"], [])]
        raw = s["raw"] if isinstance(s["raw"], dict) else (json.loads(s["raw"]) if s["raw"] else {})
        out.append({"id": s["id"], "correlation_id": str(s["correlation_id"]),
                    "ts": s["ts"].isoformat() if s["ts"] else None, "instrument": s["tradingsymbol"],
                    "sleeve": s["sleeve"], "setup": s["setup"], "gates": glist,
                    "confidence": float(s["confidence"] or 0), "decision": s["decision"], "action": s["decision"],
                    "reject_gate": next((g["name"] for g in glist if not g["pass"]), None),
                    "reason": s["reason"], "llm": raw.get("llm")})
    return out


async def audit(limit: int = 100, offset: int = 0, correlation_id: str | None = None,
                event_type: str | None = None) -> list[dict]:
    clauses, args = [], []
    if correlation_id:
        args.append(correlation_id); clauses.append(f"correlation_id=${len(args)}::uuid")
    if event_type:
        args.append(event_type); clauses.append(f"event_type=${len(args)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await fetch(f"SELECT ts, correlation_id, event_type, component, message, payload FROM audit_log "
                       f"{where} ORDER BY ts DESC LIMIT {int(limit)} OFFSET {int(offset)}", *args)
    return [{"ts": r["ts"].isoformat(), "correlation_id": str(r["correlation_id"]) if r["correlation_id"] else None,
             "event_type": r["event_type"], "component": r["component"], "message": r["message"],
             "payload": r["payload"] if isinstance(r["payload"], dict) else (json.loads(r["payload"]) if r["payload"] else {})}
            for r in rows]


async def reconstruct(correlation_id: str) -> dict:
    """Full causal chain for one trade: signal + gate trail + audit events + positions."""
    sig = await fetchrow("SELECT * FROM signals WHERE correlation_id=$1::uuid LIMIT 1", correlation_id)
    gates = await fetch("SELECT gate_name, passed, score, detail FROM gate_results "
                        "WHERE correlation_id=$1::uuid ORDER BY id", correlation_id)
    events = await audit(limit=500, correlation_id=correlation_id)
    pos = await fetch("SELECT id, tradingsymbol, side, quantity, entry_price, status, realized_pnl, unrealized_pnl "
                      "FROM positions WHERE correlation_id=$1::uuid ORDER BY id", correlation_id)
    return {
        "correlation_id": correlation_id,
        "signal": ({"sleeve": sig["sleeve"], "instrument": sig["tradingsymbol"], "setup": sig["setup"],
                    "side": sig["side"], "decision": sig["decision"], "confidence": float(sig["confidence"] or 0),
                    "reason": sig["reason"]} if sig else None),
        "gates": [{"name": g["gate_name"], "pass": g["passed"], "score": float(g["score"] or 0),
                   "detail": g["detail"] if isinstance(g["detail"], dict) else (json.loads(g["detail"]) if g["detail"] else {})}
                  for g in gates],
        "events": list(reversed(events)),  # chronological
        "positions": [{"id": p["id"], "instrument": p["tradingsymbol"], "side": p["side"],
                       "qty": int(p["quantity"] or 0), "entry": float(p["entry_price"] or 0), "status": p["status"],
                       "realized": float(p["realized_pnl"] or 0), "unrealized": float(p["unrealized_pnl"] or 0)}
                      for p in pos],
    }


async def config_view() -> dict:
    cfg = get_config()
    return {"risk": cfg.risk.model_dump(), "strategy_params": cfg.strategy.model_dump(),
            "system": {"llm_provider": (cfg.system.llm or {}).get("provider", "none"),
                       "paper_capital": cfg.risk.paper_capital},
            "bounds": {"per_trade_risk_pct": cfg.risk.per_trade_risk_pct.model_dump(),
                       "daily_max_loss_pct": cfg.risk.daily_max_loss_pct.model_dump(),
                       "editable": {"risk.paper_per_trade_pct": [0.25, 2.0],
                                    "risk.paper_daily_max_loss_pct": [1.0, 6.0]}}}


async def health() -> dict:
    r = await get_redis()
    cfg = get_config()
    hb = await r.get("aegis:engine:heartbeat")
    feed_last = await r.get("aegis:feed:last_tick")
    market = (cfg.data.feed or {}).get("market_window", ["09:15", "15:30"])
    session = "OPEN" if is_within(market[0], market[1]) else "CLOSED"
    if await get_state("engine_halted", False):
        session = "HALTED"
    token_ok = read_adapter() is not None
    nowi = now_ist()
    expiry = nowi.replace(hour=6, minute=0, second=0, microsecond=0)
    if nowi.hour >= 6:
        expiry = expiry + timedelta(days=1)
    er = await fetchrow("SELECT count(*) FILTER (WHERE event_type ILIKE '%error%' OR event_type ILIKE '%fail%') e, "
                        "count(*) t FROM audit_log WHERE ts > now() - interval '1 hour'")
    total, errs = int(er["t"] or 0), int(er["e"] or 0)
    # Age-aware feed health: fresh ticks => ok; quiet during a session => stale;
    # quiet while the market is closed => idle (expected, not an alert).
    feed_status = "unknown"
    if feed_last:
        try:
            age = (nowi - datetime.fromisoformat(feed_last)).total_seconds()
            feed_status = ("ok" if age < 15 else "stale") if session == "OPEN" else "idle"
        except Exception:
            feed_status = "ok"
    return {"feed": feed_status, "feed_last_tick": feed_last,
            "token": "ok" if token_ok else "stale",
            "token_expiry": expiry.isoformat() if token_ok else None,
            "last_reconcile": await r.get("aegis:feed:last_reconcile"),
            "rate_limit_headroom": None, "loop_heartbeat": hb, "session_state": session,
            "error_rate": round(errs / total, 4) if total else 0.0,
            "mode": await current_mode(), "paused": bool(await get_state("engine_paused", False)),
            "kill_switch_active": bool(await get_state("kill_switch_active", False)),
            "dd_circuit_active": bool(await get_state("dd_circuit_active", False))}


async def prelive_checklist() -> dict:
    keys = ["compliance_tagging", "failsafe_rehearsed", "reconcile_clean", "alerts_confirmed"]
    return {k: bool(await get_state(f"prelive_{k}", False)) for k in keys}


async def layouts_get() -> list[dict]:
    rows = await fetch("SELECT name, layout, updated_at FROM dashboard_layouts ORDER BY name")
    return [{"name": r["name"],
             "layout": r["layout"] if isinstance(r["layout"], dict) else json.loads(r["layout"]),
             "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None} for r in rows]


async def layouts_put(name: str, layout: dict) -> dict:
    from common.db import execute
    await execute("INSERT INTO dashboard_layouts (name, layout) VALUES ($1, $2::jsonb) "
                  "ON CONFLICT (name) DO UPDATE SET layout=$2::jsonb, updated_at=now()", name, json.dumps(layout))
    return {"ok": True, "name": name}
