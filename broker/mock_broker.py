"""Deterministic broker lifecycle simulator (#39).

A dependency-light fake that implements the `BrokerAdapter` order-management
surface with a *scriptable* Kite-shaped order lifecycle. `place_order()` registers
an order and returns an order_id; `order_history()` returns the broker's status
progression exactly as Kite does — a list of state dicts, oldest first — advancing
one step per call. This lets the broker contract tests (#37) and a future paper
replay (#38) drive the executor's fill-truth and lifecycle logic through every
real-world scenario with **no live Kite connection, no DB, and no `kiteconnect`
import** — fully deterministic.

Status vocabulary matches Kite and the system's `normalize_exit_status()`:
`OPEN` (working, possibly part-filled) / `COMPLETE` / `REJECTED` / `CANCELLED`,
with `filled_quantity` / `pending_quantity` / `average_price` on every state.

Scenarios (pass `scenario=` to `place_order`, or set `default_scenario`):

    complete               OPEN -> COMPLETE(full)
    partial_then_complete  OPEN(half) -> COMPLETE(full)
    partial_then_stuck     OPEN(half) -> OPEN(half) ...        (never completes)
    rejected               OPEN -> REJECTED(0)
    no_fill                OPEN(0) -> OPEN(0) ...              (never fills)

A working order (any scenario) can be terminated with `cancel_order()`, which
moves it to `CANCELLED` keeping whatever quantity had already filled — exactly the
partial-fill-then-cancel case the live executor must survive.
"""
from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any

from broker.base import BrokerAdapter

OPEN = "OPEN"
COMPLETE = "COMPLETE"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
_TERMINAL = frozenset({COMPLETE, REJECTED, CANCELLED})

SCENARIOS = frozenset(
    {"complete", "partial_then_complete", "partial_then_stuck", "rejected", "no_fill"}
)


class _Order:
    def __init__(self, oid: str, scenario: str, kw: dict) -> None:
        self.oid = oid
        self.scenario = scenario
        self.symbol = kw.get("tradingsymbol", "MOCK")
        self.exchange = kw.get("exchange", "NSE")
        self.side = kw.get("transaction_type", "BUY")
        self.qty = int(kw.get("quantity", 0) or 0)
        self.ref_price = float(kw.get("price", 0.0) or 0.0)
        self.product = kw.get("product", "MIS")
        self.order_type = kw.get("order_type", "MARKET")
        self.status = OPEN
        self.filled = 0
        self.avg_price = 0.0
        self.polls = 0
        self.history: list[dict] = []
        self._snapshot()  # initial OPEN(0) state, as Kite records on receipt

    def _snapshot(self) -> None:
        pending = 0 if self.status in _TERMINAL else self.qty - self.filled
        self.history.append({
            "order_id": self.oid,
            "status": self.status,
            "tradingsymbol": self.symbol,
            "exchange": self.exchange,
            "transaction_type": self.side,
            "quantity": self.qty,
            "filled_quantity": self.filled,
            "pending_quantity": max(0, pending),
            "average_price": round(self.avg_price, 2),
            "product": self.product,
            "order_type": self.order_type,
            "order_timestamp": datetime(2026, 1, 1).isoformat(),
        })


