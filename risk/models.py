"""Risk-engine data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstrumentKind(str, Enum):
    EQUITY = "equity"            # shares (lot_size 1); stop on price
    FUTURES = "futures"         # lots; stop on price
    OPTION_BUY = "option_buy"   # naked option BUY; stop on PREMIUM
    STRUCTURE = "structure"     # defined-risk option structure; R == max loss


@dataclass
class SizingResult:
    """Outcome of an R-sizing request. `quantity` is total units (shares or
    contracts) and is always a multiple of `lot_size`."""

    rejected: bool
    reason: str | None = None
    quantity: int = 0
    lots: int = 0
    lot_size: int = 1
    r_intended: float = 0.0       # effective R budget (₹), after confidence
    actual_risk: float = 0.0      # ₹ truly at risk for the final size
    capital_allocated: float = 0.0
    clamps: list[str] = field(default_factory=list)  # which ceilings bound the size
    detail: dict = field(default_factory=dict)

    @classmethod
    def reject(cls, reason: str, **kw) -> "SizingResult":
        return cls(rejected=True, reason=reason, **kw)


@dataclass
class KillSwitchStatus:
    active: bool
    tripped_today: bool
    realized_pnl: float
    unrealized_pnl: float
    day_pnl: float
    loss_limit: float            # negative ₹ threshold
    starting_capital: float


@dataclass
class HeatSnapshot:
    total_open_r: float
    portfolio_risk_limit_r: float
    heat_pct: float              # total_open_r / portfolio_risk_limit_r * 100
    num_open_positions: int
    max_concurrent_positions: int
    correlated_clusters: list[list[str]] = field(default_factory=list)
    by_sleeve: dict = field(default_factory=dict)
