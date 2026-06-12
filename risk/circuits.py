"""Risk circuits (Phase 3.2): the soft brakes that sit beside the hard kill switch.

- Max-drawdown circuit: if intraday equity falls more than `max_drawdown_pct` of
  capital from its peak, BLOCK new entries (don't flatten — that's the kill switch's
  job at the daily hard-loss line). A pullback from a green peak is a "stop adding
  risk" signal, not a "square off everything" signal.
- Per-strategy auto-disable: a sleeve whose rolling expectancy turns negative over a
  meaningful sample is disabled (new entries only; open positions stay managed).

The pure predicates below are unit-tested; engine/main wires them to live state.
"""
from __future__ import annotations


def drawdown_breached(peak_pnl: float, current_pnl: float, capital: float,
                      max_dd_pct: float) -> bool:
    """True when (peak - current) day P&L exceeds max_dd_pct of capital."""
    if capital <= 0 or max_dd_pct <= 0:
        return False
    return (peak_pnl - current_pnl) >= capital * max_dd_pct / 100.0


def profit_lock_breached(peak_pnl: float, current_pnl: float, capital: float,
                         trigger_pct: float, max_giveback_pct: float) -> bool:
    """Lock in gains: once the day's P&L peak clears `trigger_pct` of capital, block new
    entries if we've given back more than `max_giveback_pct` of that peak. Today the
    book peaked at +110k and bled to +28k — this would have stopped it near +66k."""
    if capital <= 0 or trigger_pct <= 0 or peak_pnl <= 0:
        return False
    if peak_pnl < capital * trigger_pct / 100.0:
        return False
    floor = peak_pnl * (1.0 - max_giveback_pct / 100.0)
    return current_pnl <= floor


def should_disable_sleeve(rmultiples: list[float], min_trades: int,
                          expectancy_floor: float) -> bool:
    """True when a sleeve's mean R over the last `len(rmultiples)` closed trades is
    below the floor AND the sample is at least `min_trades` (avoid acting on noise)."""
    if len(rmultiples) < min_trades:
        return False
    return (sum(rmultiples) / len(rmultiples)) < expectancy_floor


def period_loss_breached(realized_pnl: float, capital: float, max_loss_pct: float) -> bool:
    """Weekly/monthly brake predicate: True when the period's REALIZED loss exceeds
    max_loss_pct of capital. The daily kill-switch can't stop a slow bleed — this can."""
    if capital <= 0 or max_loss_pct <= 0:
        return False
    return realized_pnl <= -(capital * max_loss_pct / 100.0)


def loss_streak_hit(trade_pnls_newest_first: list[float], max_consecutive: int) -> bool:
    """True when the most recent `max_consecutive` TRADES (structures = one trade)
    are all losses. Four straight stops means the read is wrong — stand down today,
    re-engage tomorrow; pressing a cold hand is how a bad day becomes a terrible one."""
    if max_consecutive <= 0:
        return False
    streak = 0
    for pnl in trade_pnls_newest_first:
        if pnl < 0:
            streak += 1
            if streak >= max_consecutive:
                return True
        else:
            break
    return False
