"""Typed errors for the live trading path (P0 series).

Centralised so the mode-transition service, pre-live checks, order lifecycle,
bracket reconciler, and broker adapter all raise/catch the same types instead of
bare Exceptions. Every one is a `TradingError` so a single `except TradingError`
can guard a code path that must fail closed.
"""
from __future__ import annotations


class TradingError(Exception):
    """Base class for all live-path trading errors."""


class ModeTransitionRejected(TradingError):
    """A paper<->live mode transition failed validation. Carries the reason list."""

    def __init__(self, reasons: list[str] | str):
        self.reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("; ".join(self.reasons) or "mode transition rejected")


class UnsafeLiveState(TradingError):
    """The system is in (or would enter) a live state that isn't safe to trade."""


class PartialFillTimeout(TradingError):
    """A live order neither completed nor confirmably cancelled within the window."""


class ReconciliationMismatch(TradingError):
    """Broker truth (positions/orders/funds) disagrees with the local book."""


class BrokerUnavailable(TradingError):
    """The broker API could not be reached / returned no usable answer."""


class OrderRejected(TradingError):
    """The broker rejected an order for a non-transient reason (margin/ban/etc.)."""