class MockBroker(BrokerAdapter):
    """Scriptable, deterministic Kite-shaped order lifecycle. No I/O."""

    def __init__(self, *, default_scenario: str = "complete",
                 fill_price: float = 100.0) -> None:
        if default_scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {default_scenario!r}")
        self.default_scenario = default_scenario
        self.fill_price = float(fill_price)
        self._ids = itertools.count(1)
        self._orders: dict[str, _Order] = {}
        self._gtt_ids = itertools.count(1)
        self._gtts: dict[int, dict] = {}
        self._ltp: dict[str, float] = {}

    # ---- helpers for tests ------------------------------------------------
    def set_ltp(self, symbol: str, price: float) -> None:
        self._ltp[symbol] = float(price)

    def _px(self, o: _Order) -> float:
        return o.ref_price or self._ltp.get(o.symbol) or self.fill_price

    def latest(self, order_id: str) -> dict:
        """Most recent broker state for an order (what a poll would read)."""
        return dict(self._orders[order_id].history[-1])

    def net_quantity(self, symbol: str) -> int:
        """Signed net position from filled quantity (BUY +, SELL -)."""
        net = 0
        for o in self._orders.values():
            if o.symbol == symbol and o.filled > 0:
                net += o.filled if o.side == "BUY" else -o.filled
        return net

    # ---- order lifecycle engine ------------------------------------------
    def _advance(self, o: _Order) -> None:
        if o.status in _TERMINAL:
            return
        o.polls += 1
        half = max(1, o.qty // 2) if o.qty else 0
        px = self._px(o)
        if o.scenario == "complete":
            o.status, o.filled, o.avg_price = COMPLETE, o.qty, px
        elif o.scenario == "rejected":
            o.status, o.filled, o.avg_price = REJECTED, 0, 0.0
        elif o.scenario == "no_fill":
            o.status, o.filled = OPEN, 0           # works forever, never fills
        elif o.scenario == "partial_then_stuck":
            o.status, o.filled, o.avg_price = OPEN, half, px   # stuck part-filled
        elif o.scenario == "partial_then_complete":
            if o.polls == 1:
                o.status, o.filled, o.avg_price = OPEN, half, px
            else:
                o.status, o.filled, o.avg_price = COMPLETE, o.qty, px
        o._snapshot()

    # ---- BrokerAdapter: order management ---------------------------------
    def place_order(self, **kwargs: Any) -> str:
        scenario = kwargs.pop("scenario", self.default_scenario)
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        oid = f"MOCK{next(self._ids):06d}"
        self._orders[oid] = _Order(oid, scenario, kwargs)
        return oid

    def order_history(self, order_id: str) -> list[dict]:
        o = self._orders[order_id]
        self._advance(o)
        return [dict(s) for s in o.history]

    def orders(self) -> list[dict]:
        return [dict(o.history[-1]) for o in self._orders.values()]

    def cancel_order(self, order_id: str, **kwargs: Any) -> Any:
        o = self._orders[order_id]
        if o.status not in _TERMINAL:
            o.status = CANCELLED          # keep o.filled (partial-then-cancel)
            o._snapshot()
        return order_id

    def modify_order(self, order_id: str, **kwargs: Any) -> Any:
        o = self._orders[order_id]
        if "price" in kwargs:
            o.ref_price = float(kwargs["price"] or 0.0)
        return order_id

    def place_gtt(self, **kwargs: Any) -> Any:
        tid = next(self._gtt_ids)
        self._gtts[tid] = dict(kwargs)
        return tid

    def place_oco(self, **kwargs: Any) -> Any:
        return self.place_gtt(**kwargs)

    def delete_gtt(self, trigger_id) -> Any:
        self._gtts.pop(trigger_id, None)
        return {"trigger_id": trigger_id}

    def gtts(self) -> list[dict]:
        return [{"id": k, **v} for k, v in self._gtts.items()]

    # ---- BrokerAdapter: portfolio / account / reference ------------------
    def positions(self) -> dict:
        net: dict[str, dict] = {}
        for o in self._orders.values():
            if o.filled <= 0:
                continue
            row = net.setdefault(o.symbol, {
                "tradingsymbol": o.symbol, "exchange": o.exchange,
                "product": o.product, "quantity": 0, "average_price": o.avg_price,
            })
            row["quantity"] += o.filled if o.side == "BUY" else -o.filled
        return {"net": list(net.values()), "day": list(net.values())}

    def holdings(self) -> list[dict]:
        return []

    def margins(self, segment: str | None = None) -> dict:
        pot = {"net": 1_000_000.0, "available": {"cash": 1_000_000.0, "live_balance": 1_000_000.0}}
        return pot if segment else {"equity": pot, "commodity": pot}

    def order_margins(self, orders: list[dict]) -> list[dict]:
        out = []
        for od in orders:
            qty = float(od.get("quantity", 0) or 0)
            px = float(od.get("price", 0) or self.fill_price)
            out.append({"total": round(qty * px * 0.2, 2)})   # ~20% span+exposure
        return out

    def quote(self, instruments) -> dict:
        keys = instruments if isinstance(instruments, list) else [instruments]
        return {str(k): {"last_price": self._ltp.get(str(k), self.fill_price)} for k in keys}

    def ltp(self, instruments) -> dict:
        return self.quote(instruments)

    def instruments(self, exchange: str | None = None) -> list[dict]:
        return []

    def historical(self, instrument_token: int, from_dt: datetime, to_dt: datetime,
                   interval: str, continuous: bool = False, oi: bool = False) -> list[dict]:
        return []

    # ---- BrokerAdapter: auth / feed (no-op in the sim) -------------------
    def login(self) -> str:
        return "MOCK_TOKEN"

    def refresh_token(self) -> str:
        return "MOCK_TOKEN"

    def subscribe(self, tokens: list[int], mode: str = "quote") -> None:
        return None
