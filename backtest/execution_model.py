"""Execution-realism fill model for the backtester (#25) — pure, no I/O.

The naive backtest lie is "a stop fills exactly at the stop price." It doesn't: a
stop becomes a MARKET order the instant it is touched, so when a bar GAPS through
the stop (opens beyond it) the real fill is the gap open — materially worse than
the stop. A target is a LIMIT order: it fills at the limit or better, so a
favourable gap fills at the (better) open and a limit never suffers adverse
slippage.

`resolve_intrabar_exit` turns one OHLC bar + a position's stop/target into the
honest (reason, fill_price) so the engine stops overstating edge. Rules:

  * Gap through the stop at the open    -> stop,   filled at the open (adverse).
  * Gap through the target at the open  -> target, filled at the open (favourable).
  * Stop touched intrabar               -> stop,   filled at the stop + adverse slippage.
  * Target touched intrabar             -> target, filled at the target (limit, no slip).
  * Both stop and target touched same bar -> STOP wins (conservative: the intrabar
    path is unknowable, so assume the worse outcome for the trader).
  * Stops are market-on-trigger -> adverse slippage; targets are limits -> none.

`side` everywhere is the POSITION side: BUY = long (stop below, target above,
exits by SELLing), SELL = short (stop above, target below, exits by BUYing).
"""
from __future__ import annotations


def _slip(price: float, bps: float, *, adverse_up: bool) -> float:
    delta = price * bps / 10000.0
    return price + delta if adverse_up else price - delta


def stop_fill_price(side: str, stop: float, bar_open: float, slippage_bps: float = 0.0) -> float:
    """Honest stop fill. A long's stop is below the entry: a gap-down opens past it
    and fills at the (lower) open; otherwise it fills at the stop. Adverse slippage
    always applies because a triggered stop is a market order."""
    if side == "BUY":                       # exit SELL -> adverse is lower
        return round(_slip(min(stop, bar_open), slippage_bps, adverse_up=False), 2)
    return round(_slip(max(stop, bar_open), slippage_bps, adverse_up=True), 2)  # short


def target_fill_price(side: str, target: float, bar_open: float) -> float:
    """Honest target fill. A limit fills at the limit or better; a favourable gap
    fills at the (better) open. No adverse slippage on a limit."""
    if side == "BUY":                       # long target above -> gap-up fills higher (better)
        return round(max(target, bar_open), 2)
    return round(min(target, bar_open), 2)  # short target below -> gap-down fills lower (better)


def resolve_intrabar_exit(side: str, stop: float | None, target: float | None,
                          bar_open: float, bar_high: float, bar_low: float,
                          slippage_bps: float = 0.0) -> tuple[str | None, float | None]:
    """Resolve a single bar into (reason, fill_price); reason in {"stop","target"}
    or (None, None) if neither level is touched. Gap-at-open dominates (the position
    is already out at the open); otherwise an intrabar touch resolves stop-first."""
    o, h, l = float(bar_open), float(bar_high), float(bar_low)
    long = side == "BUY"

    # 1) A gap at the open is the first thing that happens in the bar.
    if long:
        if stop and o <= stop:
            return "stop", stop_fill_price(side, stop, o, slippage_bps)
        if target and o >= target:
            return "target", target_fill_price(side, target, o)
    else:
        if stop and o >= stop:
            return "stop", stop_fill_price(side, stop, o, slippage_bps)
        if target and o <= target:
            return "target", target_fill_price(side, target, o)

    # 2) Intrabar touches (no gap). Both touched -> stop wins (conservative).
    if long:
        stop_hit = bool(stop) and l <= stop
        tgt_hit = bool(target) and h >= target
    else:
        stop_hit = bool(stop) and h >= stop
        tgt_hit = bool(target) and l <= target
    if stop_hit:
        return "stop", stop_fill_price(side, stop, o, slippage_bps)
    if tgt_hit:
        return "target", target_fill_price(side, target, o)
    return None, None


# --------------------------------------------------------------- #25 order realism
def price_band_breached(price: float, reference: float, band_pct: float = 0.20) -> bool:
    """Exchange daily price band / circuit: an order priced beyond ±band_pct of the
    reference (prior close) is rejected by the exchange. True = would be rejected.
    Unknown/zero inputs -> not breached (can't judge -> don't fabricate a rejection)."""
    if not reference or reference <= 0 or not price or price <= 0:
        return False
    return abs(price - reference) / reference > band_pct


def freeze_slices(quantity, freeze_qty) -> list[int]:
    """Split an order above the exchange FREEZE limit into freeze-compliant child
    orders (F&O quantity freeze — a single order over the cap is rejected outright).
    Returns the list of child quantities (sums back to `quantity`)."""
    q = int(quantity or 0)
    if q <= 0:
        return []
    if not freeze_qty or freeze_qty <= 0 or q <= int(freeze_qty):
        return [q]
    cap = int(freeze_qty)
    full, rem = divmod(q, cap)
    slices = [cap] * full
    if rem:
        slices.append(rem)
    return slices


def rate_limit_ok(orders_in_window: int, max_per_window: int) -> bool:
    """Throttle gate: False once the per-window order budget is spent (broker/exchange
    OPS rate limits). max<=0 means unlimited."""
    if not max_per_window or max_per_window <= 0:
        return True
    return orders_in_window < max_per_window
