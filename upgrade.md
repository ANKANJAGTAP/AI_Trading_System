# AI Trading System Upgrade Plan

Date: 2026-06-12

Purpose: turn the audit findings into a concrete bug-finder and upgrade backlog that can raise the main quality scores of the project. This file is intentionally code-focused and action-oriented.

Current high-level verdict: good research/paper-trading foundation, not live-ready, not institutional-grade yet.

## Target Score Map

| Area | Current | Target | What Must Change |
|---|---:|---:|---|
| Project structure | 7/10 | 8.5/10 | Remove stale generated files, formalize module ownership, add architectural docs |
| Code quality | 6.5/10 | 8.5/10 | More typed boundaries, fewer implicit runtime states, stronger error handling |
| Architecture | 6/10 | 8.5/10 | Make mode/account/session state explicit and atomic |
| Database | 5.5/10 | 8/10 | Add constraints, migration drift checks, stronger audit model |
| DevOps | 4/10 | 8/10 | Add CI, scans, pinned images, reproducible deploys, restore tests |
| Reliability | 4.5/10 | 8.5/10 | Durable commands, dedicated heartbeat, broker reconciliation, chaos tests |
| Security | 3.5/10 | 8/10 | Strong auth, roles, secret encryption, service isolation, audit hardening |
| Trading engine, paper | 6.5/10 | 8.5/10 | Better lifecycle simulation, replay tests, slippage/fees realism |
| Trading engine, live | 4/10 | 8/10 | Correct live exits, partial fill handling, broker-truth accounting |
| Strategy/alpha | 4/10 | 7/10 | Evidence-backed backtests, walk-forward, regime analysis, feature drift checks |
| Risk, paper | 5.5/10 | 8/10 | Mode-scoped capital, session-aware exposure, better fail-closed controls |
| Risk, live | 3.5/10 | 8/10 | Broker-margin truth, atomic kill switch, reconciliation gates |
| Backtest validity | 3.5/10 | 7.5/10 | Historical option chains, execution realism, transaction cost validation |
| Scalability | 4.5/10 | 7.5/10 | Bounded queues, worker isolation, metrics, load tests |
| Institutional readiness | 2/10 | 7.5/10 | Compliance-grade ops, runbooks, DR, change control, evidence packs |

## Upgrade Principles

1. Fail closed for live trading. If data, broker, risk, auth, or reconciliation state is uncertain, block new risk.
2. Broker truth wins. Local quotes and simulated prices cannot be the source of truth for live fills, positions, or realized P&L.
3. Mode must be atomic. Paper/live mode, capital source, kill-switch state, executor mode, broker client, and position scope must change together.
4. Every destructive command must be durable. Flatten, close, disable, and kill commands need acknowledgement, retries, and audit.
5. Backtests must match the tradable instrument. F&O research needs historical option chain, spreads, taxes, margin, and gap behavior.
6. Operational readiness is part of trading logic. Alerts, backups, restores, logs, tokens, and runbooks are not optional.

## P0: Stop-Live Blockers

These should be fixed before any real-money trading is enabled.

### 1. Make Execution Mode Atomic

Problem:
- API mode switching updates runtime config, but risk, capital, kill switch, and executor may not all switch together.
- Live execution can use stale paper assumptions.

Required code changes:
- Introduce a single `RuntimeModeState` or equivalent domain object.
- Store active mode, broker account id, capital source, risk profile, kill-switch mode, and position namespace together.
- Replace scattered reads of `cfg.execution.mode` and mutable `config_state["execution_mode"]`.
- Add a mode transition service with validation:
  - paper to live requires executable pre-live checks.
  - live to paper requires flatten/reconcile or explicit safe isolation.
  - mode transition must be logged and auditable.
- Executor, risk engine, capital reader, kill switch, position provider, and API status must read the same state.

Bug-finder tests:
- Unit test: executor cannot be live while risk engine reports paper.
- Integration test: API mode switch updates all mode-aware services.
- Property test: no combination of mode state allows live orders with paper capital.
- Restart test: mode state survives engine restart consistently.

Score impact:
- Architecture +1.0
- Reliability +1.0
- Live trading engine +1.5
- Risk live +1.5

### 2. Replace Manual Pre-Live Checklist With Real Checks

Problem:
- The current pre-live checklist is mainly boolean flags.
- It does not prove the system is actually safe to trade live.

Required code changes:
- Build `PreLiveCheckService`.
- Required checks:
  - broker token valid.
  - broker profile/account reachable.
  - market data subscription working.
  - order placement dry-run or exchange-safe tiny test path available.
  - open broker positions match database.
  - no stale paper positions in live namespace.
  - alerts can be delivered.
  - Redis reachable and command queue healthy.
  - DB migration state clean.
  - latest backup age below threshold.
  - kill switch can block order placement.
  - daily loss and exposure caps loaded from live config.
  - system clock skew acceptable.
  - trading holiday/session calendar loaded.
  - dependency versions recorded.
