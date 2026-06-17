# AI Trading System — Consolidated Roadmap

Single source of truth for what's done, what's left, and the order to do it in.
Merges `upgrade.md` (safety ladder) + `WORLDCLASS_FNO_PLATFORM_PLAN.md` (institutional build).

**Legend:** ✅ done · 🟡 partial · ⬜ todo · 🔒 blocks real-live-trading

---

## 0. Done (this build)

- ✅ **P0 #1–7** — atomic execution mode, real pre-live checks, live exit-product handling, broker-fill-truth close accounting, safe partial fills, live F&O structures disabled (fail-closed), hardened GTT/OCO + stops.
- ✅ **P1 #8–14** — mode/account scoping, fail-closed risk deps, venue-aware sessions, broker reconciliation loop, durable command queue, engine heartbeat, atomic kill-switch gate.
- ✅ **P9** — SEBI-2026 algo compliance (Algo-ID tagging, market protection, OPS limiter, static-IP/OAuth gate, audit).
- ✅ **Pillar 1 (data platform)** — contract/expiry resolver, bhavcopy EOD lake, Timescale schema, quality jobs, research API.
- ✅ **Ops** — daily health digest, F&O Research + Pre-Live Readiness dashboard screens.
- ✅ Migrations 0013–0021 applied; 270 tests green; paper-mode live on AWS.

---

## 1. 🔒 The hard gate before any *real* live trade

These are the only things that stand between "paper on AWS" and "transacting real capital."

