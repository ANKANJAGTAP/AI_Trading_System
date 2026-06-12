"""Point-in-time candle accessor for the backtester.

Preloads the full test window per (token, interval) into memory once, then serves
slices `ts <= as_of` so the strategy can never see future bars (no look-ahead).
"""
from __future__ import annotations

import pandas as pd

from data.store import load_candles_range_df


class DataWindow:
    def __init__(self) -> None:
        self._frames: dict[tuple[int, str], pd.DataFrame] = {}

    async def load(self, token: int, interval: str, from_dt, to_dt) -> pd.DataFrame:
        df = await load_candles_range_df(token, interval, from_dt, to_dt)
        self._frames[(token, interval)] = df
        return df

    def frame(self, token: int, interval: str) -> pd.DataFrame | None:
        return self._frames.get((token, interval))

    def slice(self, token: int, interval: str, as_of) -> pd.DataFrame | None:
        df = self._frames.get((token, interval))
        if df is None or df.empty:
            return df
        return df[df.index <= as_of]
