"""
R-based position sizing (the repo's risk philosophy).

Risk is expressed in R = capital * per_trade_risk_pct / 100, scaled by the
meta-label confidence (which can only shrink, never inflate). Lots are capped by
the per-structure max, and by the portfolio's remaining R budget.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SizingConfig:
    capital: float
    per_trade_risk_pct: float = 1.0
    max_lots_per_structure: int = 20


def effective_R(cfg: SizingConfig, confidence: float) -> float:
    c = min(max(confidence, 0.0), 1.0)          # clamp to [0,1] — never > budget
    return cfg.capital * cfg.per_trade_risk_pct / 100.0 * c


def size_lots(eff_R: float, max_loss_per_lot: float, cfg: SizingConfig,
              portfolio_remaining_R: float | None = None) -> int:
    """Number of lots so that worst-case loss stays within the R budget."""
    if max_loss_per_lot <= 0:
        return 0
    lots = math.floor(eff_R / max_loss_per_lot)
    lots = min(lots, cfg.max_lots_per_structure)
    if portfolio_remaining_R is not None:
        lots = min(lots, math.floor(max(portfolio_remaining_R, 0.0) / max_loss_per_lot))
    return max(int(lots), 0)
