"""SEBI retail-algo compliance helpers (P9; framework mandatory 2026-04-01).

The framework requires every LIVE order to carry the broker/exchange Algo-ID tag,
market orders to set market protection (0 is rejected), API access from a static
IP whitelisted at the broker over OAuth, and order throughput <= 10 OPS (above
which the strategy must be exchange-registered).

This module centralises the per-order params + the config-gap check. Static-IP
whitelisting, OAuth, and exchange registration are operator ops; the pre-live
checks verify they've been recorded. Pure (no I/O) so it's easy to unit-test.
"""
from __future__ import annotations

MAX_RETAIL_OPS = 10   # SEBI: <=10 orders/sec stays in the exempt "regular API" lane


def _cfg(config) -> dict:
    return dict(getattr(config.system, "compliance", {}) or {})


def order_tag(config) -> str | None:
    """Algo-ID tag to stamp on every live order (Kite `tag`, <=20 chars)."""
    t = _cfg(config).get("algo_id")
    return str(t)[:20] if t else None


def market_protection(config) -> float:
    """Market-order protection % (Kite rejects MARKET/SL-M with protection 0)."""
    return float(_cfg(config).get("market_protection_pct", 0) or 0)


def order_ops_limit(config) -> float:
    """Effective orders/sec the rate governor allows — the real OPS enforcement."""
    o = (getattr(config.data, "rate_limits", {}) or {}).get("order", {}) or {}
    return float(o.get("refill_per_sec", 0) or 0)


def live_order_params(config, order_type: str | None) -> dict:
    """Extra kwargs for a LIVE order: the Algo-ID tag always; market_protection for
    MARKET / SL-M orders (which the exchange otherwise rejects)."""
    params: dict = {}
    tag = order_tag(config)
    if tag:
        params["tag"] = tag
    if order_type in ("MARKET", "SL-M") and market_protection(config) > 0:
        params["market_protection"] = market_protection(config)
    return params


def compliance_gaps(config) -> list[str]:
    """Unmet compliance prerequisites for going live (empty list = ready)."""
    c = _cfg(config)
    gaps: list[str] = []
    if not c.get("algo_id"):
        gaps.append("algo_id (order tag) not set")
    if not c.get("static_ip"):
        gaps.append("static_ip not recorded (whitelist it at developers.kite.trade)")
    if market_protection(config) <= 0:
        gaps.append("market_protection_pct not set (market orders would be rejected)")
    ops = order_ops_limit(config)
    if (ops <= 0 or ops > MAX_RETAIL_OPS) and not c.get("exchange_registered"):
        gaps.append(f"order rate {ops}/s must be 1..{MAX_RETAIL_OPS} OPS unless exchange_registered")
    return gaps
