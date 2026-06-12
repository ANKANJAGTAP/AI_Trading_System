"""Concrete Kite Connect implementation of BrokerAdapter (Phase 0 skeleton).

Phase 0 implements: auth (TOTP login + daily refresh), token caching, and the
read-only reference/account calls needed for acceptance (margins, instruments,
positions, holdings, order_margins). Feed and order-management methods are wired
in Phase 1 / Phase 3 and currently raise NotImplementedError with the phase note.

All REST calls will be routed through the rate-limit governor in Phase 1; for now
they are direct thin pass-throughs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from kiteconnect import KiteConnect

from broker.auth import kite_auto_login
from broker.base import BrokerAdapter
from broker.token_store import TokenStore
from common.alerts import Alerter
from common.logging import get_logger
from config.settings import Settings, get_settings

log = get_logger("kite_adapter")


class KiteAdapter(BrokerAdapter):
    def __init__(self, settings: Settings | None = None, alerter: Alerter | None = None) -> None:
        self.s = settings or get_settings()
        self.kite = KiteConnect(api_key=self.s.kite_api_key)
        self.token_store = TokenStore(self.s.token_store_path, self.s.token_encryption_key)
        self.alerter = alerter or Alerter(self.s)
        self._access_token: str | None = None
        self.ticker = None  # KiteTicker — wired in Phase 1

    # --- auth -------------------------------------------------------------
    def ensure_token(self) -> str:
        """Use today's cached token if present, otherwise log in."""
        token = self.token_store.valid_token_for_today()
        if token:
            self._access_token = token
            self.kite.set_access_token(token)
            log.info("token_loaded_from_cache")
            return token
        return self.login()

    def login(self) -> str:
        try:
            token = kite_auto_login(
                self.s.kite_api_key,
                self.s.kite_api_secret,
                self.s.kite_user_id,
                self.s.kite_password,
                self.s.kite_totp_secret,
            )
            self._access_token = token
            self.kite.set_access_token(token)
            self.token_store.save(token)
            log.info("token_refreshed")
            return token
        except Exception as exc:
            log.error("kite_login_failed", error=str(exc))
            # Fail safe: never trade on a stale/failed token — alert the operator.
            self.alerter.send(
                "Kite auth FAILED",
                f"Automated TOTP login failed: {exc}\n"
                "The system will NOT trade live with a stale token. "
                "Manual intervention required.",
            )
            raise

    def refresh_token(self) -> str:
        return self.login()

    # --- account / reference data ----------------------------------------
    def margins(self, segment: str | None = None) -> dict:
        return self.kite.margins(segment) if segment else self.kite.margins()

    def instruments(self, exchange: str | None = None) -> list[dict]:
        return self.kite.instruments(exchange) if exchange else self.kite.instruments()

    def positions(self) -> dict:
        return self.kite.positions()

    def holdings(self) -> list[dict]:
        return self.kite.holdings()

    def order_margins(self, orders: list[dict]) -> list[dict]:
        return self.kite.order_margins(orders)

    def basket_order_margins(self, orders: list[dict]) -> dict:
        """Hedge-aware margin for a multi-leg basket (spread benefit included).
        Falls back to summing per-order margins on older kiteconnect versions —
        conservative (no hedge benefit), which can only under-size, never over-size."""
        fn = getattr(self.kite, "basket_order_margins", None)
        if fn is not None:
            return fn(orders, consider_positions=True)
        legs = self.kite.order_margins(orders)
        total = sum(float(leg.get("total") or 0) for leg in legs)
        return {"final": {"total": total}, "initial": {"total": total}}

    # --- deferred to later phases ----------------------------------------
    def historical(
        self,
        instrument_token: int,
        from_dt: datetime,
        to_dt: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict]:
        return self.kite.historical_data(
            instrument_token, from_dt, to_dt, interval, continuous=continuous, oi=oi
        )

    def make_ticker(self):
        """Create a KiteTicker bound to the current access token. The FeedManager
        owns the callbacks and lifecycle."""
        from kiteconnect import KiteTicker

        if not self._access_token:
            self.ensure_token()
        self.ticker = KiteTicker(self.s.kite_api_key, self._access_token)
        return self.ticker

    def subscribe(self, tokens: list[int], mode: str = "quote") -> None:
        if self.ticker is None:
            self.make_ticker()
        mode_const = getattr(self.ticker, f"MODE_{mode.upper()}", self.ticker.MODE_QUOTE)
        self.ticker.subscribe(tokens)
        self.ticker.set_mode(mode_const, tokens)

    def place_order(self, **kwargs: Any) -> str:
        kwargs.setdefault("variety", "regular")
        return self.kite.place_order(**kwargs)

    def place_gtt(self, **kwargs: Any) -> Any:
        return self.kite.place_gtt(**kwargs)

    def place_oco(self, *, tradingsymbol: str, exchange: str, last_price: float,
                  lower_trigger: float, upper_trigger: float, orders: list[dict]) -> Any:
        """Two-leg GTT-OCO bracket (stop + target). trigger_values must be ascending."""
        return self.kite.place_gtt(
            trigger_type=self.kite.GTT_TYPE_OCO, tradingsymbol=tradingsymbol, exchange=exchange,
            trigger_values=[lower_trigger, upper_trigger], last_price=last_price, orders=orders,
        )

    def modify_order(self, order_id: str, **kwargs: Any) -> Any:
        kwargs.setdefault("variety", "regular")
        return self.kite.modify_order(order_id=order_id, **kwargs)

    def cancel_order(self, order_id: str, **kwargs: Any) -> Any:
        return self.kite.cancel_order(variety=kwargs.pop("variety", "regular"), order_id=order_id)

    def delete_gtt(self, trigger_id) -> Any:
        return self.kite.delete_gtt(trigger_id)

    # --- read helpers (used by execution, recovery, reconciliation) ---
    def quote(self, instruments) -> dict:
        return self.kite.quote(instruments)

    def ltp(self, instruments) -> dict:
        return self.kite.ltp(instruments)

    def orders(self) -> list[dict]:
        return self.kite.orders()

    def order_history(self, order_id: str) -> list[dict]:
        return self.kite.order_history(order_id)

    def gtts(self) -> list[dict]:
        return self.kite.get_gtts()
