"""Bar-based fill simulation for the backtester. Reuses the live CostModel verbatim
so backtest costs == live costs. Entries cross the spread by `slippage_bps`; exits
are filled adversely by the same amount.
"""
from __future__ import annotations

from execution.costs import CostModel


class BacktestBroker:
    def __init__(self, cost_model: CostModel, slippage_bps: float) -> None:
        self.cost = cost_model
        self.slippage_bps = float(slippage_bps)

    def _slip(self, price: float) -> float:
        return price * self.slippage_bps / 10000.0

    def entry_fill(self, side: str, ref_price: float) -> float:
        # BUY pays up (ask), SELL hits down (bid).
        return round(ref_price + self._slip(ref_price) if side == "BUY"
                     else ref_price - self._slip(ref_price), 2)

    def exit_fill(self, entry_side: str, ref_price: float) -> float:
        # Exit is the opposite side of entry -> adverse slippage relative to ref.
        return round(ref_price - self._slip(ref_price) if entry_side == "BUY"
                     else ref_price + self._slip(ref_price), 2)

    def fees(self, segment_key: str, side: str, qty: int, price: float) -> float:
        return float(self.cost.compute_leg(segment_key, side, qty, price)["total"])
