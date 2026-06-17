"""Option-leg execution realism for F&O backtests (#23) — pure, no I/O.

The F&O backtester prices legs off Black-Scholes mids with a flat slippage %
(`fno_engine.slippage_cost`), which ignores two facts that dominate real option
P&L: options trade with WIDE bid-ask spreads (worst on OTM / short-dated strikes),
and thin OI/volume strikes can't be filled at the mid at all. This models both, so
a backtest stops assuming a free fill at the theoretical mid.

  * `option_fill_price` crosses the spread — a BUY pays toward the ask, a SELL
    receives toward the bid, plus a slippage fraction for size/impact.
  * `spread_pct` / `liquidity_ok` gate illiquid strikes — too wide a spread or too
    little OI/volume means the leg is untradable and the honest backtest skips it.

All inputs are explicit numbers, so it is fully unit-tested without a live chain.
Wiring this into `fno_engine` (replacing the flat slip) and sourcing a real
historical option chain are the remaining, data-dependent half of #23.
"""
from __future__ import annotations

import math

INF = float("inf")


def spread_pct(bid: float, ask: float) -> float:
    """Relative bid-ask spread vs the mid. An unusable quote (non-positive or
    crossed) is treated as infinitely wide so it always fails a spread gate."""
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return INF
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid if mid > 0 else INF


def liquidity_ok(oi, volume, *, min_oi: float = 0.0, min_volume: float = 0.0) -> bool:
    """Enough open interest AND volume to trade. Unknown (None) values fail closed
    whenever a floor is set."""
    if min_oi > 0 and (oi is None or oi < min_oi):
        return False
    if min_volume > 0 and (volume is None or volume < min_volume):
        return False
    return True


def option_fill_price(side: str, bid: float, ask: float, *, slippage_frac: float = 0.0) -> float:
    """Realistic fill for one option leg. A BUY pays toward the ask, a SELL receives
    toward the bid; `slippage_frac` adds adverse move (fraction of mid) for impact."""
    mid = (bid + ask) / 2.0
    half = (ask - bid) / 2.0
    slip = mid * slippage_frac
    if side == "BUY":
        return round(mid + half + slip, 2)      # cross up to the ask (+ impact)
    return round(mid - half - slip, 2)           # SELL hits the bid (- impact)


def leg_fill(side: str, bid: float, ask: float, oi=None, volume=None, *,
             max_spread_pct: float = 0.25, min_oi: float = 0.0,
             min_volume: float = 0.0, slippage_frac: float = 0.0) -> dict:
    """Gate + fill for one option leg. Returns {tradable, reason, fill_price,
    spread_pct}. tradable=False means SKIP this strike (too wide / too illiquid)
    rather than book a fantasy fill at the mid."""
    sp = spread_pct(bid, ask)
    if sp > max_spread_pct:
        pct = "inf" if sp == INF else f"{sp:.0%}"
        return {"tradable": False, "reason": f"spread {pct} > {max_spread_pct:.0%}",
                "fill_price": None, "spread_pct": sp}
    if not liquidity_ok(oi, volume, min_oi=min_oi, min_volume=min_volume):
        return {"tradable": False, "reason": "insufficient OI/volume",
                "fill_price": None, "spread_pct": round(sp, 4)}
    return {"tradable": True, "reason": "ok",
            "fill_price": option_fill_price(side, bid, ask, slippage_frac=slippage_frac),
            "spread_pct": round(sp, 4)}


def synthetic_spread_pct(spot: float, strike: float, dte_days: float, iv: float,
                         *, base: float = 0.01) -> float:
    """Estimate an option's relative bid-ask spread when no real chain is available
    (#23): spreads widen for OTM strikes (|log-moneyness|), short DTE, and high IV.
    A structural stand-in for a real historical chain — it makes BS-model backtests
    pay realistically more to cross OTM / near-expiry legs. Returns a premium fraction,
    capped at 50%."""
    moneyness = abs(math.log(strike / spot)) if spot > 0 and strike > 0 else 0.0
    dte = max(0.5, float(dte_days or 0.0))
    spread = base * (1 + 4.0 * moneyness) * (1 + 2.0 / math.sqrt(dte)) * (1 + max(0.0, float(iv or 0.0)))
    return round(min(spread, 0.5), 4)