- Store check result rows with timestamp, operator, version, and evidence.
- API should return detailed failing checks, not just true/false.

Bug-finder tests:
- Mock broker unreachable: live enable fails.
- Mock reconciliation mismatch: live enable fails.
- Mock alert failure: live enable fails.
- Backup too old: live enable fails.
- Kill switch active: live enable fails.

Score impact:
- Institutional readiness +1.0
- Reliability +1.0
- Security +0.5

### 3. Fix Live Exit Product Handling

Problem:
- Live market exit is hardcoded to `MIS`.
- CNC, NRML, F&O, and MCX exits can fail or use wrong broker product.

Required code changes:
- Persist product, exchange, variety, instrument token, tradingsymbol, and order type per open position.
- `market_exit()` must derive exit order fields from the actual position/order record.
- Add support for:
  - Equity MIS.
  - Equity CNC.
  - NFO NRML.
  - MCX NRML.
  - Any intentionally unsupported product should fail closed before entry, not at exit time.
- Add product mapping tests against broker adapter.

Bug-finder tests:
- Open CNC position, close sends CNC exit.
- Open NRML F&O position, close sends NRML exit.
- Open MCX position, close sends MCX exchange and product.
- Unknown product blocks entry.

Score impact:
- Live trading engine +1.5
- Risk live +1.0

### 4. Use Broker Fill Truth For Live Close Accounting

Problem:
- Live close currently records local quote/simulated/fallback price instead of actual broker exit fill.

Required code changes:
- Make `market_exit()` return normalized fill details:
  - broker order id.
  - status.
  - filled quantity.
  - average fill price.
  - pending quantity.
  - fees if available.
  - timestamp.
- `close()` must update position P&L from actual fill data.
- If fill is partial, keep remaining quantity open.
- If fill status unknown, mark position as `CLOSE_PENDING` and trigger reconciliation.
- Add `position_events` table or append-only event model for entry, modify, partial close, full close, broker correction.

Bug-finder tests:
- Broker full fill closes position with broker average price.
- Broker partial fill reduces quantity and keeps position open.
- Broker timeout creates pending state, not fake close.
- Reconciliation later completes pending close.

Score impact:
- Live trading engine +1.5
- Database +0.5
- Institutional readiness +0.5

### 5. Handle Partial Entry Fills Safely

Problem:
- Partial live entry can leave remaining parent order active or create unbracketed exposure.

Required code changes:
- Add `OrderLifecycleManager`.
- After timeout or partial fill:
  - cancel remaining unfilled parent order.
  - confirm cancellation.
  - bracket only confirmed filled quantity.
  - reconcile broker order book.
  - mark lifecycle state precisely.
- Never assume a parent order is dead because polling timed out.
- Add explicit states:
  - `SUBMITTED`
  - `PARTIAL_FILLED`
  - `CANCEL_REQUESTED`
  - `CANCEL_CONFIRMED`
  - `BRACKET_PENDING`
  - `PROTECTED`
  - `UNPROTECTED`
  - `RECONCILE_REQUIRED`

Bug-finder tests:
- Parent order partially fills then cancellation succeeds.
- Parent order partially fills then cancellation fails.
- Parent order fills after timeout before cancel.
- Bracket placement fails after partial fill.
- Any unprotected live exposure triggers alert and kill-new-orders.

Score impact:
- Live trading engine +1.5
- Reliability +1.0
- Risk live +1.0

### 6. Disable Or Fully Implement Live F&O Structures

Problem:
- Live multi-leg structures are rejected. That is safe, but the platform should not present them as live-ready.

Required code changes:
- Add feature flag: `fno_live_structures_enabled=false` by default.
- UI/API must show F&O structures as paper-only unless enabled.
- If implementing live:
  - basket order lifecycle.
  - all-leg success/failure rollback.
  - partial-leg hedge logic.
  - margin pre-check.
  - slippage and spread guard per leg.
  - broker reconciliation per leg.
  - kill switch for orphan legs.
- Until complete, block live F&O structure mode at strategy-gate level.

Bug-finder tests:
- Live F&O structure signal is blocked when flag false.
- Partial leg fill creates hedge/flatten action.
- Margin failure blocks basket before first order.

Score impact:
- Live trading engine +1.0 if blocked clearly.
- Live trading engine +2.0 if fully implemented.

### 7. Harden GTT/OCO And Stop Handling

Problem:
- GTT/OCO plus local guard can race.
- Stop legs use limit orders that may not fill through gaps.

Required code changes:
- Add a broker-order reconciliation loop for all active brackets.
- Store bracket id, trigger id, local guard id, state, and last broker status.
- Add state transitions:
  - `BRACKET_REQUESTED`
  - `BRACKET_ACTIVE`
  - `STOP_TRIGGERED`
  - `TARGET_TRIGGERED`
  - `CANCEL_REQUESTED`
  - `CANCELLED`
  - `BROKER_FILLED`
  - `LOCAL_EXIT_SENT`
  - `DUPLICATE_EXIT_RISK`
