"""Edge-decay tracking (Tier-3 process alpha).

Edges decay as markets adapt — the only defense is measuring yours on a schedule.
This module builds a weekly report: per-sleeve per-week trade-level expectancy and
win rate (is the edge stable, improving, or bleeding away?) plus the current
feature-discrimination snapshot (which gates still separate winners from losers).

Consumed by scripts/edge_report.py (CLI) and the engine's Friday-evening email job.
"""
from __future__ import annotations

from common.db import fetch
from research.dataset import build_dataset
from research.discrimination import discriminate


async def weekly_sleeve_stats(weeks: int = 8) -> list[dict]:
    """Per (ISO week, sleeve): trades (correlation-grouped), win rate, expectancy in R
    (only trades with recorded risk), and net P&L. Newest week first. Inner query
    aggregates legs into trades; outer query aggregates trades into weekly buckets."""
    rows = await fetch(
        "SELECT wk, sleeve, COUNT(*) AS trades, "
        "       SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins, "
        "       ROUND(SUM(pnl)::numeric, 0) AS net_pnl, "
        "       ROUND(AVG(CASE WHEN rr > 0 THEN pnl / rr END)::numeric, 3) AS expectancy_r "
        "FROM ("
        "  SELECT to_char(date_trunc('week', MAX(closed_at) AT TIME ZONE 'Asia/Kolkata'), 'IYYY-\"W\"IW') AS wk, "
        "         sleeve, SUM(realized_pnl) AS pnl, SUM(r_rupees) AS rr "
        "  FROM positions WHERE status='closed' AND closed_at IS NOT NULL "
        "  GROUP BY sleeve, COALESCE(correlation_id::text, id::text)"
        ") t GROUP BY wk, sleeve ORDER BY wk DESC, sleeve LIMIT $1", weeks * 6)
    return [dict(r) for r in rows]


async def build_edge_report(weeks: int = 8) -> str:
    """Plain-text edge report: weekly expectancy trend per sleeve + which features
    still discriminate. The question it answers: is the edge still there?"""
    lines = ["================ EDGE-DECAY REPORT ================"]
    stats = await weekly_sleeve_stats(weeks)
    if not stats:
        lines.append("No closed trades yet — nothing to measure.")
    else:
        lines.append(f"{'week':10} {'sleeve':18} {'trades':>6} {'win%':>6} {'expR':>7} {'netP&L':>12}")
        lines.append("-" * 64)
        for r in stats:
            wr = (int(r["wins"]) / int(r["trades"]) * 100) if r["trades"] else 0.0
            exp = r["expectancy_r"]
            lines.append(f"{r['wk']:10} {(r['sleeve'] or '?'):18} {int(r['trades']):>6} "
                         f"{wr:>5.0f}% {(f'{float(exp):+.2f}' if exp is not None else '   n/a'):>7} "
                         f"Rs {float(r['net_pnl']):>+9,.0f}")
        lines.append("-" * 64)
        lines.append("Read: expectancy (R/trade) should be stable-positive. A sleeve that")
        lines.append("decays week over week is an edge being arbitraged away — shrink or stop it.")

    samples = await build_dataset()
    lines.append("")
    lines.append(f"FEATURE DISCRIMINATION ({len(samples)} labelled trades)")
    if len(samples) >= 20:
        disc = discriminate(samples)
        lines.append(f"base win rate: {disc['base_rate']*100:.0f}%   top separators (|lift| = win% high-half vs low-half):")
        for f in (disc.get("features") or [])[:8]:
            if f.get("win_rate_high") is None:
                continue
            lines.append(f"  {f['feature']:<24} high {f['win_rate_high']*100:>3.0f}% vs low {f['win_rate_low']*100:>3.0f}%  "
                         f"lift {f['lift']*100:+.0f}pp (n {f['n_high']}/{f['n_low']})")
        lines.append("Features whose lift trends to ~0 are dead weight — candidates for removal,")
        lines.append("not for re-weighting. Don't add new ones without walk-forward proof.")
    else:
        lines.append(f"needs >= 20 labelled trades for a meaningful split (have {len(samples)}).")
    lines.append("===================================================")
    return "\n".join(lines)
