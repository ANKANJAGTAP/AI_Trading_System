"""Daily operations journal — the system's black-box recorder.

Every evening the engine writes a full record of its day: balance and per-trade
results, ANOMALIES (the bug signatures: losses that overran their planned risk,
structure exits beyond defined max loss, kill-switch/brake trips), gate rejection
patterns, and the ML learning status. Stored in `daily_journal` (backed up nightly)
and emailed — so each periodic review starts from evidence, not memory.
"""
from __future__ import annotations

import json

from common.db import execute, fetch, fetchrow, fetchval
from common.market_time import now_ist
from config.loader import get_config


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


async def _trades_today(day_start) -> list[dict]:
    rows = await fetch(
        "SELECT MIN(p.id) AS id, COUNT(*) AS legs, "
        "       CASE WHEN COUNT(*) > 1 THEN COALESCE(MAX(p.raw->'structure_meta'->>'stype'), 'STRUCT') "
        "            ELSE MAX(p.tradingsymbol) END AS inst, "
        "       MAX(p.sleeve) AS sleeve, SUM(p.realized_pnl) AS pnl, SUM(p.r_rupees) AS rr, "
        "       MAX((p.raw->'structure_meta'->>'max_loss_total')::numeric) AS max_loss, "
        "       string_agg(DISTINCT p.raw->>'exit_reason', ',') AS reasons, "
        "       to_char(MAX(p.closed_at) AT TIME ZONE 'Asia/Kolkata', 'HH24:MI') AS closed "
        "FROM positions p WHERE p.status='closed' AND p.closed_at >= $1 "
        "GROUP BY COALESCE(p.correlation_id::text, p.id::text) ORDER BY MAX(p.closed_at)", day_start)
    return [dict(r) for r in rows]


