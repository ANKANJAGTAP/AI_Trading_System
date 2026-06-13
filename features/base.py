"""
Feature framework — the single source of truth for every TA / options feature.

Design guarantees (from the world-class plan, Pillar 2):
  * POINT-IN-TIME: every feature is f(history <= T) -> value_at_T. The value at
    row i must depend only on rows 0..i. This is enforced by a parity test
    (tests/test_engine_parity.py) that truncates the series and checks the tail
    value is unchanged — i.e. no look-ahead leakage.
  * TRAIN/SERVE PARITY: the SAME function computes a feature in research (over a
    Parquet frame) and live (over a streaming buffer). One implementation, two
    callers. The engine guarantees identical inputs => identical outputs.
  * VERSIONED + CATALOGED: each feature has an id, version, category and lookback
    so backtests can pin exact feature versions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

# Feature categories (the plan's taxonomy)
CATEGORIES = (
    "trend", "momentum", "volatility", "volume",
    "options", "microstructure", "regime", "statistical",
)


@dataclass(frozen=True)
class FeatureSpec:
    """Metadata + the pure function that computes one feature."""
    id: str
    category: str
    fn: Callable[..., pd.Series]
    params: dict = field(default_factory=dict)
    lookback: int = 0           # bars of history needed for a stable value
    version: int = 1
    point_in_time: bool = True
    description: str = ""

    def compute(self, df: pd.DataFrame) -> pd.Series:
        s = self.fn(df, **self.params)
        return s.rename(self.id)


# Global registry: feature_id -> FeatureSpec
REGISTRY: dict[str, FeatureSpec] = {}


def register(spec: FeatureSpec) -> FeatureSpec:
    if spec.category not in CATEGORIES:
        raise ValueError(f"unknown category {spec.category!r} for {spec.id}")
    if spec.id in REGISTRY:
        raise ValueError(f"duplicate feature id {spec.id!r}")
    REGISTRY[spec.id] = spec
    return spec


def get(feature_id: str) -> FeatureSpec:
    return REGISTRY[feature_id]


def list_features(category: str | None = None) -> list[str]:
    ids = sorted(REGISTRY)
    if category:
        ids = [i for i in ids if REGISTRY[i].category == category]
    return ids


def clear_registry() -> None:
    """Test helper — wipe the registry (then re-import modules to repopulate)."""
    REGISTRY.clear()