- Use stop-market where available, or define a tested slippage envelope for stop-limit.
- On local exit, re-query broker before sending market exit.
- After exit, verify no remaining open GTT/trigger/order.

Bug-finder tests:
- Broker GTT fills while local close is requested.
- Local stop fires while GTT status is stale.
- Cancel GTT fails, then market exit flow handles duplicate risk.
- Gap through stop-limit leaves order unfilled and triggers emergency exit.

Score impact:
- Risk live +1.0
- Reliability +1.0

## P1: Core Risk And Session Safety

### 8. Scope Positions, Capital, And P&L By Mode And Account

Problem:
- Position and capital readers can aggregate all rows, including paper/live/stale rows.

Required code changes:
- Add explicit columns where missing:
  - `mode`
  - `account_id`
  - `broker`
  - `strategy`
  - `venue`
  - `instrument_type`
- Every query that reads positions, closed P&L, heat, loss streak, daily P&L, or journal stats must filter by mode/account.
- Add indexes for `(mode, account_id, status)`.
- Add migration and backfill plan for existing rows.

Bug-finder tests:
- Paper loss cannot affect live capital.
- Live open position cannot affect paper sizing.
- Stale old-mode rows ignored by active mode.

Score impact:
- Architecture +1.0
- Risk live +1.0
- Database +0.5

### 9. Make Risk Dependencies Fail Closed In Live

Problem:
- VIX scaling and structure margin checks can fail open.

Required code changes:
- Introduce per-mode dependency policy:
  - paper: may degrade with warning.
  - live: fail closed for missing critical data.
- Critical live dependencies:
  - broker account/margin.
  - market data.
  - instrument metadata.
  - session calendar.
  - margin estimator.
  - risk config.
  - kill-switch status.
- Add `RiskDependencyStatus` object and expose it through API/dashboard.

Bug-finder tests:
- VIX unavailable in live blocks new high-risk trades or applies strict cap.
- Margin API unavailable blocks F&O entry.
- Instrument metadata unavailable blocks order.

Score impact:
- Risk live +1.0
- Institutional readiness +0.5

### 10. Add Venue-Aware Market Sessions

Problem:
- Feed watchdog and management loop use equity-style market windows.
- MCX evening session may be under-protected.

Required code changes:
- Replace single market window with session calendar service.
- Support NSE equity, NFO, MCX, holidays, special sessions, and early closes.
- Every instrument must map to venue/session.
- Feed watchdog should evaluate staleness per active venue.
- Risk management loop should continue for any venue with open positions.
- If a venue is closed but positions remain open, manage according to carry policy.

Bug-finder tests:
- MCX open after NSE close still triggers feed stale alert.
- NSE closed, MCX open: MCX positions still managed.
- Holiday blocks new entries.
- Special session loads modified timings.

Score impact:
- Reliability +1.0
- Risk live +1.0

### 11. Add Broker Reconciliation As A First-Class Loop

Problem:
- Local DB can drift from broker orders/positions/funds.

Required code changes:
- Add reconciliation worker:
  - broker positions vs DB positions.
  - broker orders vs DB orders.
  - broker funds/margins vs capital reader.
  - broker GTT/triggers vs bracket state.
- Define severity levels:
  - informational drift.
  - trading blocked.
  - flatten required.
  - manual intervention required.
- Run on startup, before live enable, periodically during live mode, and after every order lifecycle error.
- Persist reconciliation snapshots.

Bug-finder tests:
- Broker has unknown position: block new entries.
- DB has open position missing at broker: mark resolved/anomaly.
- Broker pending order missing in DB: alert and block.
- Funds mismatch beyond threshold: block live sizing.

Score impact:
- Reliability +1.0
- Institutional readiness +1.0

## P1: Durable Commands, Heartbeat, And Kill Switch

### 12. Replace Fire-And-Forget Redis Commands

Problem:
- Commands are popped before execution. Engine crash can lose flatten/kill commands.

Required code changes:
- Use Redis Streams, DB-backed command table, or reliable queue semantics.
- Command states:
  - `CREATED`
  - `CLAIMED`
  - `EXECUTING`
  - `SUCCEEDED`
  - `FAILED`
  - `RETRYING`
  - `DEAD_LETTER`
- Commands must have idempotency keys.
- Panic commands must be replayable after restart.
- API should show command status and last error.

Bug-finder tests:
- Engine dies after claiming flatten command; command is retried.
- Duplicate flatten command does not create duplicate exits.
- Failed close command moves to retry/dead-letter with alert.

Score impact:
- Reliability +1.5
- Institutional readiness +0.5

