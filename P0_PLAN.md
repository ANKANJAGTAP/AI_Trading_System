# Live-Path P0 Blockers — Implementation Plan

The 7 "stop-live" blockers from `upgrade.md`. The system runs in **paper**
(`simulated_fill`); live real-money is gated. These build the safety machinery
required *before* a live flip. **Non-negotiables for every item:** the
`_execute_sim` / sim-`close` branches must not change; every new live behavior
defaults to the blocked/paper state (fail-closed); each ships with tests; the
live-order-path items (#3/#4/#5/#7) merge only behind a mocked-broker harness.

## How the live path works today (the fault line)

There is one `Executor` that branches on mode per call (`current_mode()` reads
`config_state['execution_mode']`). But `RiskEngine`, `KillSwitch`, and
`CapitalReader` are built once at startup with the mode baked in and **never
updated when the API flips mode** (`api/routes.py` just writes the state row).
So a flip to live keeps paper capital and a paper-namespaced kill-switch — the
exact "live execution on stale paper assumptions" P0#1 fixes. Everything else
(#3–#7) lives on the live order path inside `executor.py` / `brackets.py` /
`position_book.py`.

Cross-cutting: introduce `common/errors.py` with the typed exceptions
(`ModeTransitionRejected`, `UnsafeLiveState`, `PartialFillTimeout`,
`ReconciliationMismatch`, `BrokerUnavailable`, `OrderRejected`) during P0#1 — all
seven raise them.

---

## P0#1 — Atomic execution mode  *(foundation)*

- **Today:** mode read from 6+ places; risk/kill-switch/capital ignore the flip.
- **Change:** `common/runtime_mode.py` — one `RuntimeModeState` (mode, broker
  account, capital source, risk profile, kill-switch mode, position namespace,
  version) in a single `config_state['runtime_mode']` row. `common/mode_transition.py`
  — validated paper↔live transitions (paper→live requires P0#2 all-pass + clean
  reconcile; live→paper requires flatten or explicit safe-isolation). Make
  `KillSwitch`/`CapitalReader`/`RiskEngine`/`Executor` read mode **lazily** from
  `get_runtime_mode()` instead of a constructor value. Drive the transition through
  the **command queue** (engine-side), not the API process. Migration seeds a safe
  default. Fix latent bug: `close()`/guard-exit read a possibly-stale `self.mode`.
- **Paper-safe:** default row = paper; falls back to legacy `execution_mode`; sim
  fill logic untouched; every missing field defaults to blocked/paper.
- **Tests:** no state combo yields live+paper-capital; API request→engine apply→all
  consumers observe live in one cycle; survives restart.
- **Effort:** L. Foundation for all others.

## P0#2 — Real pre-live checks

- **Today:** `prelive_checklist()` returns 4 operator-set booleans — nothing is
  verified. No holiday calendar exists.
- **Change:** `common/prelive.py::PreLiveCheckService` running the 15 real checks
  (token valid, broker reachable, feed live, order dry-run via `order_margins`,
  broker positions==DB via `book.reconcile`, no stale paper positions, alert
  deliverable, Redis+queue, migration checksums clean, backup age, kill-switch
  blocks, live caps loaded, clock skew, session/holiday calendar, dep versions).
  Persist runs+results+evidence (new migration). The P0#1 transition requires
  `overall == pass`. Stub `common/sessions.py` (seed for P1#10).
- **Paper-safe:** read-only broker probes + a test alert; the real-order dry-run is
  flag-gated OFF; only invoked on a live transition; every check fails-closed.
- **Tests:** each failing probe blocks the transition; a run persists with evidence.
- **Effort:** M. Consumed by #1.

## P0#6 — Disable live F&O structures (flag)  *(quick win)*

- **Today:** already **blocked** (`execute_structure` rejects in live), but no flag
  and the UI/docs imply live capability.
- **Change:** `fno_live_structures_enabled: false` flag; make the gate flag-driven
  (still blocked by default); skip F&O eval in `_slow_loop` when live+disabled;
  surface `paper_only` to the dashboard/health.
- **Paper-safe:** default false = today's behavior; sim structures untouched.
- **Effort:** S. Independent — can land early.

## P0#3 — Live exit product handling

- **Today:** `market_exit()` hardcodes `product="MIS"`; `positions` doesn't store
  product/exchange/variety, so exits can't know CNC/NRML/MCX. Product is known at
  entry but only persisted on `orders`, not `positions`.
- **Change:** migration adds `product/exchange/variety/order_type/instrument_type`
  to `positions` (+ backfill from `orders`); persist them in `open_position`/
  `adopt_row`; `market_exit` derives exit fields from the row; whitelist supported
  (exchange,product); **fail-closed at entry** for unsupported.
- **Paper-safe:** `market_exit` is live-only; new columns nullable; sim close path
  untouched.
- **Tests:** CNC/NRML/MCX exits use correct product/exchange; unsupported rejects at
  entry; backfill works.
- **Effort:** M. Pairs with #4.

## P0#4 — Broker-fill truth for live close

- **Today:** live `close()` books P&L on a **local/quote** price and discards
  `market_exit`'s return. No partial-exit/CLOSE_PENDING/reconcile; no
  `position_events`.
- **Change:** `NormalizedFill` model; `market_exit` polls the exit order (reuse
  `_poll_order`) and returns it; live `close()` books from `fill.avg_price`, keeps
  remainder open on partial, sets `CLOSE_PENDING` + reconcile on unknown; new
  append-only `position_events` table (immutability trigger like `audit_log`);
  slow-loop resolves CLOSE_PENDING from broker order history.
- **Paper-safe:** all inside the live branch; sim P&L (depth-aware sim price)
  unchanged; CLOSE_PENDING only ever live.
- **Tests:** full→broker avg; partial→remainder open+re-armed; timeout→CLOSE_PENDING
  (no fake P&L); reconcile resolves; sim regression.
- **Effort:** L. Highest-risk accounting change. Pairs with #3.

## P0#5 — Safe partial entry fills

- **Today:** `_execute_live` *claims* to cancel the remainder but **never sends a
  cancel** — a partial entry can leave a resting parent + unbracketed exposure.
- **Change:** `execution/order_lifecycle.py::OrderLifecycleManager` with explicit
  states (SUBMITTED…PROTECTED/UNPROTECTED/RECONCILE_REQUIRED): poll → cancel
  remainder → **confirm cancel** (never assume dead on timeout) → bracket only
  confirmed filled qty → reconcile order book → any unprotected live exposure
  alerts + blocks new entries. Delegate `_execute_live` to it; keep freeze-slicing
  + reason-aware no-retry.
- **Paper-safe:** live-entry-only; sim partial via `force_fill_qty` untouched; use a
  dedicated `block_new_entries` flag.
- **Tests:** cancel ok→bracket sized to filled; cancel fail→RECONCILE+alert; fill
  after timeout captured; bracket-fail→UNPROTECTED+kill-new-orders.
- **Effort:** L. After #3/#4; bracket step uses #7.

## P0#7 — Harden GTT/OCO + stops

- **Today:** live bracket uses **LIMIT** stop legs (can gap through); stores only a
  `gtt_id` in `positions.raw`; local guard + broker GTT race; `close()` doesn't
  re-query the broker before a market exit → duplicate-exit risk.
- **Change:** `brackets` table (gtt/trigger/local-guard ids + state machine +
  last-broker-status); prefer **stop-market**; `execution/bracket_reconciler.py`
  loop reconciles active brackets vs `gtts()`/`orders()` and disarms the local guard
  on broker fill; `close()` **re-queries the broker before** sending a market exit
  (DUPLICATE_EXIT_RISK → book from existing fill, don't double-exit); adoption
  creates bracket rows post-restart.
- **Paper-safe:** all bracket-broker logic is live-only; sim arms only the local
  guard.
- **Tests:** GTT fills during local close→no duplicate; cancel-fail handled; stop-
  market gap path; post-exit asserts no resting GTT/order.
- **Effort:** L. Pairs with #4; its reconciler is the first slice of P1#11.

---

## Recommended sequence

1. **#1 Atomic mode** (L) + `common/errors.py` — foundation.
2. **#2 Pre-live checks** (M) — gates the transition.
3. **#6 Disable live F&O flag** (S) — quick safety win (parallelizable).
4. **#3 Exit product fields** (M) — live close path.
5. **#4 Broker-fill close accounting** (L) — highest-risk; with #3.
6. **#5 Partial entry lifecycle** (L) — live entry path.
7. **#7 GTT/OCO + stop hardening** (L) — bracket reconciler + re-query.

Items #3/#4/#5/#7 touch the live order path: each needs a mocked-broker harness
and must be exercised with kill-switch/halt set to prove fail-closed, and must
leave the sim branches byte-for-byte unchanged.

## Already partly built — extend, don't duplicate
- #1: `current_mode()` already re-reads mode (extend to RuntimeModeState).
- #3: product already computed (`_PRODUCT`) + on `orders` (propagate to `positions`).
- #4: `_poll_order` already normalizes entry fills (reuse for exits); `audit_log`
  immutability trigger is the `position_events` template.
- #5: `partial_fill` config knobs + reason-aware no-retry already exist.
- #6: live structures already blocked (only flag + UI label missing).
- #7: `_cancel_bracket`, `attach_bracket`, `place_oco`, `gtts()`, `_stops_from_gtts`
  all exist (extend into a stateful table + reconciler).
- P1#11 overlap: slow-loop already calls `book.reconcile` in live (grow it).
