# P1 Hardening Tier — Implementation Plan

The next tier below the P0 stop-live blockers (from `upgrade.md`). The P0 work
left groundwork in 5 of 7 items, so the theme is **extend, don't rebuild**.
Non-negotiables (same as P0): sim/paper path unchanged; new live behavior is
fail-closed; each piece ships with tests (prefer pure, DB-free helpers
monkeypatching `get_state`/`set_state` + `asyncio.run`, as in `tests/test_runtime_mode.py`).

Cross-cutting: derive scope/policy from `RuntimeModeState` (P0#1), raise the typed
errors in `common/errors.py`, new migrations `0019+` (forward-only, additive).

## P1#8 — Scope positions/capital/P&L by mode + account  *(foundation)*
- **Today:** `positions.mode` exists; kill-switch P&L is namespaced. But
  `risk/positions.PositionsProvider.open_positions()`, `risk/capital` compound read,
  and every `FROM positions` aggregate in `engine/main.py` + `api/services.py` have
  **no mode filter** → paper & live rows mix.
- **Left:** migration `0019_position_scope` (add `account_id`/`broker`/`venue`;
  reuse `sleeve` as strategy; indexes `(mode,account_id,status)`); a pure
  `risk/scope.py` (`position_scope(state)`, `where_clause(scope)`); thread scope
  through PositionsProvider + CapitalReader + every engine aggregate.
- **Safe:** unreadable mode → paper scope (never widen to "all rows").
- **Tests:** pure scope/where-clause; mixed-rows property test (live ignores paper).
- Effort M · read-path, high blast radius · **do first.**

## P1#10 — Venue-aware market sessions
- **Today:** verified `dataplatform/marketcalendar` calendar exists; but feed
  watchdog + both engine loops gate on ONE equity window → MCX evening session
  under-protected.
- **Left:** `common/sessions.py` (`Venue` enum + `MarketSessions` over the seed
  calendar, early-closes); `venue_for(exchange,segment)`; per-venue feed staleness;
  per-venue risk-loop gating of NEW entries (keep managing open positions always).
- **Safe:** unknown venue → closed for entries, but keep managing; error → fall back
  to the single equity window (no regression).
- **Tests:** pure session predicates vs the seed calendar (NSE closed/MCX open, etc.).
- Effort M · no order-path impact.

## P1#9 — Risk dependencies fail-closed in live
- **Today:** `RiskEngine._vol_scale` + `_margin_per_unit`/`_structure_margin_per_lot`
  fail OPEN (commented as such).
- **Left:** `risk/dependencies.py` (`RiskDependencyStatus` + mode-keyed
  `DependencyPolicy`); in live, missing broker-margin / market-data / calendar /
  risk-config → reject sizing instead of fail-open; expose `GET /risk/dependencies`.
- **Safe:** policy from `RuntimeModeState.risk_profile`; paper keeps degrade-with-warn.
- **Tests:** pure `(profile, present?) -> ok|degrade|fail_closed`.
- Effort M · gates sizing (live-only rejects).

## P1#13 — Dedicated engine heartbeat
- **Today:** heartbeat is written by `_publish_dashboard_snapshot` — coupled to the
  slow loop, so it doesn't represent true liveness.
- **Left:** independent `_heartbeat_loop` (loop alive, DB/Redis/broker reachable,
  feed-alive per venue, last reconcile, last command); `health()` classifies
  `ok|degraded|down`; alert on missed heartbeat.
- **Tests:** pure `heartbeat_status(doc, now)` classifier.
- Effort S-M · no order-path impact · cheap observability win.

## P1#11 — Broker reconciliation as a first-class loop
- **Today:** slow loop already runs `book.reconcile` + `resolve_pending_closes` +
  `reconcile_brackets` in live; pre-live has a one-shot count reconcile.
- **Left:** promote to `execution/reconciler.py` covering positions/**orders**/
  **funds**/GTTs; pure severity classifier (`info|trading_blocked|flatten_required|
  manual`) driving existing levers (`block_new_entries`, `safe_exit_all`); run on
  startup + before live-enable + after order errors; persist snapshots
  (`0020_reconciliation`).
- **Safe:** live-only; reconcile error → `block_new_entries` (fail-closed).
- **Tests:** pure severity classifier on synthetic diffs.
- Effort M · touches live path via existing levers.

## P1#12 — Durable commands
- **Today:** `common/commands.py` is fire-and-forget (RPUSH/LPOP) — a crash between
  pop and execute loses a flatten/kill.
- **Left:** DB-backed `commands` table (`0021_commands`) with states
  (CREATED/CLAIMED/EXECUTING/SUCCEEDED/FAILED/RETRYING/DEAD_LETTER), idempotency
  keys, atomic claim (`UPDATE ... RETURNING`), replay-after-restart in `bootstrap`;
  `GET /commands`. Keep the module name; swap internals.
- **Safe:** operator actions are mode-agnostic; durability only improves safety.
- **Tests:** pure state machine + idempotency (fake store).
- Effort L · delivery layer, not order logic · largest net-new.

## P1#14 — Atomic + global kill switch (single gateway)  *(highest order-path risk)*
- **Today:** kill-switch state durable + namespaced, but checks are scattered across
  `execute` / `execute_structure` (misses `block_new_entries`) / risk sizing.
- **Left:** one `_order_gateway(intent ∈ {ENTRY,EXIT,CANCEL})` that ALL broker
  placement funnels through; blocks ENTRY when active, allows EXIT/CANCEL under
  `reducing_only` (already a `RuntimeModeState.kill_switch_mode` value); store
  `{active,reason,operator,ts}`.
- **Safe:** wraps sim + live; defaults `block_all`; unknown state → block (fail-closed).
- **Tests:** pure `gate_decision(intent, active, mode)`; stub-adapter call-recording.
- Effort M-L · refactors every placement call site · **do last, with the broker mock.**

## Recommended sequence
1. **P1#8** scope (foundation, read-path) → 2. **P1#10** venue sessions →
3. **P1#9** fail-closed deps → 4. **P1#13** heartbeat (observability) →
5. **P1#11** reconciliation loop → 6. **P1#12** durable commands →
7. **P1#14** atomic kill gateway (live-path refactor, last).

#11 and #14 are the live-order-path items — last, behind a mocked-broker harness,
exercised with kill-switch/halt/block flags set, sim branches untouched.
