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
