"""
Indian F&O transaction-cost model.

For high-churn option strategies, statutory costs frequently ARE the strategy's
P&L, so the backtester models them to the rupee. Rates change (e.g. the Oct-2024
STT hike), so they live in a CostConfig with documented defaults flagged
`verify` — confirm against your broker's latest contract note before relying on
absolute numbers. Defaults reflect NSE, post-Oct-2024.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostConfig:
    # brokerage per executed order (discount-broker style; set 0 for zero-brokerage)
    brokerage_per_order: float = 20.0
    # STT (Securities Transaction Tax) — SELL side only
    opt_stt_sell: float = 0.0010      # 0.10% of premium (post Oct-2024)
    fut_stt_sell: float = 0.0002      # 0.02% of turnover (post Oct-2024)
    # exchange transaction charges (NSE defaults; BSE/Sensex differ — override)
    opt_exch_txn: float = 0.0003503   # ~0.03503% of premium
    fut_exch_txn: float = 0.0000173   # ~0.00173% of turnover
    # SEBI turnover fee: Rs 10 per crore
    sebi: float = 0.000001
    # stamp duty — BUY side only
    opt_stamp_buy: float = 0.00003    # 0.003%
    fut_stamp_buy: float = 0.00002    # 0.002%
    gst: float = 0.18                 # on (brokerage + exchange txn + SEBI)
    verify: bool = True               # confirm rates vs current circulars


def leg_cost(price: float, qty: int, side: str, segment: str,
             cfg: CostConfig = CostConfig()) -> dict:
    """Cost breakdown for one executed leg. side in {BUY,SELL}; segment in {OPT,FUT}."""
    side = side.upper()
    segment = segment.upper()
    turnover = abs(price) * abs(qty)

    brokerage = cfg.brokerage_per_order
    if segment == "OPT":
        stt = cfg.opt_stt_sell * turnover if side == "SELL" else 0.0
        exch = cfg.opt_exch_txn * turnover
        stamp = cfg.opt_stamp_buy * turnover if side == "BUY" else 0.0
    elif segment == "FUT":
        stt = cfg.fut_stt_sell * turnover if side == "SELL" else 0.0
        exch = cfg.fut_exch_txn * turnover
        stamp = cfg.fut_stamp_buy * turnover if side == "BUY" else 0.0
    else:
        raise ValueError(f"segment must be OPT or FUT, got {segment!r}")

    sebi = cfg.sebi * turnover
    gst = cfg.gst * (brokerage + exch + sebi)
    total = brokerage + stt + exch + sebi + stamp + gst
    return {
        "brokerage": brokerage, "stt": stt, "exch": exch, "sebi": sebi,
        "stamp": stamp, "gst": gst, "total": total, "turnover": turnover,
    }


def round_trip_cost(price_in: float, price_out: float, qty: int, side_in: str,
                    segment: str, cfg: CostConfig = CostConfig()) -> float:
    """Total cost of entering and exiting one leg (exit side is the opposite)."""
    side_out = "SELL" if side_in.upper() == "BUY" else "BUY"
    return (leg_cost(price_in, qty, side_in, segment, cfg)["total"]
            + leg_cost(price_out, qty, side_out, segment, cfg)["total"])