### 13. Add Dedicated Engine Heartbeat

Problem:
- Heartbeat is coupled to dashboard snapshot publishing and may not represent true liveness.

Required code changes:
- Add dedicated heartbeat task that runs regardless of trading gates.
- Publish:
  - process alive.
  - event loop healthy.
  - DB reachable.
  - Redis reachable.
  - broker reachable if live.
  - feed alive per venue.
  - last reconcile timestamp.
  - last command processed timestamp.
- API health should distinguish degraded vs down.
- Alert on missed heartbeat.

Bug-finder tests:
- Engine loop blocked: heartbeat fails.
- DB down: heartbeat degraded.
- Redis down: heartbeat degraded/down.
- Broker down in live: heartbeat critical.

Score impact:
- Reliability +1.0
- DevOps +0.5

### 14. Make Kill Switch Atomic And Global

Problem:
- Kill-switch behavior may not cover all order paths and mode transitions.

Required code changes:
- All order placement must go through one guarded order gateway.
- Kill switch must block:
  - strategy entries.
  - manual entries.
  - API-triggered new orders.
  - mode switch to live.
- Flatten/exit orders may be allowed under a separate `allow_reducing_only` policy.
- Persist kill switch state durably.
- Add operator identity and reason.

Bug-finder tests:
- Active kill switch blocks all new orders.
- Active kill switch permits reducing-only exits.
- Restart preserves kill switch state.
- API cannot bypass kill switch.

Score impact:
- Risk live +1.0
- Security +0.5

## P2: Database, Audit, And Data Integrity

### 15. Add Strong Database Constraints

Problem:
- Important trading fields are free text or weakly constrained.

Required code changes:
- Add CHECK constraints:
  - quantity > 0.
  - price >= 0 where applicable.
  - side in allowed values.
  - status in allowed values.
  - mode in allowed values.
  - product in allowed values.
  - exchange in allowed values.
- Add NOT NULL to critical fields after backfill.
- Add foreign keys where appropriate:
  - orders to positions/signals.
  - position events to positions.
  - bracket records to positions.
- Add unique constraints for broker order ids and idempotency keys.

Bug-finder tests:
- Invalid status insert fails.
- Negative quantity fails.
- Duplicate broker order id fails.
- Orphan order insert fails where FK required.

Score impact:
- Database +1.0
- Reliability +0.5

### 16. Detect Migration Drift

Problem:
- Migration runner records checksums but does not fail if an already-applied migration changes.

Required code changes:
- On migration startup, compare stored checksum with file checksum for every applied migration.
- Fail startup on drift unless explicit repair command is used.
- Add migration status command.
- Add CI check that migration files are immutable after release.

Bug-finder tests:
- Modify applied migration: runner fails.
- Add new migration: runner applies once.
- Missing migration file: runner warns/fails according to policy.

Score impact:
- Database +0.5
- DevOps +0.5

### 17. Build Event-Sourced Position History

Problem:
- Position lifecycle is too stateful for reliable audit and recovery.

Required code changes:
- Add append-only `position_events`:
  - signal accepted.
  - order submitted.
  - order filled.
  - partial fill.
  - bracket active.
  - stop moved.
  - exit submitted.
  - exit filled.
  - reconciliation correction.
- Derive current position state from latest valid events.
- Keep mutable summary table only as cache.

Bug-finder tests:
- Rebuild open positions from events.
- Rebuild P&L from events.
- Detect inconsistent event order.

Score impact:
- Institutional readiness +1.0
- Database +1.0

### 18. Strengthen Audit Log

Problem:
- Audit is useful but not compliance-grade immutable evidence.

Required code changes:
- Add hash chaining across audit rows.
- Store actor, source IP, request id, command id, correlation id, mode, and account id.
- Separate operational audit from trading event audit.
- Avoid short retention for compliance-critical records unless policy explicitly allows it.
- Export daily signed audit digest.

Bug-finder tests:
- Audit hash mismatch is detected.
- Update/delete attempts fail for normal app role.
- Every order lifecycle event has audit correlation.

Score impact:
- Security +0.5
- Institutional readiness +1.0

## P2: Security Hardening

### 19. Replace Single Static API Token

Problem:
- One bearer token controls both read and destructive operations. If unset, API may be open.

Required code changes:
- Fail startup if auth secret is missing outside local development.
- Add roles/scopes:
  - read-only.
  - operator.
  - trader.
  - admin.
- Require stronger auth for:
  - live enable.
  - kill switch changes.
  - flatten.
  - config changes.
  - token rotation.
- Add request audit with actor identity.
- Add rate limiting for sensitive endpoints.

Bug-finder tests:
- Missing token in production fails startup.
- Read-only token cannot flatten.
- Operator cannot change secrets.
- Admin action is audited.

Score impact:
- Security +1.0
- Institutional readiness +0.5

### 20. Stop Passing WebSocket Tokens In Query Strings

