"""Shared fixtures for feature tests."""
import numpy as np
import pandas as pd
import pytest


def make_ohlcv(n=300, seed=0):
    """Reproducible random-walk OHLCV with a business-day DatetimeIndex."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    openp = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum.reduce([openp, close, close * (1 + np.abs(rng.normal(0, 0.005, n)))])
    low = np.minimum.reduce([openp, close, close * (1 - np.abs(rng.normal(0, 0.005, n)))])
    vol = rng.integers(100_000, 1_000_000, n).astype("int64")
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


@pytest.fixture
def ohlcv():
    return make_ohlcv()
