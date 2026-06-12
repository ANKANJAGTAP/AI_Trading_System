"""Execution-layer data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class OrderOutcome:
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


class ExitReason:
    STOP = "stop"
    TARGET = "target"
    TRAIL = "trailing_stop"
    TIME = "square_off_time"
    FAILSAFE = "failsafe"
    MANUAL = "manual"


@dataclass
class Decision:
    """A risk-approved trade to execute. Produced by the orchestrator (Phase 5)
    after the Risk Engine has sized it; the Executor never re-sizes."""

    correlation_id: str
    sleeve: str
    instrument: dict              # token, tradingsymbol, exchange, lot_size, instrument_type, segment
    side: str                     # BUY / SELL (entry side)
    quantity: int                 # risk-sized units (multiple of lot_size)
    order_type: str = "MARKET"    # MARKET / LIMIT
    entry_price: float = 0.0      # reference / limit price
    stop_price: float = 0.0
    target_price: float = 0.0
    product: str = "MIS"          # MIS / CNC / NRML
    r_rupees: float = 0.0
    confidence: float = 1.0
    signal_id: int | None = None


@dataclass
class Fill:
    quantity: int
    price: float
    fees: dict
    ts: datetime


@dataclass
class ExecutionResult:
    outcome: str                  # OrderOutcome.*
    decision: Decision
    filled_quantity: int = 0
    avg_price: float = 0.0
    fees_total: float = 0.0
    position_id: int | None = None
    broker_order_id: str | None = None
    reason: str | None = None
    bracket: dict | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class ExitSignal:
    reason: str                   # ExitReason.*
    price: float
    detail: dict = field(default_factory=dict)