Problem:
- Query tokens can leak through logs, browser history, proxies, and monitoring.

Required code changes:
- Use secure headers or short-lived session tokens.
- Add token expiry.
- Add origin checks where relevant.
- Redact auth material from logs.

Bug-finder tests:
- Query token rejected.
- Expired token rejected.
- Logs do not contain token.

Score impact:
- Security +0.5

### 21. Harden Secrets

Problem:
- Broker token encryption may be weak or empty in development.

Required code changes:
- Require encryption key for stored broker tokens in all non-local environments.
- Support key rotation.
- Store only encrypted token material.
- Add token age/expiry status to pre-live checks.
- Prevent accidental logging of tokens.
- Add secret scanner to CI.

Bug-finder tests:
- Token file cannot be read as plaintext.
- Missing encryption key fails startup in live mode.
- Rotated key can decrypt old token through migration path.

Score impact:
- Security +1.0

### 22. Lock Down Infrastructure Defaults

Problem:
- Postgres and Redis are published on all interfaces by default. Redis has no auth.

Required code changes:
- Bind local services to localhost by default.
- Add Redis password or use private network only.
- Add separate compose files for local vs production.
- Add firewall/security group documentation.
- Do not publish DB/Redis in production compose unless explicitly required.

Bug-finder tests:
- Production config refuses unauthenticated Redis.
- Production config refuses public DB bind.
- Local compose remains easy to run.

Score impact:
- Security +1.0
- DevOps +0.5

## P2: Backtesting And Research Validity

### 23. Use Historical Option Chain Data For F&O Backtests

Problem:
- Current F&O backtest uses modeled values/proxies. That is not enough for production capital.

Required code changes:
- Add option chain data ingestion.
- Store bid, ask, last, volume, OI, IV, delta, gamma, theta, vega if available.
- Simulate entry/exit using realistic bid/ask and liquidity filters.
- Include expiry effects, assignment/exercise edge cases where relevant.
- Validate against broker contract notes after live/paper test trades.

Bug-finder tests:
- Backtest rejects missing chain data.
- Wide spreads reduce/skip trades.
- Illiquid strikes skipped.
- Expiry-day behavior tested.

Score impact:
- Backtest validity +1.5
- Strategy/alpha +1.0

### 24. Align Backtest And Live Risk Parameters

Problem:
- F&O backtest stop/target behavior differs from live config.

Required code changes:
- Load stop/target/trailing settings from shared config.
- Persist config version with every backtest run.
- Add test that backtest config and live strategy config match unless explicitly overridden.
- Surface overrides in reports.

Bug-finder tests:
- Config mismatch fails test.
- Backtest report includes config hash.
- Strategy report shows all overrides.

Score impact:
- Backtest validity +0.75
- Code quality +0.25

### 25. Improve Execution Realism

Problem:
- Backtests need more realistic slippage, gaps, fees, and rejected orders.

Required code changes:
- Add slippage models by instrument type and liquidity.
- Add gap-through-stop model.
- Add order rejection simulation.
- Add broker rate-limit simulation.
- Add taxes/fees model from current broker contract notes.
- Add max order size and freeze quantity rules.

Bug-finder tests:
- Gap stop produces worse fill than stop level.
- Low liquidity increases slippage.
- Broker rejection does not create fake position.
- Rate limit delays or rejects orders.

Score impact:
- Backtest validity +1.0
- Strategy/alpha +0.5

### 26. Add Walk-Forward And Out-Of-Sample Discipline

Problem:
- Strategy confidence needs more evidence.

Required code changes:
- Add walk-forward runner.
- Add train/validation/test splits by time.
- Add regime buckets:
  - low volatility.
  - high volatility.
  - trend.
  - chop.
  - gap days.
  - event days.
- Add parameter stability reports.
- Add kill criteria for strategies that decay.

Bug-finder tests:
- Strategy report fails if no out-of-sample window.
- Overfit parameter set flagged.
- Regime-specific drawdown reported.

Score impact:
- Strategy/alpha +1.0
- Institutional readiness +0.5

### 27. Treat Meta-Labeling As Experimental Until Data Is Enough

Problem:
- Meta-labeling requires enough labeled trades and class balance.

Required code changes:
- Keep meta-label model disabled until minimum sample size and validation quality are reached.
- Add dataset quality report:
  - label count.
  - class balance.
  - leakage checks.
  - feature drift.
  - performance by regime.
- Store model version and feature schema.
- Add model rollback.

Bug-finder tests:
- Too few labels blocks model activation.
- Single-class dataset blocks training.
- Feature schema mismatch blocks inference.

Score impact:
- Strategy/alpha +0.5
- Reliability +0.25

## P2: Feed, Data, And Scalability

### 28. Bound Tick Queues

Problem:
- Unbounded queues can grow memory under high tick volume or DB slowness.

