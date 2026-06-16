"""Daily health digest — a morning snapshot emailed to the operator so the live
system can be monitored without logging in: mode, kill-switch, feed/heartbeat,
lake growth, open positions, day P&L, and go-live readiness.

Mirrors the research/journal + edge-report pattern (gather -> format -> email).
Everything is best-effort; a single failing probe never breaks the digest.
"""
from __future__ import annotations

from common.db import fetch, fetchrow
from common.logging import get_logger
from common.market_time import now_ist
from common.state import get_state

log = get_logger("health_digest")


def format_digest(s: dict) -> str:
    """Pure: render a gathered-stats dict as the digest text."""
    lines = [
        f"AEGIS daily health — {s.get('date')}",
        "=" * 44,
        f"Mode             : {s.get('mode', '?')}",
        f"Kill-switch      : {'ACTIVE' if s.get('kill_switch') else 'clear'}",
        f"New entries      : {'BLOCKED' if s.get('block_new_entries') else 'allowed'}",
        f"Engine heartbeat : {s.get('heartbeat') or 'none'}",
        f"Feed last tick   : {s.get('feed_last') or 'none'}",
        "",
        f"Lake (eod_fno)   : {s.get('lake_rows', 0):,} rows / {s.get('lake_days', 0)} trading days",
        f"Open positions   : {s.get('open_positions', 0)}",
        f"Day P&L          : Rs {s.get('day_pnl', 0.0):,.0f} "
        f"(realized {s.get('realized', 0.0):,.0f} + unrealized {s.get('unrealized', 0.0):,.0f})",
        "",
        f"Go-live ready    : {s.get('prelive_overall', 'n/a')}",
    ]
    failed = s.get("prelive_failed") or []
    if failed:
        lines.append(f"  blocking       : {', '.join(failed)}")
    return "\n".join(lines)


async def gather_stats() -> dict:
    s: dict = {"date": str(now_ist().date())}
    try:
        from common.runtime_mode import load_runtime_mode
        s["mode"] = (await load_runtime_mode()).mode
    except Exception:
        s["mode"] = "?"
    s["kill_switch"] = bool(await get_state("kill_switch_active", False))
    s["block_new_entries"] = bool(await get_state("block_new_entries", False))
    try:
        from common.redis_client import get_redis
        r = await get_redis()
        s["heartbeat"] = await r.get("aegis:engine:heartbeat")
        s["feed_last"] = await r.get("aegis:feed:last_tick")
    except Exception:
        pass
    try:
        row = await fetchrow("SELECT count(*) c, count(distinct trade_date) d FROM eod_fno")
        s["lake_rows"], s["lake_days"] = int(row["c"] or 0), int(row["d"] or 0)
    except Exception:
        s["lake_rows"], s["lake_days"] = 0, 0
    try:
        start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await fetch(
            "SELECT status, COALESCE(realized_pnl,0) rp, COALESCE(unrealized_pnl,0) up "
            "FROM positions WHERE (status='closed' AND closed_at>=$1) OR status='open'", start)
        s["open_positions"] = sum(1 for x in rows if x["status"] == "open")
        s["realized"] = sum(float(x["rp"]) for x in rows if x["status"] == "closed")
        s["unrealized"] = sum(float(x["up"]) for x in rows if x["status"] == "open")
        s["day_pnl"] = s["realized"] + s["unrealized"]
    except Exception:
        s["open_positions"] = 0
        s["realized"] = s["unrealized"] = s["day_pnl"] = 0.0
    try:  # go-live readiness (best-effort; never break the digest if the broker is down)
        from api.prelive_checks import build_prelive_service
        run = await build_prelive_service(persist=False).run_all("digest")
        s["prelive_overall"] = run.get("overall")
        s["prelive_failed"] = run.get("failed") or []
    except Exception:
        s["prelive_overall"] = "n/a"
    return s


async def save_and_send(alerter) -> str:
    s = await gather_stats()
    text = format_digest(s)
    if alerter:
        try:
            await alerter.send_async(f"AEGIS daily health — {s['date']}", text)
        except Exception as exc:
            log.warning("health_digest_email_failed", error=str(exc))
    return text
