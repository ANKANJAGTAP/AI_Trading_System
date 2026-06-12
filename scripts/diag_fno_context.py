"""Live test of build_fno_context -> FnoPipeline. Backfills INDIA VIX daily (for the
IV-rank proxy), then builds a live F&O context for a few underlyings and runs the
pipeline, printing the decision + structure. Run during market hours.
"""
from __future__ import annotations

import asyncio

from broker.kite_adapter import KiteAdapter
from common.alerts import Alerter
from common.db import close_pool, init_pool
from common.logging import configure_logging
from config.loader import get_config
from config.settings import get_settings
from data.historical import incremental_backfill
from data.instruments import get_token
from data.rate_governor import RateGovernor
from engine.context_builder import build_fno_context
from strategies.fno import FnoPipeline

UNIVERSE = [("NIFTY", "NSE:NIFTY 50"), ("BANKNIFTY", "NSE:NIFTY BANK"), ("RELIANCE", "NSE:RELIANCE")]


async def main():
    configure_logging()
    await init_pool()
    cfg, settings = get_config(), get_settings()
    adapter = KiteAdapter(settings, Alerter(settings))
    await asyncio.to_thread(adapter.ensure_token)
    gov = RateGovernor(cfg.data.rate_limits)

    vix_tok = await get_token("NSE:INDIA VIX")
    print("INDIA VIX token:", vix_tok)
    if vix_tok:
        try:
            await incremental_backfill(adapter, gov, vix_tok, "day", 300, 200)
            print("VIX daily backfill done")
        except Exception as e:
            print("VIX backfill error:", str(e)[:120])

    pipe = FnoPipeline(cfg)
    for name, key in UNIVERSE:
        tok = await get_token(key)
        ctx = await build_fno_context(adapter, gov, name, key, tok, cfg.strategy.fno)
        if ctx is None:
            print(f"\n{name}: context=None (insufficient data / no expiry in window)")
            continue
        res = await pipe.evaluate(
            {"tradingsymbol": name, "exchange": "NFO", "instrument_type": "CE", "lot_size": ctx.lot_size}, ctx)
        st = res.signal.detail.get("structure") if res.signal else None
        print(f"\n{name}: spot={ctx.spot} iv={ctx.iv} iv_rank={ctx.iv_rank} dte={ctx.dte} "
              f"dir={ctx.direction} oi={ctx.oi_signal} pcr={ctx.extra.get('pcr')} "
              f"step={ctx.strike_step} lot={ctx.lot_size}")
        print(f"   -> {res.decision} {res.reason or ''} | struct={st and st.get('type')} "
              f"maxloss/lot={st and st.get('max_loss_per_lot')} | trail={[g['name'] for g in res.trail]}")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
