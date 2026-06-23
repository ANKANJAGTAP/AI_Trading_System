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
- ✅ Migrations 0013–0023 applied; full suite green (496 tests); paper-mode live on AWS.

---

## 1. 🔒 The hard gate before any *real* live trade

These are the only things that stand between "paper on AWS" and "transacting real capital."

- ⬜ 🔒 **Validate the real Kite adapter live** — `broker/kite_adapter.py` methods are thin Kite-SDK pass-throughs (orders/positions/historical/quote/GTT/OCO; auth + token refresh work). Contract behaviour is pinned by `tests/test_broker_contract.py` + the `MockBroker` sim, and `scripts/verify_broker_adapter.py` checks the live read + order→fill→book path read-only. Remaining: run that validation against real Kite (your Mac) + the streaming websocket feed. *(maps to upgrade #37 + world-class Phase 1/5)*
- ⬜ 🔒 **Rotate leaked secrets** — Kite key/secret + DB password were exposed in plaintext earlier. Rotate at the source (Kite console / DB) — **user action**, Claude cannot enter credentials.
- 🟡 🔒 **Live market-data feed** — **implemented** (`data/feed.py` FeedManager: KiteTicker → candle aggregation → Redis LTP → fast-loop, with a staleness watchdog, auto-reconnect on fresh token, and gap reconciliation). Remaining is **operational, not code**: a valid daily Kite token on the server + market hours — it connects automatically when the engine runs (paper mode uses it for live prices too).

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
- ✅ **#17 Event-sourced positions** — pure `execution/position_events.py` rebuilds a position from its append-only log + `reconcile_position` drift check; `PositionBook.rebuild_from_events` audits the stored row against the log. Unit-tested.
- ✅ **#18 Compliance-grade audit** — hash-chained row fingerprints + `compute_and_store_daily_digest` (tamper-evident daily digest).

## 4. Backtest & research validity

- 🟡 **#23 Historical option-chain backtests** — ✅ option-leg fill realism + synthetic bid/ask spread model (`backtest/option_fills.py`) wired into `fno_engine`; ✅ **TrueData vendor path** for real EOD option chains (`dataplatform/vendors/truedata.py` builds the chain via `TD_hist`) + intraday-bar backfill (`scripts/truedata_backfill.py`). ⬜ remaining: pull the chains on a TrueData port that allows full segments (trial is sandbox/limited) + verify the option-symbol format; pin/assignment effects.
- ✅ **#24 Align backtest & live params** — `backtest/provenance.py` config fingerprint (stable hash of result-affecting sections) stamped on every run + sweep; `diff_configs` reports backtest-vs-live drift. Unit-tested.
- ✅ **#25 Execution realism** — honest intrabar fills (gap-through-stop, limit targets, stop-first, directional slippage) **plus** order-rejection (price-band), freeze-qty slicing, and rate-limit models in `backtest/execution_model.py`; price-band rejection wired into the engine entry. Unit-tested.
- ✅ **#26 Walk-forward + OOS** — overfitting core (PSR / Deflated Sharpe / PBO·CSCV) + sweep verdict **live at `POST /api/backtest/sweep`**; regime-bucketed performance + parameter-decay kill criteria in `backtest/regime_analysis.py`. Unit-tested.
- ✅ **#27 Meta-label discipline** — already enforced in `api/research.train_and_register`: min-sample + class-balance gates, purged expanding-window CV with embargo (leakage-safe), activate-only-if-it-beats-baseline validation gate; model versioning + rollback in `research/registry.py` (`save_model`/`list_models`/`activate`). ✅ triple-barrier labeling (`research/triple_barrier.py`); ✅ alternative model trains on triple-barrier labels via `build_triple_barrier_dataset` + `train_and_register(label_mode="triple_barrier")` (CLI: `train_meta.py --labels triple_barrier`), through the same CV / validation / registry discipline.

## 5. Feed, data & scalability

- ✅ **#28 Bound tick queues** — `CoalescingTickBuffer` wired into the engine LTP path (bounded, latest-per-symbol under burst; coalesced/evicted counters exposed on the handler). Full coalescing activates with the live websocket feed (§1).
- ✅ **#29 Market-data quality gates** — `validate_tick` (stale/zero/negative/jump/crossed-quote) live in the engine LTP handler; bad ticks dropped.
- ✅ **#30 Instrument-metadata cache** — `validate_order_against_meta` (lot/tick/expiry) gates live entries in the executor; freeze handled by the slicer.

## 6. API & dashboard

- ✅ **#31 API safety boundaries** — scoped + rate-limited + audited control endpoints; optional `Idempotency-Key` header dedupes destructive cmds and returns the command-id.
- ✅ **#32 Truthful live-readiness UI** — `GET /api/readiness` aggregates operational tiles (pending commands, open positions, unsafe-entry block, live feed, backup) into a pass/warn/fail roll-up, surfaced in the Go-Live Readiness screen. Pure roll-up unit-tested; dashboard type-checks clean.

## 7. DevOps, CI & release safety

- ✅ **#33 CI pipeline** — GitHub Actions runs the suite + secret scan on every push/PR; FastAPI/uvicorn pinned to avoid the starlette route-registration break.
- ✅ **#34 Pin & scan runtime images** — base image digest-pinned; Trivy HIGH/CRITICAL scan (report-only until baseline clean).
- ✅ **#35 Backup & restore flow** — `backup_db.sh` (gzip pg_dump, 14-day retention) + `restore_db.sh`; restore-drill documented in RUNBOOK.
- ✅ **#36 Deploy & rollback discipline** — `scripts/deploy.sh` (rsync + rebuild, junk/override excluded); source-based rollback in RUNBOOK.

## 8. Testing expansion

- ✅ **#41 property-based risk tests** — `tests/test_invariants.py` sweeps sizing caps, the entry/exit gate, tick + instrument-meta validators (no new dependency).
- ✅ **#37 broker-adapter contract tests** + ✅ **#39 broker-mock lifecycle sim** — `broker/mock_broker.py` + `tests/test_broker_contract.py` pin the fill-truth/entry-lifecycle contract. · ✅ **#38 e2e paper replay** — `tests/test_paper_replay.py` drives a multi-order session through the mock end-to-end. · ✅ **#40 chaos tests** — `tests/test_chaos.py` injects broker silence/garbage, partial-then-cancel, bad ticks, gaps, and halts; asserts fail-closed throughout.

## 9. Docs & cleanup

- ✅ **#43 runbooks** — `RUNBOOK.md` (deploy/rollback/backup-restore/kill-switch/health/secret-rotation/go-live). · ✅ **#44 risk-policy doc** — `RISK_POLICY.md` from `config/risk.yaml`.
- ✅ **#42 README-to-reality** — status/blockers/tests/limitations corrected to current state. · ✅ **#45 cache prune** — `.gitignore` complete (incl. `*.tsbuildinfo`); nothing tracked to remove. · ✅ **#46 boundary typing** — every substantive module carries `from __future__ import annotations` (only empty `__init__.py` markers lack it). · ✅ **#47 standard error types** — `TradingError` hierarchy used across the mode/executor/broker live paths.

---

## 10. The bigger build — world-class plan, Phases 2–7 (where the *edge* is made)

- ✅ **Phase 2 — Research & validation** — triple-barrier + meta-labeling, Deflated Sharpe + PBO (`backtest/validation.py`), CPCV split generator (`backtest/cpcv.py`) **now wired into the training harness** (`train_meta.py --cv cpcv` → many OOS folds), sample weights — label uniqueness + time-decay (`backtest/sample_weights.py`), and a **dev→shadow→paper→live promotion ladder** (`registry.promote` / `next_stage`, migration 0023). The in-house model registry + staging stands in for MLflow.
- 🟡 **Phase 3 — Backtest engine** — ✅ SPAN-style scan-risk margin (`backtest/span_margin.py`), ✅ Greeks-attributed P&L (`backtest/greeks_pnl.py`), ✅ scenario/stress + Monte-Carlo / risk-of-ruin (`risk/scenario_var.py`, `backtest/monte_carlo.py`). ⬜ remaining: a full event-driven options backtester driven by a **real historical chain** (data-vendor dependency, deferred).
- ⬜ **Phase 4 — Strategy/signal engine**: 7-step pipeline, per-index structure selection, IV/GEX routing, microstructure confirmation. *(IV-regime routing, GEX, order-book imbalance already exist in the live strategies; remaining is integration/refinement.)*
- 🟡 **Phase 5 — Execution/risk** — ✅ options-portfolio Greeks limits, scenario-VaR/stress engine, pin/expiry controls (`risk/greeks_portfolio.py`, `risk/scenario_var.py`, `risk/expiry_control.py`); ✅ composed into `risk/structure_risk.assess_structure` and **wired into the paper F&O sim** — every structure carries net-greeks / stress-VaR / SPAN / expiry, with opt-in `fno.risk_gating` to block breaching structures. ⬜ remaining: the same gate in the live risk engine — deferred until live F&O is enabled (no-op on the current equity book).
- 🟡 **Phase 6 — Compliance + paper-live + UX** — ✅ payoff/Greeks UX (**Structure Lab**: `/structure` screen + `POST /api/structure/analyze` — expiry payoff curve, net Greeks, stress-VaR, SPAN, expiry verdict), ✅ go-live walkthrough (`GO_LIVE.md`). ⬜ remaining: a full drag-and-drop strategy *builder* + sustained paper across expiry cycles (operational/time).
- ⬜ 🔒 **Phase 7 — Controlled live**: tiny capital, one index/strategy, scale only on evidence. *(user action — real capital.)*
- 🟡 **Data fuel (cross-cutting)** — ✅ **TrueData** wired (SDK + EOD F&O-chain adapter + intraday backfill); ✅ **DhanHQ free historical** (`dataplatform/vendors/dhan.py`: daily + 1/5/15/30/60-min REST, `scripts/dhan_backfill.py` → candles), pure normalizers unit-tested. ⬜ remaining: run a backfill on the server to load data (Dhan is free → the realistic path now that the TrueData trial lacks historical); `strategies/providers.py` fundamentals + ban-list still stubs.

---

## Recommended execution order

1. **Security tier (§2)** — now. Cheap, paper-safe, removes default-credential exposure.
2. **Phase 2 validation harness (§10)** — *the highest-leverage build*. The plan's rule is data → **validation** → backtest → strategy → execution → live. Trust a strategy before risking it.
3. **Data integrity + feed/scale (§3, §5)** — reliability backbone.
4. **Live-hardening track (§1 adapter + §4 backtest realism + §8 contract tests)** — only when going live actually means something.
5. **DevOps/CI (§7) + docs (§9)** — fold in continuously.

> Sequencing rule (from the world-class plan): *never let strategy enthusiasm outrun data/validation maturity.* Going live without §10 Phase 2 is how good backtests become real losses.
