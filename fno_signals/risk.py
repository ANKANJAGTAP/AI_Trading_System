"""
Pre-trade risk state & gates.

Keeps the repo's R-based risk philosophy: a daily kill-switch, a portfolio R
budget, a max-concurrent-positions cap, and an options-aware scenario gate that
re-prices the candidate over a spot x IV grid (Pillar 4) — because linear VaR is
misleading for option books.
"""
from __future__ import annotations

from dataclasses import dataclass

from fno_backtest.analysis import scenario_grid


@dataclass
class RiskState:
    capital: float
    day_pnl: float = 0.0
    open_R: float = 0.0
    open_positions: int = 0
    daily_max_loss_pct: float = 3.0
    portfolio_risk_limit_pct: float = 5.0
    max_concurrent: int = 5

    def kill_switch_tripped(self) -> bool:
        return self.day_pnl <= -self.capital * self.daily_max_loss_pct / 100.0

    def portfolio_remaining_R(self) -> float:
        budget = self.capital * self.portfolio_risk_limit_pct / 100.0
        return max(0.0, budget - self.open_R)

    def can_add_position(self) -> bool:
        return self.open_positions < self.max_concurrent


def scenario_loss_ok(structure, spot, t, iv, max_loss_limit):
    """Worst-case MTM over the spot x IV grid must stay within `max_loss_limit`
    (a positive rupee number). Returns (ok, worst_loss)."""
    grid = scenario_grid(structure, spot, t, iv=iv)
    worst = float(grid.to_numpy().min())
    return (worst >= -abs(max_loss_limit)), worst
