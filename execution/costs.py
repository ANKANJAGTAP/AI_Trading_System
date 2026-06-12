"""Cost model (spec §8) — always on in both modes so the live transition holds no
surprises. Brokerage, STT/CTT, exchange txn, SEBI, stamp duty, GST per leg, using
the rates in config/execution.yaml. Indian-market side rules:

- brokerage: per leg (flat, or pct capped)
- STT: equity delivery -> both legs; intraday / F&O / futures -> SELL leg
- CTT (commodity): SELL leg
- exchange txn + SEBI: both legs
- stamp duty: BUY leg only
- GST: 18% on (brokerage + txn + SEBI)
"""
from __future__ import annotations


class CostModel:
    def __init__(self, cost_config: dict) -> None:
        self.cm = cost_config or {}

    @staticmethod
    def segment_key(sleeve: str, instrument_type: str | None) -> str:
        itype = (instrument_type or "").upper()
        if sleeve == "fno":
            return "fno_options" if itype in ("CE", "PE") else "fno_futures"
        if sleeve == "mcx_commodities":
            return "mcx_futures"
        if sleeve == "swing_stocks":
            return "equity_delivery"
        return "equity_intraday"

    def compute_leg(self, segment_key: str, side: str, quantity: int, price: float) -> dict:
        c = self.cm.get(segment_key, {})
        turnover = quantity * price
        side = side.upper()

        if "brokerage_flat" in c:
            brokerage = float(c["brokerage_flat"])
        else:
            raw = turnover * float(c.get("brokerage_pct", 0)) / 100.0
            cap = c.get("brokerage_flat_cap")
            brokerage = min(raw, float(cap)) if cap else raw

        stt_pct = float(c.get("stt_pct", 0))
        if segment_key == "equity_delivery":
            stt = turnover * stt_pct / 100.0
        elif side == "SELL":
            stt = turnover * stt_pct / 100.0
        else:
            stt = 0.0
        if "ctt_pct" in c and side == "SELL":
            stt += turnover * float(c["ctt_pct"]) / 100.0

        txn = turnover * float(c.get("exchange_txn_pct", 0)) / 100.0
        sebi = turnover * float(c.get("sebi_per_cr", 0)) / 1e7
        stamp = turnover * float(c.get("stamp_pct", 0)) / 100.0 if side == "BUY" else 0.0
        gst = (brokerage + txn + sebi) * float(c.get("gst_pct", 0)) / 100.0

        total = brokerage + stt + txn + sebi + stamp + gst
        return {
            "brokerage": round(brokerage, 2), "stt": round(stt, 2), "txn": round(txn, 4),
            "sebi": round(sebi, 4), "stamp": round(stamp, 2), "gst": round(gst, 2),
            "total": round(total, 2),
        }

    def round_trip_cost(self, segment_key: str, qty: int, entry: float, exit_price: float) -> float:
        """Total cost of a long round trip (buy entry + sell exit)."""
        buy = self.compute_leg(segment_key, "BUY", qty, entry)["total"]
        sell = self.compute_leg(segment_key, "SELL", qty, exit_price)["total"]
        return round(buy + sell, 2)
