"""Shared enums used across the system."""
from __future__ import annotations

from enum import Enum


class Sleeve(str, Enum):
    INTRADAY_STOCKS = "intraday_stocks"
    FNO = "fno"
    SWING_STOCKS = "swing_stocks"
    MCX_COMMODITIES = "mcx_commodities"


class ExecutionMode(str, Enum):
    SIMULATED_FILL = "simulated_fill"
    LIVE = "live"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SLM = "SL-M"


class Product(str, Enum):
    MIS = "MIS"      # intraday
    CNC = "CNC"      # delivery / swing
    NRML = "NRML"    # F&O / MCX carry


class GateOutcome(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


class SignalDecision(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    FLAGGED = "flagged"   # cold-start: could not be safely reconstructed


class TickMode(str, Enum):
    LTP = "ltp"
    QUOTE = "quote"
    FULL = "full"
