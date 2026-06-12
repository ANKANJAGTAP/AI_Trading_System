"""Performance analytics + rejection analytics (Phase 6b). Computed ONLY from real
executed/simulated trades (positions) and real gate results — never fabricated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from common.db import fetch
from common.market_time import now_ist
from common.state import get_state
from config.loader import get_config


def _period_cutoff(period: str):
    now = now_ist()
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period.endswith("d") and period[:-1].isdigit():
        return now - timedelta(days=int(period[:-1]))
    return now - timedelta(days=3650)  # "all"


async def analytics(period: str = "all") -> dict:
    cutoff = _period_cutoff(period)
    # TRADE-level rows: a structure's legs share one correlation_id and aggregate to
    # ONE trade (combined P&L, combined risk, opened at first leg, closed at last).
    # Leg-level counting inflated trades (67 vs 36), understated win rate, and the
    # equity curve sawtoothed inside each structure (one leg +X then its hedge -Y),
    # fabricating drawdown that never existed at the account level. Only FULLY
    # closed trades count, attributed to the period their LAST leg closed in.
    rows = await fetch(
        "SELECT SUM(p.realized_pnl) AS rp, SUM(p.r_rupees) AS r_rupees, "
        "       MIN(p.opened_at) AS opened_at, MAX(p.closed_at) AS closed_at, "
        "       MAX(p.sleeve) AS sleeve, "
        "       CASE WHEN COUNT(*) > 1 THEN 'STRUCT' ELSE MAX(p.side) END AS side, "
        "       COALESCE(MAX(p.raw->'structure_meta'->>'name'), "
        "                CASE WHEN COUNT(*) > 1 THEN regexp_replace(MIN(p.tradingsymbol), '[0-9].*$', '') "
        "                     ELSE MIN(p.tradingsymbol) END) AS tradingsymbol, "
        "       MAX(s.setup) AS setup "
        "FROM positions p LEFT JOIN signals s ON s.correlation_id = p.correlation_id "
        "GROUP BY COALESCE(p.correlation_id::text, p.id::text) "
        "HAVING COUNT(*) FILTER (WHERE p.status <> 'closed') = 0 "
        "   AND MAX(p.closed_at) >= $1 "
        "ORDER BY MAX(p.closed_at)", cutoff)
    dataset = await get_state("execution_mode", get_config().execution.mode)
    dataset = "live" if dataset == "live" else "sim"

    rps = [float(r["rp"] or 0) for r in rows]
    rmults = [float(r["rp"]) / float(r["r_rupees"]) for r in rows if r["r_rupees"] and float(r["r_rupees"]) > 0]
    wins = [x for x in rps if x > 0]
    losses = [x for x in rps if x < 0]
    gross_w, gross_l = sum(wins), abs(sum(losses))
    win_rms = [m for m in rmults if m > 0]
    loss_rms = [m for m in rmults if m < 0]

    # equity + drawdown curves
    equity, dd, cum, peak = [], [], 0.0, 0.0
    for r in rows:
        cum += float(r["rp"] or 0)
        ts = r["closed_at"].isoformat() if r["closed_at"] else None
        equity.append({"ts": ts, "value": round(cum, 2)})
        peak = max(peak, cum)
        dd.append({"ts": ts, "value": round(cum - peak, 2)})
    max_dd = round(min((p["value"] for p in dd), default=0.0), 2)

    import statistics as st
    sharpe = round(st.mean(rmults) / st.pstdev(rmults), 2) if len(rmults) > 1 and st.pstdev(rmults) else 0.0

    def _grp(keyfn):
        g = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
        for r in rows:
            k = keyfn(r) or "?"
            g[k]["pnl"] += float(r["rp"] or 0)
            g[k]["trades"] += 1
            g[k]["wins"] += 1 if float(r["rp"] or 0) > 0 else 0
        return [{"key": k, "pnl": round(v["pnl"], 2), "trades": v["trades"], "wins": v["wins"]} for k, v in g.items()]

    # R-multiple histogram (buckets) + hold-time histogram (minutes)
    r_hist = defaultdict(int)
    for m in rmults:
        b = max(-3, min(3, round(m)))
        r_hist[b] += 1
    ht_hist = defaultdict(int)
    for r in rows:
        if r["opened_at"] and r["closed_at"]:
            mins = (r["closed_at"] - r["opened_at"]).total_seconds() / 60.0
            bucket = "<15m" if mins < 15 else "<1h" if mins < 60 else "<1d" if mins < 1440 else ">=1d"
            ht_hist[bucket] += 1
    hour_hm = defaultdict(float)
    wday_hm = defaultdict(float)
    for r in rows:
        if r["closed_at"]:
            c = r["closed_at"].astimezone(now_ist().tzinfo)
            hour_hm[c.hour] += float(r["rp"] or 0)
            wday_hm[c.strftime("%a")] += float(r["rp"] or 0)

    return {
        "period": period, "dataset": dataset,
        "equity_curve": equity, "drawdown_curve": dd,
        "kpis": {
            "trades": len(rows),
            "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0.0,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l else (gross_w and 999.0 or 0.0),
            "expectancy_R": round(sum(rmults) / len(rmults), 3) if rmults else 0.0,
            "avg_win_R": round(sum(win_rms) / len(win_rms), 2) if win_rms else 0.0,
            "avg_loss_R": round(sum(loss_rms) / len(loss_rms), 2) if loss_rms else 0.0,
            "max_dd": max_dd, "sharpe": sharpe,
            "largest_win": round(max(wins), 2) if wins else 0.0,
            "largest_loss": round(min(losses), 2) if losses else 0.0,
        },
        "by_sleeve": _grp(lambda r: r["sleeve"]),
        "by_setup": _grp(lambda r: r["setup"]),
        "by_instrument": _grp(lambda r: r["tradingsymbol"]),
        "by_side": _grp(lambda r: r["side"]),
        "r_histogram": [{"bucket": k, "count": v} for k, v in sorted(r_hist.items())],
        "holdtime_histogram": [{"bucket": k, "count": v} for k, v in ht_hist.items()],
        "hour_heatmap": [{"hour": k, "pnl": round(v, 2)} for k, v in sorted(hour_hm.items())],
        "weekday_heatmap": [{"day": k, "pnl": round(v, 2)} for k, v in wday_hm.items()],
    }


async def rejections(window_hours: int = 24) -> dict:
    by_gate = await fetch(
        "SELECT gate_name, count(*) c FROM gate_results WHERE passed = false "
        "AND ts > now() - make_interval(hours => $1) GROUP BY gate_name ORDER BY c DESC", window_hours)
    by_reason = await fetch(
        "SELECT reason, count(*) c FROM signals WHERE decision='REJECT' AND reason IS NOT NULL "
        "AND ts > now() - make_interval(hours => $1) GROUP BY reason ORDER BY c DESC LIMIT 20", window_hours)
    near = await fetch(
        "SELECT s.tradingsymbol, s.sleeve, s.reason, "
        "count(*) FILTER (WHERE g.passed) AS passed_gates, count(*) AS total_gates "
        "FROM signals s JOIN gate_results g ON g.signal_id = s.id "
        "WHERE s.decision='REJECT' AND s.ts > now() - make_interval(hours => $1) "
        "GROUP BY s.id, s.tradingsymbol, s.sleeve, s.reason "
        "ORDER BY passed_gates DESC LIMIT 10", window_hours)
    return {
        "window_hours": window_hours,
        "by_gate": [{"gate": r["gate_name"], "count": int(r["c"])} for r in by_gate],
        "by_reason": [{"reason": r["reason"], "count": int(r["c"])} for r in by_reason],
        "near_misses": [{"instrument": r["tradingsymbol"], "sleeve": r["sleeve"], "reason": r["reason"],
                         "passed_gates": int(r["passed_gates"]), "total_gates": int(r["total_gates"])} for r in near],
    }
