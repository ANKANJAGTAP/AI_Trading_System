import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def close():
    """Reproducible random-walk close with a business-day DatetimeIndex."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2021-01-01", periods=400)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), index=idx)


@pytest.fixture
def feature_matrix(close):
    ret = close.pct_change()
    fm = pd.DataFrame(
        {
            "ret_1": ret,
            "mom_10": close.pct_change(10),
            "sma_ratio": close / close.rolling(10).mean() - 1,
            "vol_10": ret.rolling(10).std(),
        },
        index=close.index,
    ).dropna()
    return fm
