# SEBI Retail-Algo Compliance (P9)

SEBI's retail algorithmic-trading framework (circular Feb 2025, **mandatory
2026-04-01**) makes the broker the *principal* and any algo running through its
API the broker's *agent*. For a self-run algo on Zerodha Kite below 10 OPS you're
a "regular API user" (no mandatory exchange registration), but order tagging,
static-IP/OAuth access, and market protection are required regardless.

## What the code does (implemented)

| Requirement | Implementation |
|---|---|
| **Algo-ID on every live order** | `common/compliance.live_order_params()` stamps `tag=<algo_id>` on every live `place_order` (entry clips, `market_exit`, and both OCO bracket legs). Config: `system.compliance.algo_id` (≤20 chars). |
| **Market protection** | MARKET / SL-M orders get `market_protection=<pct>` (Kite rejects 0). Config: `system.compliance.market_protection_pct` (default 1.0). Applies to the P0#7 stop-market leg too. |
| **≤ 10 OPS (exempt lane)** | The order rate governor is capped at **8 orders/sec** (`data.rate_limits.order.refill_per_sec`), with a per-minute/daily order-count guard. Below SEBI's 10-OPS threshold, so no exchange registration is required. |
| **Pre-live gate** | The `sebi_compliance` pre-live check (`api/prelive_checks.py`) FAILS the go-live transition until `algo_id`, `static_ip`, and `market_protection_pct` are set and OPS ≤ 10 (or `exchange_registered=true`). |
| **Audit trail** | Every order/fill/decision is already logged under one `correlation_id` (`audit_log`, `orders`, `fills`, and the new append-only `position_events`), with the algo tag on each order. |
| **OAuth-only auth** | Kite Connect is OAuth (request-token → session) already; no other login path is used. |

## What you must do (operator ops)

1. **Whitelist the static IP** of the EC2 host (`43.205.112.232`) at
   `developers.kite.trade` → profile → *IP Whitelist*. Orders from any other IP
   are rejected. Record it in `system.compliance.static_ip`.
2. **Set the Algo-ID** the broker/exchange assigns into `system.compliance.algo_id`.
3. **Keep OPS ≤ 10.** If you ever raise `data.rate_limits.order` above 10/s, you
   must register the strategy with the exchange and set
   `system.compliance.exchange_registered: true`.
4. **Re-run the pre-live checks** (`GET /api/prelive-checklist`); the
   `sebi_compliance` check must pass before flipping to live.

## Config (`config/system.yaml`)

```yaml
compliance:
  algo_id: ""                  # exchange/broker Algo-ID (<=20 chars)
  static_ip: ""                # the whitelisted static IP
  market_protection_pct: 1.0   # market/SL-M protection %
  exchange_registered: false   # only if running > 10 OPS
```

## Sources

- [SEBI algo-trading rules 2026 (Sahi)](https://www.sahi.com/blogs/sebi-algo-trading-rules-2026-what-every-retail-trader-must-know-before-april)
- [NSE retail algo framework overview (Z-Connect, Zerodha)](https://zerodha.com/z-connect/general/a-comprehensive-overview-of-nses-circular-on-the-new-retail-algo-trading-framework)
- [Kite Connect: preparing for SEBI retail algo rules (static IP, ratelimits, order types)](https://kite.trade/forum/discussion/15912/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types)
- [SEBI retail algo guidelines (FinSec)](https://www.finseclaw.com/article/finsec-tracker-on-sebi-issues-guidelines-on-retail-participation-in-algorithmic-trading)
