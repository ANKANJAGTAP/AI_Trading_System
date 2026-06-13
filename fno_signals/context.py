"""
MarketContext — the point-in-time snapshot a decision is made from.

Bundles everything the pipeline needs for one (underlying, timestamp): the spot,
the computed feature vector (Pillar 2), the IV regime inputs, the option chain,
and contract facts (lot size, dte) resolved as-of the date (Pillar 1). Nothing
in here may use information after `timestamp`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class MarketContext:
    underlying: str
    timestamp: pd.Timestamp
    spot: float
    features: dict           # feature_id -> value (point-in-time)
    iv_rank: float           # 0..100
    atm_iv: float            # decimal, e.g. 0.18
    chain: pd.DataFrame      # OPT rows: opt_type, strike, close, oi, volume
    dte: int                 # calendar days to the chosen expiry
    expiry: pd.Timestamp
    lot_size: int
    step: float = 50.0       # strike spacing
    events: tuple = field(default_factory=tuple)  # blackout dates near `timestamp`

    def t_years(self) -> float:
        return max(self.dte, 1) / 365.0

    def feature(self, name: str, default=float("nan")):
        return self.features.get(name, default)
