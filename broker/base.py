"""Broker abstraction (spec §8, Appendix B).

All broker calls go through this interface so the system stays broker-agnostic.
The concrete `KiteAdapter` implements it. Methods not needed until later phases
raise NotImplementedError in the skeleton and are filled in then.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class BrokerAdapter(ABC):
    # --- auth ---
    @abstractmethod
    def login(self) -> str:
        """Perform a fresh login, return + persist the access token."""

    @abstractmethod
    def refresh_token(self) -> str:
        """Refresh the daily access token (re-login). Return the new token."""

    # --- account / reference data ---
    @abstractmethod
    def margins(self, segment: str | None = None) -> dict:
        ...

    @abstractmethod
    def instruments(self, exchange: str | None = None) -> list[dict]:
        ...

    @abstractmethod
    def historical(
        self,
        instrument_token: int,
        from_dt: datetime,
        to_dt: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict]:
        ...

    # --- market data feed ---
    @abstractmethod
    def subscribe(self, tokens: list[int], mode: str = "quote") -> None:
        ...

    # --- order management ---
    @abstractmethod
    def place_order(self, **kwargs: Any) -> str:
        ...

    @abstractmethod
    def place_gtt(self, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def place_oco(self, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def modify_order(self, order_id: str, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, **kwargs: Any) -> Any:
        ...

    @abstractmethod
    def delete_gtt(self, trigger_id) -> Any:
        """Cancel a resting GTT/OCO trigger (used when a bracket's position closes)."""

    # --- portfolio / margin ---
    @abstractmethod
    def positions(self) -> dict:
        ...

    @abstractmethod
    def holdings(self) -> list[dict]:
        ...

    @abstractmethod
    def order_margins(self, orders: list[dict]) -> list[dict]:
        ...
