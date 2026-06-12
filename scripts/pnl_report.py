"""End-of-day paper P&L report. Summarizes today's positions (realized + unrealized)
by sleeve, win/loss, open F&O structures, and kill-switch status against the daily
limit. Read-only. Run any time (intraday snapshot) or after close (EOD)."""
from __future__ import annotations

import asyncio
from collections import defaultdict

from common.db import close_pool, fetch, init_pool
from common.logging import configure_logging
from common.market_time import now_ist
from common.state import get_state
from config.loader import get_config


async def main():
    configure_logging()
    await init_pool()
    cfg = get_config()
    cap = float(getattr(cfg.risk, "paper_capital", 0) or 0)
    start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)

    rows = await fetch(
        "SELECT sleeve, tradingsymbol, side, quantity, status, "
        "COALESCE(realized_pnl,0) AS rp, COALESCE(unrealized_pnl,0) AS up, correlation_id "
        "FROM positions WHERE opened_at >= $1 ORDER BY sleeve, opened_at", start)

    by_sleeve = defaultdict(lambda: {"realized": 0.0, "unrealized": 0.0, "open": 0, "closed": 0, "wins": 0, "losses": 0})
    structs = defaultdict(lambda: {"legs": 0, "unrealized": 0.0})
    # TRADE-level accounting: legs sharing a correlation_id are ONE trade — count one
    # W/L on the combined P&L, not one per leg.
    trades = defaultdict(lambda: {"sleeve": "?", "rp": 0.0, "closed": True})
    realized = unrealized = 0.0
    wins = losses = 0
    for r in rows:
        s = by_sleeve[r["sleeve"] or "?"]
        rp, up = float(r["rp"]), float(r["up"])
        key = str(r["correlation_id"]) if r["correlation_id"] else f"row{id(r)}"
        t = trades[key]
        t["sleeve"] = r["sleeve"] or "?"
        if r["status"] == "closed":
            s["realized"] += rp; realized += rp
            t["rp"] += rp
        else:
            s["unrealized"] += up; unrealized += up; s["open"] += 1
            t["closed"] = False
            if r["sleeve"] == "fno":
                st = structs[str(r["correlation_id"])]
                st["legs"] += 1; st["unrealized"] += up
    for t in trades.values():
        if not t["closed"]:
            continue
        s = by_sleeve[t["sleeve"]]
        s["closed"] += 1
        if t["rp"] > 0:
            s["wins"] += 1; wins += 1
        elif t["rp"] < 0:
            s["losses"] += 1; losses += 1

    killed = await get_state("kill_switch_active", False)
    enabled = await get_state("orchestrator_enabled", False)
    daily_limit = cap * (cfg.risk.daily_max_loss_pct.default / 100.0)
    net = realized + unrealized

    print("\n================= PAPER P&L REPORT =================")
    print(f"Date (IST): {start.date()}    Paper capital: Rs {cap:,.0f}")
    print(f"orchestrator_enabled={enabled}   kill_switch_active={killed}   daily_limit=-Rs {daily_limit:,.0f}")
    print("---------------------------------------------------")
    if not rows:
        print("No positions today.")
    for sleeve, s in by_sleeve.items():
        decided = s["wins"] + s["losses"]
        wr = (s["wins"] / decided * 100) if decided else 0
        print(f"{sleeve:16} closed={s['closed']:2} (W{s['wins']}/L{s['losses']} {wr:.0f}%win) "
              f"open={s['open']:2}  realized=Rs {s['realized']:,.0f}  unrealized=Rs {s['unrealized']:,.0f}")
    if structs:
        print("---------------------------------------------------")
        print("Open F&O structures:")
        for cid, st in structs.items():
            print(f"  {cid[:8]}  legs={st['legs']}  unrealized=Rs {st['unrealized']:,.0f}")
    print("---------------------------------------------------")
    pct = f"  ({net / cap * 100:+.2f}% of capital)" if cap else ""
    print(f"TOTAL  realized=Rs {realized:,.0f}  unrealized=Rs {unrealized:,.0f}  NET=Rs {net:,.0f}{pct}")
    print(f"Closed trades: {wins} wins / {losses} losses")
    print("===================================================")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