- ⬜ 🔒 **Real Kite broker adapter** — `broker/kite_adapter.py` is a skeleton: auth/token refresh work; `place_order`, `positions`, `historical`, `quote`, websocket `subscribe`, GTT/OCO all raise `NotImplementedError`. Fill in + contract-test against Kite. *(maps to upgrade #37 + world-class Phase 1/5)*
- ⬜ 🔒 **Rotate leaked secrets** — Kite key/secret + DB password were exposed in plaintext earlier. Rotate at the source (Kite console / DB) — **user action**, Claude cannot enter credentials.
- ⬜ 🔒 **Live market-data feed** — real-time websocket tick stream + per-venue feed health (depends on the adapter).

---

## 2. Security hardening — *do now (cheap, high value, paper-safe)*

- 🟡 **#22 Lock down infra defaults** — DB/Redis bound to localhost; opt-in Redis password; prod vs local compose. *(IN PROGRESS)*
- ⬜ **#21 Harden secrets** — require token-encryption key in non-local; key rotation; token-age in pre-live checks; never log tokens; CI secret scanner.
- ⬜ **#20 WS tokens out of query strings** — header/short-lived session tokens; expiry; redact from logs.
- ⬜ **#19 API roles/scopes** — read-only / operator / trader / admin; stronger auth for live-enable, kill-switch, flatten, config; rate-limit sensitive endpoints. *(backward-compatible: single token = admin)*

---

## 3. Data integrity & audit

- ⬜ **#15 DB constraints** — CHECK (qty>0, valid side/status/mode/product/exchange), NOT NULL, FKs, unique broker-order-id / idempotency-key.
- ⬜ **#16 Migration drift detection** — fail startup if an applied migration's checksum changed; `migrate status` command; CI immutability check.
- 🟡 **#17 Event-sourced positions** — `position_events` exists (P0#4); extend to derive state from events + rebuild/audit.
- ⬜ **#18 Compliance-grade audit** — hash-chained rows, actor/IP/request/command/correlation IDs, signed daily digest, no short retention.

## 4. Backtest & research validity

- ⬜ **#23 Historical option-chain backtests** — real bid/ask/OI/IV/Greeks (replace modeled proxies); liquidity filters; expiry effects.
- ⬜ **#24 Align backtest & live params** — shared config, persisted config hash per run, mismatch test.
- ⬜ **#25 Execution realism** — slippage/gap-through-stop/rejection/rate-limit/fee models; freeze-qty rules.
- ⬜ **#26 Walk-forward + OOS** — train/val/test by time, regime buckets, parameter-stability + decay kill criteria.
- ⬜ **#27 Meta-label discipline** — keep model off until min sample/class-balance; dataset-quality + leakage report; model versioning + rollback.

## 5. Feed, data & scalability

- ⬜ **#28 Bound tick queues** — max size + backpressure (never drop lifecycle events; coalesce ticks per symbol); lag metrics.
- ⬜ **#29 Market-data quality gates** — stale/zero/negative/jump/crossed-quote validators; block entries on poor data.
- ⬜ **#30 Instrument-metadata cache** — versioned master (lot/tick/freeze/expiry), validate orders pre-submit, stale alert.

## 6. API & dashboard

- ⬜ **#31 API safety boundaries** — request schemas, idempotency on destructive cmds (partly via durable commands), scopes, audit, return command-id, OpenAPI.
- 🟡 **#32 Truthful live-readiness UI** — Pre-Live Readiness screen exists; add per-venue feed, pending commands, unprotected positions, last backup test; disable live controls unless ready + scoped.

## 7. DevOps, CI & release safety

- ⬜ **#33 CI pipeline** — run the test suite, lint, type-check, migration-immutability, secret scan on every push.
- ⬜ **#34 Pin & scan runtime images** — pinned base digests + vulnerability scan.
- ⬜ **#35 Backup & restore flow** — automated DB backups + tested restore drill.
- ⬜ **#36 Deploy & rollback discipline** — versioned releases, one-command rollback (replaces ad-hoc scp).

## 8. Testing expansion

- ⬜ **#37 Broker-adapter contract tests** (pairs with the live adapter) · **#38 e2e paper replay** · **#39 broker-mock lifecycle sim** · **#40 chaos tests** · **#41 property-based risk tests**.

## 9. Docs & cleanup

- ⬜ **#42 README-to-reality** · **#43 runbooks** · **#44 risk-policy doc** · **#45 prune cache files** · **#46 typing at boundaries** · **#47 standard error types**.

---

## 10. The bigger build — world-class plan, Phases 2–7 (where the *edge* is made)

- ⬜ **Phase 2 — Research & validation** *(highest leverage)*: triple-barrier + meta-labeling + sample weighting; **CPCV + Deflated Sharpe + PBO** harness; MLflow registry (dev→shadow→paper→live).
- ⬜ **Phase 3 — Backtest engine**: event-driven options engine + SPAN-style margin; Greeks-attributed P&L; scenario/stress/Monte-Carlo.
- ⬜ **Phase 4 — Strategy/signal engine**: 7-step pipeline, per-index structure selection, IV/GEX routing, microstructure confirmation.
- ⬜ **Phase 5 — Execution/risk**: options-portfolio Greeks limits, scenario-VaR gate, pin/expiry control.
- ⬜ **Phase 6 — Compliance + paper-live + UX**: visual strategy builder, payoff/Greeks, sustained paper across full expiry cycles.
- ⬜ **Phase 7 — Controlled live**: tiny capital, one index/strategy, scale only on evidence.
- ⬜ **Data fuel (cross-cutting)**: paid 1-min options vendor (`dataplatform/vendors/bar_vendor.py` is a stub); `strategies/providers.py` fundamentals + ban-list are stubs.

---

## Recommended execution order

1. **Security tier (§2)** — now. Cheap, paper-safe, removes default-credential exposure.
2. **Phase 2 validation harness (§10)** — *the highest-leverage build*. The plan's rule is data → **validation** → backtest → strategy → execution → live. Trust a strategy before risking it.
3. **Data integrity + feed/scale (§3, §5)** — reliability backbone.
4. **Live-hardening track (§1 adapter + §4 backtest realism + §8 contract tests)** — only when going live actually means something.
5. **DevOps/CI (§7) + docs (§9)** — fold in continuously.

> Sequencing rule (from the world-class plan): *never let strategy enthusiasm outrun data/validation maturity.* Going live without §10 Phase 2 is how good backtests become real losses.