Required code changes:
- Add max queue size.
- Define backpressure/drop policy:
  - never drop order lifecycle events.
  - market ticks may be coalesced by symbol.
  - store latest tick per symbol during overload.
- Add metrics for queue size, dropped/coalesced ticks, processing lag.

Bug-finder tests:
- Slow DB does not grow memory without bound.
- Latest tick is preserved during overload.
- Overload triggers alert.

Score impact:
- Scalability +1.0
- Reliability +0.5

### 29. Add Market Data Quality Gates

Problem:
- Bad ticks can contaminate signals and risk.

Required code changes:
- Add validators:
  - stale timestamp.
  - zero/negative price.
  - unrealistic jump.
  - crossed or invalid bid/ask.
  - volume anomaly.
- Flag symbols with bad data.
- Block strategy entries if required data quality is poor.

Bug-finder tests:
- Negative price rejected.
- Stale tick blocked.
- Sudden spike requires confirmation or is clipped.

Score impact:
- Risk +0.5
- Strategy/alpha +0.5

### 30. Build Instrument Metadata Cache

Problem:
- Trading logic depends on correct lot size, tick size, expiry, exchange, product, and freeze quantity.

Required code changes:
- Add versioned instrument master ingestion.
- Store instrument metadata with effective date.
- Validate orders against metadata before broker submission.
- Add stale metadata alert.

Bug-finder tests:
- Wrong lot size blocks order.
- Expired contract blocks order.
- Tick-size-invalid price is rounded or rejected.

Score impact:
- Live engine +0.5
- Risk +0.5

## P2: API And Dashboard

### 31. Add API Safety Boundaries

Problem:
- API control endpoints need stronger validation, authorization, and evidence.

Required code changes:
- Add request schemas for all control commands.
- Add idempotency key support for destructive commands.
- Add role/scope checks.
- Add audit event for every command.
- Return command id, not just success.
- Add OpenAPI docs.

Bug-finder tests:
- Invalid command payload rejected.
- Duplicate idempotency key returns same command result.
- Unauthorized destructive command rejected.

Score impact:
- Security +0.5
- Reliability +0.5

### 32. Show Truthful Live Readiness In Dashboard

Problem:
- UI should not imply live readiness when blockers exist.

Required code changes:
- Dashboard should show:
  - current mode state.
  - live readiness result with failing checks.
  - broker reconciliation status.
  - heartbeat state.
  - feed state per venue.
  - kill switch state.
  - pending commands.
  - unprotected positions.
  - last backup/restore test.
- Disable live controls unless readiness passes and user has scope.

Bug-finder tests:
- Failed pre-live check disables live button.
- Unprotected exposure displays critical warning.
- Pending command status updates.

Score impact:
- Institutional readiness +0.5
- Reliability +0.5

## P3: DevOps, CI, And Release Safety

### 33. Add CI Pipeline

Problem:
- No visible CI gate.

Required code changes:
- Add CI jobs:
  - format check.
  - lint.
  - type check.
  - unit tests.
  - integration tests.
  - migration tests.
  - dashboard build/test.
  - secret scan.
  - dependency vulnerability scan.
  - Docker build.
- Require CI pass before release.

Bug-finder tests:
- Broken migration fails CI.
- Secret committed to test fixture fails scanner.
- Type error fails CI.

Score impact:
- DevOps +1.5
- Code quality +0.5

### 34. Pin And Scan Runtime Images

Problem:
- Mutable images make builds less reproducible.

Required code changes:
- Pin Docker base images by digest or specific patch version.
- Pin TimescaleDB and Cloudflare image versions.
- Generate SBOM.
- Run vulnerability scanner.
- Document upgrade cadence.

Bug-finder tests:
- CI fails on unpinned production image.
- SBOM artifact generated.
- Critical vulnerability fails release.

Score impact:
- DevOps +1.0
- Security +0.5

### 35. Build Real Backup And Restore Flow

Problem:
- Runbook backup is too thin for production.

Required code changes:
- Add backup script with:
  - DB dump.
  - config snapshot excluding secrets.
  - audit digest.
  - checksum.
  - retention policy.
- Add restore script.
- Add scheduled restore test to staging/local.
- Define RPO and RTO.
- Expose backup freshness in health/pre-live checks.

Bug-finder tests:
- Restore from latest backup into empty DB.
- Checksum mismatch fails restore.
- Backup older than threshold blocks live enable.

Score impact:
- DevOps +1.0
- Institutional readiness +1.0

### 36. Add Deployment And Rollback Discipline

Problem:
- Production changes need controlled release flow.

Required code changes:
- Add version endpoint.
- Persist app version/build hash with orders and audit events.
- Add release checklist.
- Add rollback plan.
- Separate config from code.
- Add staging environment.

Bug-finder tests:
- Version endpoint returns build hash.
- Order audit includes code version.
- Rollback can start from previous image/config.

