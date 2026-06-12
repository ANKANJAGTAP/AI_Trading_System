"""CLI: read (or regenerate) the daily operations journal.

Usage:
    python -m scripts.journal              # today's journal (regenerated live)
    python -m scripts.journal --last 3     # stored journals for the last 3 days
"""
from __future__ import annotations

import argparse
import asyncio

from common.db import close_pool, fetch, init_pool
from common.logging import configure_logging


async def main() -> None:
    ap = argparse.ArgumentParser(description="Daily operations journal.")
    ap.add_argument("--last", type=int, default=0, help="show the last N stored journals")
    ap.add_argument("--save", action="store_true", help="store today's regenerated journal")
    ap.add_argument("--send", action="store_true", help="email the regenerated journal; implies --save")
    args = ap.parse_args()
    configure_logging()
    await init_pool()
    try:
        if args.last > 0:
            rows = await fetch("SELECT day, content FROM daily_journal ORDER BY day DESC LIMIT $1", args.last)
            for r in reversed(rows):
                print("\n" + "=" * 72 + "\n" + r["content"])
            if not rows:
                print("No journals stored yet.")
        else:
            if args.save or args.send:
                from research.journal import save_and_send
                alerter = None
                if args.send:
                    from common.alerts import Alerter
                    alerter = Alerter()
                print("\n" + await save_and_send(alerter))
            else:
                from research.journal import build_daily_journal
                print("\n" + await build_daily_journal())
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
