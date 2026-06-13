import numpy as np
import pandas as pd

from ml import labeling as lb


def _linear_close(slope_pct):
    idx = pd.bdate_range("2022-01-03", periods=20)
    return pd.Series([100 * (1 + slope_pct * k) for k in range(20)], index=idx)


def _events(close, end_offset=10, trgt=0.01):
    return pd.DataFrame(
        {"t1": [close.index[end_offset]], "trgt": [trgt]},
        index=[close.index[0]],
    )


def test_daily_vol_positive(close):
    v = lb.get_daily_vol(close, 20).dropna()
    assert (v >= 0).all() and v.iloc[-1] > 0


def test_vertical_barriers_offset(close):
    vb = lb.get_vertical_barriers(close, close.index, num_bars=5)
    assert vb.iloc[0] == close.index[5]
    assert len(vb) == len(close) - 5


def test_upper_barrier_hit():
    c = _linear_close(0.01)                 # +1% per bar
    out = lb.apply_triple_barrier(c, _events(c, 10, 0.01), pt_sl=(2, 2))
    row = out.iloc[0]
    assert row["bin"] == 1
    assert abs(row["ret"] - 0.02) < 1e-9    # up barrier = 2*trgt
    assert row["touch"] == c.index[2]


def test_lower_barrier_hit():
    c = _linear_close(-0.01)                # -1% per bar
    out = lb.apply_triple_barrier(c, _events(c, 10, 0.01), pt_sl=(2, 2))
    assert out.iloc[0]["bin"] == -1
    assert out.iloc[0]["ret"] < 0


def test_vertical_barrier_timeout():
    idx = pd.bdate_range("2022-01-03", periods=20)
    c = pd.Series(100.0, index=idx)         # flat -> no horizontal touch
    out = lb.apply_triple_barrier(c, _events(c, 10, 0.01), pt_sl=(2, 2))
    assert out.iloc[0]["bin"] == 0
    assert out.iloc[0]["touch"] == c.index[10]


def test_meta_labels_respect_side():
    c = _linear_close(0.01)
    out = lb.apply_triple_barrier(c, _events(c, 10, 0.01), pt_sl=(2, 2))
    long = lb.meta_labels(out, pd.Series([1], index=out.index))
    short = lb.meta_labels(out, pd.Series([-1], index=out.index))
    assert long.iloc[0] == 1     # long was right on an up move
    assert short.iloc[0] == 0    # short was wrong
