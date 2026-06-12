"""Volume profile (Phase 3.3): POC / Value Area High / Value Area Low + bins.

Distributes each candle's volume to the bin of its typical price, then finds the
Point of Control (busiest price) and the ~70% Value Area around it — durable S/R the
order book doesn't show. Pure over an OHLCV frame.
"""
from __future__ import annotations

import pandas as pd


def volume_profile(df: pd.DataFrame, bins: int = 24, value_area: float = 0.70) -> dict:
    if df is None or df.empty:
        return {"poc": None, "vah": None, "val": None, "bins": []}
    lo, hi = float(df["low"].min()), float(df["high"].max())
    typical = ((df["high"] + df["low"] + df["close"]) / 3.0).to_numpy()
    vol = df["volume"].astype(float).to_numpy()
    if hi <= lo:
        return {"poc": round(lo, 2), "vah": round(hi, 2), "val": round(lo, 2),
                "bins": [{"price": round(lo, 2), "volume": float(vol.sum())}]}

    width = (hi - lo) / bins
    buckets = [0.0] * bins
    for p, v in zip(typical, vol):
        idx = min(bins - 1, max(0, int((p - lo) / width)))
        buckets[idx] += float(v)
    centers = [round(lo + (i + 0.5) * width, 2) for i in range(bins)]

    total = sum(buckets)
    poc_i = max(range(bins), key=lambda i: buckets[i])
    captured = buckets[poc_i]
    lo_i = hi_i = poc_i
    while captured < value_area * total and (lo_i > 0 or hi_i < bins - 1):
        left = buckets[lo_i - 1] if lo_i > 0 else -1.0
        right = buckets[hi_i + 1] if hi_i < bins - 1 else -1.0
        if right >= left:
            hi_i += 1
            captured += buckets[hi_i]
        else:
            lo_i -= 1
            captured += buckets[lo_i]
    return {
        "poc": centers[poc_i], "vah": centers[hi_i], "val": centers[lo_i],
        "bins": [{"price": centers[i], "volume": round(buckets[i], 0)} for i in range(bins)],
    }