Score impact:
- DevOps +0.75
- Institutional readiness +0.5

## P3: Testing Expansion

### 37. Add Broker Adapter Contract Tests

Required tests:
- Place market order.
- Place limit order.
- Poll order.
- Cancel order.
- Partial fill.
- Rejected order.
- Rate limit.
- GTT/OCO create/cancel/status.
- Funds/margin fetch.
- Position fetch.

Expected score impact:
- Live engine +1.0
- Reliability +1.0

### 38. Add End-To-End Paper Trading Replay

Required tests:
- Feed replay creates signals.
- Risk approves/rejects.
- Executor opens position.
- Bracket activates.
- Stop/target closes.
- Journal records outcome.
- Dashboard/API state matches DB.

Expected score impact:
- Paper engine +1.0
- Code quality +0.5

### 39. Add Live Lifecycle Simulation With Broker Mock

Required tests:
- Full fill entry/exit.
- Partial fill entry.
- Bracket failure.
- Broker disconnect.
- Broker rejects close.
- Reconciliation mismatch.
- Kill switch during entry.
- Engine restart with open live position.

Expected score impact:
- Live engine +1.5
- Reliability +1.0

### 40. Add Chaos Tests

Required tests:
- Redis restart.
- DB restart.
- Broker timeout.
- Feed disconnect.
- Engine process kill.
- Clock drift.
- Disk full simulation where practical.
- API command submitted during engine restart.

Expected score impact:
- Reliability +1.0
- Institutional readiness +0.5

### 41. Add Property-Based Tests For Risk

Required properties:
- Position size never exceeds configured cap.
- Daily loss brake monotonically becomes stricter after losses.
- Kill switch always blocks new risk.
- Unknown/missing critical live dependency cannot approve order.
- Negative/zero prices cannot produce positive quantity.
- Total heat cannot exceed cap.

Expected score impact:
- Risk +1.0
- Code quality +0.5

## P3: Documentation And Operating Model

### 42. Update README To Match Reality

Required changes:
- Replace stale phase status.
- Document current supported modes honestly.
- Mark live F&O structures as disabled/not-ready if still blocked.
- Add architecture diagram.
- Add run commands.
- Add safety assumptions.

Score impact:
- Institutional readiness +0.25
- Project structure +0.25

### 43. Write Real Runbooks

Required runbooks:
- Start/stop system.
- Enable live mode.
- Disable live mode.
- Flatten all positions.
- Broker outage.
- Feed outage.
- Redis outage.
- DB outage.
- Stuck order.
- Partial fill.
- GTT mismatch.
- Restore backup.
- Rotate secrets.
- Incident review.

Score impact:
- Institutional readiness +1.0
- Reliability +0.5

### 44. Add Risk Policy Document

Required content:
- Max daily loss.
- Max weekly/monthly loss.
- Max heat.
- Max open positions.
- Strategy-level caps.
- Instrument-level caps.
- F&O margin rules.
- MCX carry policy.
- Kill-switch triggers.
- Manual override policy.

Score impact:
- Institutional readiness +0.5
- Risk +0.5

## P4: Cleanup And Maintainability

### 45. Remove Generated/Cache Files From Workspace

Problem:
- `__pycache__`, dashboard build outputs, and node modules are present in workspace.

Required changes:
- Keep them ignored.
- Clean local generated files when not needed.
- Add lightweight cleanup script if useful.
- Do not commit generated artifacts.

Score impact:
- Project structure +0.25

### 46. Add Static Typing At Service Boundaries

Required changes:
- Type API service responses.
- Type broker adapter interfaces.
- Type risk decision objects.
- Type command payloads.
- Type DB row mappers.
- Run mypy in CI for critical modules.

Score impact:
- Code quality +1.0

### 47. Standardize Error Types

Required changes:
- Add domain exceptions:
  - `BrokerUnavailable`
  - `OrderRejected`
  - `PartialFillTimeout`
  - `RiskDependencyMissing`
  - `ReconciliationMismatch`
  - `ModeTransitionRejected`
  - `UnsafeLiveState`
- Convert broad exceptions into typed failures.
- Ensure each typed failure has risk action and alert severity.

Score impact:
- Code quality +0.5
- Reliability +0.5

## Bug-Finder Approach

Use this workflow continuously while upgrading.

### Static Bug Finding

1. Run lint, format, and type checks.
2. Search for direct broker calls outside the guarded order gateway.
3. Search for unscoped position/capital queries.
4. Search for `except Exception` blocks that hide live-risk failures.
5. Search for hardcoded products, exchanges, sessions, and quantities.
6. Search for local quote usage in live P&L or live close logic.
7. Search for mutable global config state.
8. Search for API endpoints without auth/scope checks.
9. Search for secrets in files, logs, and configs.
10. Search for queue pop operations without acknowledgement.

### Dynamic Bug Finding

