"""Effective-dated contract-spec resolver — the single source of truth for
'what was this attribute on this date?'. Used by sizing, cost and backtest code."""
from __future__ import annotations

import datetime as dt

from .models import SpecRecord, cast
from .seed import SEED_SPECS


class ContractSpecResolver:
    def __init__(self, specs: list[SpecRecord] | None = None):
        self.specs = specs if specs is not None else list(SEED_SPECS)

    def as_of(self, underlying: str, attribute: str, on: dt.date):
        """Return the value of `attribute` for `underlying` effective on `on`.

        Raises KeyError if no record covers that date (fail loud — never guess).
        """
        candidates = [
            s for s in self.specs
            if s.underlying == underlying and s.attribute == attribute and s.active_on(on)
        ]
        if not candidates:
            raise KeyError(
                f"No spec for {underlying}.{attribute} as of {on} "
                f"(add an effective-dated SpecRecord)."
            )
        # most specific = latest valid_from among matches
        rec = max(candidates, key=lambda s: s.valid_from)
        return cast(attribute, rec.value)

    def lot_size(self, underlying: str, on: dt.date) -> int:
        return self.as_of(underlying, "lot_size", on)

    def tick_size(self, underlying: str, on: dt.date) -> float:
        return self.as_of(underlying, "tick_size", on)

    def weekly_available(self, underlying: str, on: dt.date) -> bool:
        return self.as_of(underlying, "weekly_available", on)

    def unverified(self) -> list[SpecRecord]:
        """Records still flagged verify=True — surface these in a setup report."""
        return [s for s in self.specs if s.verify]
