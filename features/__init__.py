"""
features — Pillar 2 of the world-class F&O platform.

A versioned, point-in-time technical-analysis + options-analytics feature
library with train/serve parity, computed over the Pillar-1 data platform.

  base       : Feature spec + registry/catalog + point-in-time contract
  indicators : trend / momentum / volatility / volume (pure functions)
  options    : Black-Scholes greeks, implied vol, chain analytics (PCR/GEX/...)
  engine     : FeatureEngine + build_feature_matrix over canonical EOD data
"""
from . import indicators, options, engine  # noqa: F401 (populate registry)
from .base import (
    REGISTRY, FeatureSpec, register, get, list_features, CATEGORIES,
)
from .engine import (
    FeatureEngine, build_feature_matrix,
    underlying_daily_from_eod, option_features_timeseries,
)

__version__ = "0.1.0"
__all__ = [
    "REGISTRY", "FeatureSpec", "register", "get", "list_features", "CATEGORIES",
    "FeatureEngine", "build_feature_matrix",
    "underlying_daily_from_eod", "option_features_timeseries",
    "indicators", "options", "engine",
]