async def build_daily_journal() -> str:
    today = now_ist().date()
    day_start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
    L: list[str] = [f"# Daily Journal — {today} (generated {now_ist().strftime('%H:%M IST')})", ""]

    # ---- capital & day result ------------------------------------------------
    cfg = get_config()
    base_capital = float(getattr(cfg.risk, "paper_capital", 0) or 1000000)
    balance = float(await fetchval(
        "SELECT $1::numeric + COALESCE(SUM(realized_pnl),0) FROM positions WHERE status='closed'",
        base_capital) or 0)
    realized = float(await fetchval(
        "SELECT COALESCE(SUM(realized_pnl),0) FROM positions WHERE status='closed' AND closed_at >= $1",
        day_start) or 0)
    open_rows = await fetch("SELECT tradingsymbol, side, quantity, COALESCE(unrealized_pnl,0) up "
                            "FROM positions WHERE status='open'")
    L += [f"## Capital",
          f"- Running balance: Rs {balance:,.2f}  | day realized: Rs {realized:+,.0f}",
          f"- Open positions overnight: {len(open_rows)}"
          + (": " + ", ".join(f"{r['tradingsymbol']} {r['side']} {r['quantity']} (uPnL {float(r['up']):+,.0f})"
                              for r in open_rows) if open_rows else ""), ""]

    # ---- trades --------------------------------------------------------------
    trades = await _trades_today(day_start)
    L.append(f"## Trades ({len(trades)})")
    if not trades:
        L.append("- none")
    for t in trades:
        L.append(f"- #{t['id']} {t['inst']} [{t['sleeve']}] legs={t['legs']} "
                 f"pnl Rs {float(t['pnl']):+,.0f} (risk Rs {float(t['rr'] or 0):,.0f}) "
                 f"exit={t['reasons']} @{t['closed']}")
    L.append("")

    # ---- ANOMALIES: the bug signatures ----------------------------------------
    # Every entry here is "should be impossible" — exactly what a review must read.
    anomalies: list[str] = []
    for t in trades:
        pnl, rr = float(t["pnl"] or 0), float(t["rr"] or 0)
        ml = float(t["max_loss"] or 0)
        if rr > 0 and pnl < -(rr * 1.3):
            anomalies.append(f"STOP-OVERRUN: trade #{t['id']} {t['inst']} lost Rs {pnl:+,.0f} "
                             f"vs planned risk Rs {rr:,.0f} ({abs(pnl)/rr:.1f}x) — "
                             "check fills/marks (Jun-12 class)")
        if ml > 0 and pnl < -(ml * 1.2):
            anomalies.append(f"BEYOND-MAX-LOSS: structure #{t['id']} lost Rs {pnl:+,.0f} "
                             f"vs DEFINED max Rs {ml:,.0f} — defined risk must be a ceiling")
    ks = await fetchrow(
        "SELECT BOOL_OR(kill_switch_tripped) AS kill_switch_tripped, "
        "       MAX(ABS(max_loss_limit)) AS max_loss_limit "
        "FROM daily_pnl WHERE trade_date=$1", today)
    if ks and ks["kill_switch_tripped"]:
        anomalies.append(f"KILL-SWITCH TRIPPED (limit Rs {float(ks['max_loss_limit']):,.0f}) — "
                         "needs review + manual reset before next session")
    for key, label in (("period_brake_active", "PERIOD BRAKE"), ("trade_budget_exhausted", "TRADE BUDGET"),
                       ("dd_circuit_active", "DD CIRCUIT")):
        row = await fetchrow("SELECT value FROM config_state WHERE key=$1", key)
        val = _json_value(row["value"]) if row else None
        if val:
            anomalies.append(f"{label} active: {val}")
    for s in ("intraday_stocks", "fno", "swing_stocks", "mcx_commodities"):
        row = await fetchrow("SELECT value FROM config_state WHERE key=$1", f"sleeve_{s}_review_required")
        if row and _json_value(row["value"]) is True:
            anomalies.append(f"KILL CRITERIA: sleeve {s} disabled pending human review")
    L.append(f"## Anomalies ({len(anomalies)})" if anomalies else "## Anomalies (0) — clean day")
    L += [f"- ⚠ {a}" for a in anomalies] + [""]

    # ---- decision funnel (what got rejected and why) ---------------------------
    rej = await fetch("SELECT sleeve, COALESCE(reason,'?') reason, count(*) c FROM signals "
                      "WHERE decision='REJECT' AND ts >= $1 GROUP BY sleeve, reason "
                      "ORDER BY c DESC LIMIT 8", day_start)
    n_pass = await fetchval("SELECT count(*) FROM signals WHERE decision='PASS' AND ts >= $1", day_start)
    L.append(f"## Decision funnel — PASS {n_pass}, top rejections:")
    L += [f"- {r['sleeve']}: {r['reason'][:70]} x{r['c']}" for r in rej] or ["- none"]
    L.append("")

    # ---- ML learning status ----------------------------------------------------
    n_lessons = await fetchval(
        "SELECT count(*) FROM (SELECT 1 FROM signals s JOIN positions p ON p.correlation_id=s.correlation_id "
        "WHERE s.decision='PASS' GROUP BY s.id HAVING COUNT(*) FILTER (WHERE p.status<>'closed') = 0) t") or 0
    model = await fetchrow("SELECT name, metrics, active, created_at FROM meta_models "
                           "ORDER BY created_at DESC LIMIT 1")
    L.append("## Learning")
    L.append(f"- Labeled trades in dataset: {n_lessons} (training begins at 80)")
    if model:
        m = _json_value(model["metrics"])
        L.append(f"- Latest model: {model['name']} active={model['active']} metrics={m}")
    else:
        L.append("- No model trained yet (expected until ~80 trades) — deterministic rules carry the book")
    L.append("")
    return "\n".join(L)


async def save_and_send(alerter=None) -> str:
    content = await build_daily_journal()
    await execute(
        "INSERT INTO daily_journal (day, content) VALUES ($1, $2) "
        "ON CONFLICT (day) DO UPDATE SET content = EXCLUDED.content, created_at = now()",
        now_ist().date(), content)
    if alerter:
        await alerter.send_async(f"Daily journal {now_ist().date()}", content)
    return content
