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

- ✅ **#22 Lock down infra defaults** — DB/Redis bound to localhost; opt-in Redis password; prod vs local compose.
- ✅ **#21 Harden secrets** — token-encryption key required in non-local; token-age in pre-live checks; redaction processor (never log tokens); CI secret scanner.
- ✅ **#20 WS tokens out of query strings** — subprotocol/header tokens; redacted from logs.
- ✅ **#19 API roles/scopes** — read-only / operator / trader / admin; scoped live-enable, kill-switch, flatten, config; rate-limited sensitive endpoints. *(backward-compatible: single token = admin)*

---

## 3. Data integrity & audit

- ✅ **#15 DB constraints** — NOT VALID CHECKs (qty>0, valid side/status/mode/product/exchange) + `audit_digests` (migration 0022); safe-on-live (no scan/lock).
- ✅ **#16 Migration drift detection** — checksum drift detected on startup (warn by default, raise under `migration_strict`); `python -m migrations.runner status`.
- 🟡 **#17 Event-sourced positions** — `position_events` exists (P0#4); extend to derive state from events + rebuild/audit.
- ✅ **#18 Compliance-grade audit** — hash-chained row fingerprints + `compute_and_store_daily_digest` (tamper-evident daily digest).

## 4. Backtest & research validity

- ⬜ **#23 Historical option-chain backtests** — real bid/ask/OI/IV/Greeks (replace modeled proxies); liquidity filters; expiry effects.
- ⬜ **#24 Align backtest & live params** — shared config, persisted config hash per run, mismatch test.
- ⬜ **#25 Execution realism** — slippage/gap-through-stop/rejection/rate-limit/fee models; freeze-qty rules.
- ⬜ **#26 Walk-forward + OOS** — train/val/test by time, regime buckets, parameter-stability + decay kill criteria.
- ⬜ **#27 Meta-label discipline** — keep model off until min sample/class-balance; dataset-quality + leakage report; model versioning + rollback.

## 5. Feed, data & scalability

- 🟡 **#28 Bound tick queues** — `CoalescingTickBuffer` ready (bounded, latest-per-symbol, coalesced/evicted counters); wires in with the live ticker (no live tick queue yet).
- ✅ **#29 Market-data quality gates** — `validate_tick` (stale/zero/negative/jump/crossed-quote) live in the engine LTP handler; bad ticks dropped.
- ✅ **#30 Instrument-metadata cache** — `validate_order_against_meta` (lot/tick/expiry) gates live entries in the executor; freeze handled by the slicer.

## 6. API & dashboard

- ✅ **#31 API safety boundaries** — scoped + rate-limited + audited control endpoints; optional `Idempotency-Key` header dedupes destructive cmds and returns the command-id.
- 🟡 **#32 Truthful live-readiness UI** — Pre-Live Readiness screen exists; add per-venue feed, pending commands, unprotected positions, last backup test; disable live controls unless ready + scoped.

## 7. DevOps, CI & release safety

- ✅ **#33 CI pipeline** — GitHub Actions runs the suite + secret scan on every push/PR; FastAPI/uvicorn pinned to avoid the starlette route-registration break.
- ✅ **#34 Pin & scan runtime images** — base image digest-pinned; Trivy HIGH/CRITICAL scan (report-only until baseline clean).
- ✅ **#35 Backup & restore flow** — `backup_db.sh` (gzip pg_dump, 14-day retention) + `restore_db.sh`; restore-drill documented in RUNBOOK.
- ✅ **#36 Deploy & rollback discipline** — `scripts/deploy.sh` (rsync + rebuild, junk/override excluded); source-based rollback in RUNBOOK.

## 8. Testing expansion

- ✅ **#41 property-based risk tests** — `tests/test_invariants.py` sweeps sizing caps, the entry/exit gate, tick + instrument-meta validators (no new dependency).
- ⬜ **#37 Broker-adapter contract tests** (pairs with the live adapter) · **#38 e2e paper replay** · **#39 broker-mock lifecycle sim** · **#40 chaos tests**.

## 9. Docs & cleanup

- ✅ **#43 runbooks** — `RUNBOOK.md` (deploy/rollback/backup-restore/kill-switch/health/secret-rotation/go-live). · ✅ **#44 risk-policy doc** — `RISK_POLICY.md` from `config/risk.yaml`.
- ✅ **#42 README-to-reality** — status/blockers/tests/limitations corrected to current state. · ✅ **#45 cache prune** — `.gitignore` complete (incl. `*.tsbuildinfo`); nothing tracked to remove. · ✅ **#46 boundary typing** — every substantive module carries `from __future__ import annotations` (only empty `__init__.py` markers lack it). · ✅ **#47 standard error types** — `TradingError` hierarchy used across the mode/executor/broker live paths.

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
