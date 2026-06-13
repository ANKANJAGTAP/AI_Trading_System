"""
ml — Pillar 3 of the world-class F&O platform.

Labelling + the anti-overfitting validation stack that decides whether an edge
is real, built on the Pillar-2 feature matrix:

  labeling       : triple-barrier method, daily-vol target, directional/meta labels
  sample_weights : label concurrency, average uniqueness, time-decay
  cv             : PurgedKFold + combinatorial purged CV (CPCV)
  metrics        : Sharpe, PSR, Deflated Sharpe, PBO (CSCV), drawdown/profit-factor
  models         : standardising logistic meta-model + size-multiplier (veto/shrink)
  pipeline       : price+features -> events -> labels -> CPCV-evaluated model
"""
from . import labeling, sample_weights, cv, metrics, models, pipeline  # noqa: F401
from .models import LogisticMetaModel, size_multiplier
from .cv import PurgedKFold, combinatorial_purged_cv, num_cpcv_paths
from .metrics import (
    sharpe_ratio, probabilistic_sharpe_ratio, deflated_sharpe_ratio,
    expected_max_sharpe, pbo_cscv, max_drawdown, profit_factor, expectancy,
)

__version__ = "0.1.0"
__all__ = [
    "labeling", "sample_weights", "cv", "metrics", "models", "pipeline",
    "LogisticMetaModel", "size_multiplier",
    "PurgedKFold", "combinatorial_purged_cv", "num_cpcv_paths",
    "sharpe_ratio", "probabilistic_sharpe_ratio", "deflated_sharpe_ratio",
    "expected_max_sharpe", "pbo_cscv", "max_drawdown", "profit_factor", "expectancy",
]