1. Replay market data through paper engine.
2. Simulate broker partial fills.
3. Simulate broker order rejection.
4. Simulate broker timeout.
5. Simulate delayed GTT status.
6. Kill engine during flatten command.
7. Restart with open positions.
8. Disconnect feed during open position.
9. Disconnect Redis during command processing.
10. Disconnect DB during order lifecycle.

### Trading-Specific Bug Finding

1. Verify every live position has a matching broker position.
2. Verify every live broker order has a matching DB order.
3. Verify every open live position has protection or a documented no-protection reason.
4. Verify every close event uses actual broker fill price.
5. Verify every strategy signal has a risk decision.
6. Verify every risk decision has config version and mode.
7. Verify every order has idempotency key and correlation id.
8. Verify every F&O order respects lot size and margin.
9. Verify every MCX order respects session and product rules.
10. Verify every stop can execute in gap scenarios.

### Security Bug Finding

1. Start app without auth secret in production mode; it must fail.
2. Try read-only token against destructive endpoint; it must fail.
3. Try WebSocket with token in query string after migration; it must fail.
4. Scan logs for tokens.
5. Scan repo for secrets.
6. Check DB/Redis network exposure.
7. Check dependency vulnerabilities.
8. Check Docker image vulnerabilities.
9. Check audit records for actor identity.
10. Check that token rotation does not break startup.

### Operational Bug Finding

1. Restore latest backup into empty DB.
2. Verify heartbeat alerts when engine stops.
3. Verify pre-live fails when backup is stale.
4. Verify pre-live fails when reconciliation is dirty.
5. Verify runbook steps match real commands.
6. Verify dashboard shows degraded states.
7. Verify incident logs contain enough evidence.
8. Verify release rollback works.
9. Verify migration drift is detected.
10. Verify all production config differences are documented.

## Suggested Implementation Order

### Milestone 1: Live Trading Freeze And Safety Foundation

Deliver:
- Atomic mode state.
- Real pre-live checks.
- Guarded order gateway.
- Durable kill switch.
- Mode/account-scoped risk queries.
- Auth fail-closed when secret missing.

Exit criteria:
- No live order can be placed unless mode, risk, capital, kill switch, broker, and reconciliation state all agree.

### Milestone 2: Broker-Truth Execution

Deliver:
- Correct product-aware exits.
- Broker-fill-based accounting.
- Partial fill lifecycle handling.
- Bracket/GTT reconciliation.
- Broker reconciliation loop.

Exit criteria:
- Every live position can be traced from signal to broker order to fill to P&L using broker truth.

### Milestone 3: Reliability And Operations

Deliver:
- Durable command queue.
- Dedicated heartbeat.
- Backup/restore scripts.
- Real runbooks.
- CI pipeline.
- Migration drift detection.

Exit criteria:
- Engine crash, Redis crash, DB crash, and broker timeout scenarios are tested and produce safe states.

### Milestone 4: Research Validity

Deliver:
- Historical option chain backtests.
- Shared live/backtest risk config.
- Execution realism.
- Walk-forward reports.
- Meta-label data-quality gates.

Exit criteria:
- Strategy performance reports are reproducible, out-of-sample, and instrument-realistic.

### Milestone 5: Institutional Hardening

Deliver:
- Role-based auth.
- Strong audit hash chain.
- Signed audit digest.
- SBOM and vulnerability scans.
- Versioned releases and rollback.
- Compliance evidence pack.

Exit criteria:
- A third party can inspect the system state, release version, trade history, risk decisions, audit trail, and restore evidence.

## Definition Of Done For Live Readiness

Live trading should remain disabled until all are true:

1. Atomic mode state implemented and tested.
2. Pre-live checks are executable and all pass.
3. Broker reconciliation is clean.
4. Live exits use correct product/exchange/instrument.
5. Live P&L uses actual broker fills.
6. Partial fills are safely handled.
7. Durable flatten/kill commands exist.
8. Kill switch is durable and globally enforced.
9. Feed watchdog is venue-aware.
10. Open positions are mode/account scoped.
11. Secrets are encrypted and auth is mandatory.
12. DB/Redis are not publicly exposed by default.
13. Backup and restore have been tested.
14. CI passes tests, lint, type checks, scans, and migration checks.
15. Runbooks exist and have been dry-run.

## Highest-Value Next Code Changes

If only ten changes are done first, do these:

1. Create atomic runtime mode state and block unsafe live transitions.
2. Replace manual pre-live flags with executable readiness checks.
3. Make all position/capital/risk queries mode/account scoped.
4. Fix live exit product handling.
5. Record live close P&L from broker fills only.
6. Add partial-fill cancellation/reconciliation lifecycle.
7. Replace Redis pop commands with durable acknowledged commands.
8. Add broker reconciliation loop.
9. Add venue-aware session/feed watchdog.
10. Require secure auth/secrets for any live-capable environment.

