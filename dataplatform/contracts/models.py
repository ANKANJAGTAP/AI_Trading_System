"""Data models for effective-dated contract specifications."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class SpecRecord:
    """A single effective-dated attribute value for an underlying.

    The resolver answers "what was <attribute> for <underlying> on <date>?",
    so a rule change (lot size, fee, tick) is a data row, not a code change.
    """
    underlying: str
    attribute: str            # e.g. 'lot_size', 'tick_size', 'multiplier'
    value: str                # stored as text; cast on read
    valid_from: dt.date
    valid_to: dt.date | None  # None = current
    source: str = "seed"
    verify: bool = True       # True until confirmed against an official circular

    def active_on(self, d: dt.date) -> bool:
        if d < self.valid_from:
            return False
        return self.valid_to is None or d <= self.valid_to


def cast(attribute: str, value: str):
    """Cast a stored text value to its natural Python type."""
    int_attrs = {"lot_size"}
    float_attrs = {"tick_size", "multiplier"}
    bool_attrs = {"weekly_available"}
    if attribute in int_attrs:
        return int(value)
    if attribute in float_attrs:
        return float(value)
    if attribute in bool_attrs:
        return value.lower() in ("1", "true", "yes")
    return value
