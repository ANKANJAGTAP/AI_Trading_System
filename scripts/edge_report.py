"""CLI: edge-decay report — weekly per-sleeve expectancy trend + feature
discrimination snapshot. The same report the engine emails every Friday evening.

Usage:
    python -m scripts.edge_report
    python -m scripts.edge_report --weeks 12
"""
from __future__ import annotations

import argparse
import asyncio

from common.db import close_pool, init_pool
from common.logging import configure_logging
from research.edge import build_edge_report


async def main() -> None:
    ap = argparse.ArgumentParser(description="Edge-decay report.")
    ap.add_argument("--weeks", type=int, default=8)
    args = ap.parse_args()
    configure_logging()
    await init_pool()
    try:
        print("\n" + await build_edge_report(args.weeks))
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
