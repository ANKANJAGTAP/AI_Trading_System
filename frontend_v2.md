# Frontend Build Specification (v2 — Maximum Density) — AI Algorithmic Trading Platform

> **Pairs with:** `backend.md` (v2). Build **after** the backend's REST + WebSocket API is live.
> **Audience:** implementing engineer / Claude Opus 4.8.
> **Mandate:** a *phenomenal*, **information-dense professional trading terminal** for a real-money autonomous system — Bloomberg / Thinkorswim / TradingView-class density, executed with rigorous UX so density reads as *signal, not clutter*. One operator must be able to surface, on demand, **everything the system knows** — every quote, every gate, every Greek, every risk number — without hunting.
> **Working title:** **Aegis** (placeholder — find-and-replace when final).
> **What changed from v1:** density is now a first-class principle. Adds a configurable multi-pane **Workspace**, a live **Market/Watchlist grid**, full **Charts** with signal/trade markers, an **Option Chain + Greeks** surface, a **Performance/Analytics** suite, a **correlation matrix**, a **command palette**, **density modes**, **multi-monitor pop-out**, and **saved layouts** — plus far more data on every existing screen via micro-visualizations.

---

## 0. Design Decisions Made (override any of these)

1. **Platform:** **Desktop-first** dense terminal (primary), engineered for large and multi-monitor setups, **plus** a responsive mobile **Watch mode** (read-mostly + the two emergency controls).
2. **Aesthetic:** **dark-first "night desk"** — functional for long sessions and dense data; distinctive disciplined palette, not the generic near-black + acid-green default.
3. **Single operator, single tenant.** One login, no roles in v1.
4. **Signatures (where boldness is spent):** the **Mode Frame** (unmistakable SIMULATED vs LIVE) and the **Gate Trail** (pass/reject reasoning made visible). Everything else is quiet, instrument-grade, and *dense*.
5. **Density philosophy:** maximize information per screen via rigorous hierarchy + micro-visualizations (sparklines, inline bar gauges, heat cells) + operator-configurable layout. Never density-for-its-own-sake: every element must be answerable to "what decision does this inform?"

---

## 1. Product Thesis & UX Principles

Aegis is a **trading terminal and command cockpit**. The operator's jobs: (1) know instantly if the system is healthy and whether it's SIMULATED or LIVE; (2) see capital, open risk, and kill-switch proximity at a glance; (3) drill into *any* depth — a single position's intraday path, an option chain's OI buildup, the exact gate that rejected a signal — without leaving flow; (4) intervene fast and safely.

**Non-negotiable principles (mirror the backend's safety ethos):**

1. **Mode is never ambiguous** — Mode Frame on every screen.
2. **Never show stale data as live** — on WS drop, affected cells desaturate + carry a "stale · HH:MM:SS" tag; reconnect refetches authoritative state via REST before resuming the stream.
3. **Critical actions resist accident** — Flatten-All, Go-Live flip, Kill-Switch reset use hold-to-confirm or a typed token, and state exactly what will happen.
4. **The interface explains in its own voice** — errors say what happened + how to fix; empty states invite action; labels name what the operator controls.
5. **Numbers are first-class** — tabular (monospace) figures everywhere; green/red reserved strictly for direction/P&L.
6. **Density with hierarchy** — three weights of information (primary scan / secondary detail / on-demand drill) are visually distinct so a dense screen is still instantly parseable.
7. **Keyboard-first** — every screen and action reachable via the Command Palette (⌘/Ctrl-K) and shortcuts; a power operator should rarely need the mouse.

---

## 2. Design Language (token system)

### 2.1 Color — "Night Desk"
Semantic discipline: **brand ≠ profit color**; green only ever means up/long/profit.

```
--ink:            #0A0C12   /* base background — deep blue-black                 */
--surface:        #12151E   /* panels                                            */
--surface-raised: #1A1E2A   /* elevated cards, headers, popovers, sticky rows    */
--surface-inset:  #0E111A   /* table bodies, wells, chart backgrounds            */
--line:           #252A38   /* hairline borders, dividers, grid lines            */
--line-strong:    #313747   /* panel separators, active borders                  */
--text-hi:        #E8ECF4   /* primary                                           */
--text-lo:        #8A93A6   /* secondary, labels, axes                           */
--text-faint:     #5A6172   /* disabled, stale, watermark                        */

--brand:          #4FD1E0   /* signal cyan — interactive, focus, brand           */
--long:           #34D399   /* positive / long / profit                          */
--short:          #F87171   /* negative / short / loss                           */
--warn:           #FBBF24   /* caution / approaching kill-switch                 */
--info:           #818CF8   /* neutral highlight (selection, info chips)         */

--mode-sim:       #6B7AA8   /* SIMULATED chrome — calm desaturated blue          */
--mode-live:      #FF5C38   /* LIVE chrome — hot vermilion, used NOWHERE else    */

/* Heat scale (for OI buildup, correlation, performance heatmaps) — diverging */
--heat-pos-3:#065F46 --heat-pos-2:#10B981 --heat-pos-1:#6EE7B7
--heat-neg-1:#FCA5A5 --heat-neg-2:#EF4444 --heat-neg-3:#7F1D1D
--heat-zero:#1A1E2A
```

Rule: `--mode-live` appears only in live-mode chrome; its presence anywhere always means real money is on.

### 2.2 Typography
- **UI / display:** **Geist** (fallback Inter) — headings, labels, controls.
- **Data / numerics:** **Geist Mono** (fallback JetBrains Mono) — *all* prices, P&L, R, qty, %, timestamps; `font-variant-numeric: tabular-nums`.
- **Eyebrow labels:** uppercase 10–11px, letter-spacing 0.08em, `--text-lo` — encode structure (sleeve, gate, state).
- Scale (px): 10 (micro-label) · 11 (eyebrow) · 12 (dense data) · 13 (body) · 15 (default) · 20 (panel title) · 28 (hero secondary) · 44 (the one live-P&L hero). In Ultra-compact density, base data drops to 11px with 18px row height.

### 2.3 Layout & spacing
- 4px base grid (tighter than v1's 8px to support density); panel padding 12px (8px compact); table rows 28px comfortable / 24px compact / 20px ultra.
- **Shell:** persistent **Status Bar** (top) + optional **Ticker Tape** (top, toggle) + **Rail** (left, collapsible to icons) + **Workspace** (main) + optional **Inspector** (right dock, context detail).
- Hairline `--line` borders define the instrument grid; elevation by surface tint, not heavy shadow. Radius 6px panels / 4px controls / 3px chips.
- **Density modes:** Comfortable / Compact / **Ultra** — a global toggle that rescales paddings, row heights, and base font; persisted per operator.

### 2.4 Micro-visualization vocabulary (the key to density)
Reusable inline components that pack data into minimal space — specify and reuse everywhere:
- **Sparkline** (intraday/period price or P&L path) — inline in table cells and cards.
- **Inline bar gauge** — a value vs limit (e.g., R used vs R budget, margin used vs available) as a thin horizontal bar with a marker.
- **Heat cell** — a number whose background is color-scaled (OI buildup, correlation, IV rank, performance).
- **R-multiple chip** — compact `+1.8R` / `−1.0R` pill, colored.
- **Delta/Greek meter** — tiny dial or signed bar for option Greeks.
- **Distance badge** — % distance to VWAP / to stop / to target, signed.
- **Donut / stacked bar** — allocation (idle cash vs sleeves).
- **Status dot** — subsystem health (green/warn/short), with tooltip detail.

### 2.5 Motion (deliberate)
- **Value tick:** 180ms `--long`/`--short` background flash on change, then fade.
- **Gate resolve:** nodes resolve left-to-right with 120ms stagger.
- **Alarm (kill-switch / safe-exit):** decisive entrance + slow steady pulse on the relevant indicator; announced to assistive tech.
- `prefers-reduced-motion`: flashes/pulses become static color states.

### 2.6 Signature elements
**A. Mode Frame.** A 3px inset viewport border keyed to mode (`--mode-sim` / `--mode-live`); LIVE adds a slow-pulsing **● LIVE** badge in the Status Bar. Flipping mode animates the frame over 400ms. The single most important pixel in the app.

**B. Gate Trail.** A signal's pipeline as a horizontal track of gate nodes in order (Universe → Regime → Signal → Confirmation → Greeks/Vol → OI → Risk+Margin → Execution), each showing name + PASS/REJECT + a 0–1 score bar; a reject visibly halts the trail and dims downstream nodes; confidence + LLM veto render as the final node. Reused on Signals and in audit reconstruction. The product's reasoning made legible.

---

## 3. Information Architecture

**Global chrome (always present):**
- **Status Bar:** mode badge · health dot (worst subsystem) · session state (PRE-OPEN / OPEN / MCX-EXT / CLOSED / HALTED) · live capital · available margin (inline gauge vs used) · **day P&L vs kill-switch gauge** · open R vs limit · IST clock · global Pause + Flatten-All (guarded) · density toggle · ⌘K.
- **Ticker Tape (toggle):** Nifty, BankNifty, FinNifty, Sensex, India VIX, plus tracked instruments — LTP, %chg, mini-spark; click to open in Charts.
- **Command Palette (⌘K):** fuzzy navigation + actions (go to any screen, jump to an instrument, run a guarded control) — the keyboard backbone.
- **Inspector dock (right, toggle):** contextual detail for whatever is selected (a position, a signal, an instrument, a strike) without leaving the current screen.

**Left rail (operator-priority order):**
1. **Workspace** — configurable multi-pane grid (compose any panels; saved layouts).
2. **Command Center** — densified health + capital + risk + market context overview.
3. **Market** — live watchlist/scanner grid of everything the engine tracks.
4. **Charts** — full price charts with overlays + signal/trade markers + depth.
5. **Positions** — live positions across sleeves with management state.
6. **Signals** — live + recent signals, Gate Trail, rejection analytics.
7. **Option Chain** — F&O chain, OI/IV/Greeks, PCR, Max Pain, skew.
8. **Sleeves** — allocation, caps vs utilization, per-sleeve performance.
9. **Risk** — heat, correlation matrix, exposure, margin, drawdown.
10. **Analytics** — performance: equity/drawdown curves, win rate, expectancy (R), breakdowns.
11. **Audit** — immutable log + full trade reconstruction.
12. **Controls** — pause/flatten/sleeve toggles/Go-Live/kill-switch reset.
13. **Settings** — config (risk + thresholds), connection, alerts, layouts.

---

## 4. Screen Specifications

### 4.0 Workspace (the density centerpiece)
**Purpose:** let the operator compose a personal multi-pane terminal — see many data surfaces at once, like a Bloomberg launchpad.
- A resizable, draggable **panel grid**. Any of these are panel types: mini Market grid, a Chart, Positions, a Sleeve card, Risk gauge, Signals feed, Gate Trail, Option Chain mini, Activity feed, P&L hero, Greeks board, correlation mini.
- **Saved layouts** (named workspaces, e.g. "Open," "F&O focus," "Risk watch"); switch instantly; persisted via backend.
- Panels can **pop out** into a new browser window for multi-monitor use (see §7).
- Each panel has a compact header (title + instrument/context selector + density + pop-out + close).
- Default layout ships sensible (P&L hero + Positions + Market + Signals + Risk gauge).

### 4.1 Command Center
**Purpose:** maximal at-a-glance state.
- **Hero:** today's **net P&L** (44px mono, colored) + realized/unrealized split + % of capital; beneath it the **Kill-Switch Gauge** (0 → daily_max_loss, live marker, `--warn` within 25%, `--short` at line).
- **Market context strip:** Nifty / BankNifty / FinNifty / VIX (LTP, %chg, spark), advance-decline, market regime tag (trending/choppy), and the engine's current regime read.
- **Stat grid (dense):** trades today (win/loss), hit rate, avg R, current open R / max, positions N/max, exposure by sleeve, available margin gauge, largest winner/loser today, slippage vs model, rate-limit headroom.
- **Equity curve** (today + selectable period) as a compact chart.
- **Sleeve strip:** 4 cards, each with utilization-vs-cap bar, day P&L spark, open positions, enabled state.
- **Activity feed:** live entries/exits/rejections/alerts, newest first, color-coded, click → Inspector.
- **System Health:** feed connection, token validity + expiry countdown, last reconcile, loop heartbeat, rate-limit headroom, error rate — each a status dot with tooltip.

### 4.2 Market (live watchlist / scanner)
**Purpose:** surface *every instrument the engine is scanning* with the metrics that drive decisions — huge data density, the operator's market radar.
- Dense, virtualized, sortable, filterable grid. One row per tracked instrument. Columns (all live, with heat cells / sparks where noted):
  - instrument (+ sleeve eligibility chips), LTP (ticking), chg / %chg (colored), **day spark**, RVOL (heat), **VWAP distance** (signed badge), opening-range state (above/inside/below), volume vs avg, day range position (a mini hi-lo bar with marker).
  - F&O-relevant: OI, **OI day change** (heat), **IV**, **IV Rank** (heat), PCR (for underlyings), F&O-ban flag.
  - signal state: is a setup forming? last signal + result; eligibility (passes pre-filters?).
- **Saved scans / filters** (e.g., "RVOL>2 & above VWAP," "IV Rank>70," "near ORB breakout").
- Group by sleeve; column chooser; click a row → Inspector (detail) or Charts; right-click → add to a Workspace chart.
- Empty/loading states in interface voice; never show a frozen quote as live.

### 4.3 Charts
**Purpose:** professional price analysis with the system's reasoning overlaid.
- **TradingView Lightweight Charts**: candles + volume, multi-timeframe, with overlays: **VWAP**, EMAs/SMAs (incl. 200 DMA for swing), opening range box, ATR-stop level, support/resistance.
- **Markers on chart:** plot the engine's actual **signals and trades** — entry/exit, stop, target, and a marker that opens that signal's **Gate Trail** in the Inspector. This ties price action to system decisions visually.
- **OI / IV sub-panes** for F&O instruments; **depth/order-book** panel (bid/ask ladder with size bars) for the selected instrument.
- Drawing tools optional; chart background and series colors from the token layer so it stays cohesive in dark.
- Multi-chart grid (2/4 up) for scanning several instruments.

### 4.4 Positions (dense)
**Purpose:** every open position + protective state + live analytics.
- Virtualized table, **grouped by sleeve with subtotals** (sleeve P&L, sleeve open R). Columns:
  - instrument (+ sleeve chip), side (colored ▲/▼), qty/lots, entry, **LTP (tick)**, **intraday spark**, stop (+ distance badge), target (+ distance badge), **R at risk**, **R-multiple chip** (current), unrealized P&L (₹), **MAE/MFE** (max adverse/favorable excursion), time-in-trade, management state (trailing / soft-exit pending / etc.).
  - F&O rows: expandable to legs; show net **Greeks (Δ/Θ/Γ/V)**, structure max-loss, IV, DTE.
- Row danger states: near stop → left border `--warn`; breached/exiting → `--short` pulse.
- Per-row guarded actions (close, modify stop/target). Footer: portfolio totals (open R, net unrealized, net Greeks across F&O).
- Empty: "No open positions. The engine is scanning for qualifying setups."

### 4.5 Signals + Gate Trail + Rejection Analytics
**Purpose:** the window into reasoning, plus *aggregate* insight into why trades fire or don't.
- **Left:** recent signals list (newest first; filter sleeve / PASS / REJECT / executed; each row shows instrument, setup, result, confidence chip, the gate it died at if rejected).
- **Right:** selected signal's full **Gate Trail** + context (regime snapshot, IV/OI for F&O, confidence breakdown, LLM verdict + reason, final action + size, or rejecting gate).
- **Rejection analytics panel (new):** aggregated over a window — which gates reject most (bar chart), reject reasons distribution, near-misses (signals that passed N−1 gates). Tells the operator where the funnel is tight and whether thresholds need calibration.
- Live: evaluations animate their trail in real time.

### 4.6 Option Chain + Greeks (F&O density)
**Purpose:** the full options picture the F&O pipeline reasons over.
- **Chain grid** per underlying + expiry selector (weekly/monthly): strikes as rows; calls left / puts right; columns LTP, chg, **OI** (heat), **OI chg** (heat), volume, **IV** (heat), **Δ/Θ/Γ/V**; ATM row highlighted; in-the-money shading.
- **OI buildup heatmap** across strikes (long/short buildup, unwinding) using the diverging heat scale.
- **Summary band:** PCR, **Max Pain**, total CE/PE OI, IV skew curve, India VIX, days-to-expiry.
- Selecting a strike → Inspector with that contract's detail + "would the pipeline trade this?" eligibility readout.
- Builder hint: highlight the strikes the engine's structures (credit/debit spreads, condor) would use given current IV regime + delta bands.

### 4.7 Sleeves (dense)
- Four sleeve panels. Each: cap % vs **deployed** vs **live-margin-bounded headroom** (show both nominal cap and margin-clamped reality, per backend §3); open positions count; **day & cumulative P&L spark**; win/loss tally; avg R; enable/disable toggle (guarded — stops *new* entries, never silent force-close).
- Allocation visualization: stacked bar / donut of capital = idle cash + each sleeve's deployed (idle cash shown as a legitimate position).
- Per-sleeve mini equity curve.

### 4.8 Risk
**Purpose:** the risk-officer screen, dense.
- **Portfolio heat:** aggregate open R vs limit (gauge) + a table of positions contributing R, sorted, with R-multiple and stop distance.
- **Correlation matrix (new):** heatmap of open positions / sectors (diverging scale); flag clusters (>2 correlated) with a caution chip — concentrated risk counts against the limit.
- **Exposure breakdowns:** by sleeve, by sector, by long/short, by instrument — stacked bars.
- **Margin:** live available vs used (SPAN+Exposure for F&O), headroom projection, intraday margin timeline.
- **Leverage:** current effective exposure vs the 1.5–3x band (gauge; warn if exceeded).
- **Drawdown:** today's loss vs kill-switch + a session drawdown curve; kill-switch trip history.

### 4.9 Analytics (performance)
**Purpose:** is the edge real — computed from **real** executed/simulated trades only (no fabricated data).
- **Equity curve** + **drawdown curve** (selectable period, sim vs live separable).
- **KPIs:** win rate, profit factor, **expectancy in R**, avg win/avg loss (R), largest win/loss, Sharpe-like ratio, max drawdown, recovery, total trades.
- **Breakdowns:** by sleeve / by setup (ORB, VWAP pullback, credit spread…) / by instrument / by side — table + bars.
- **Distributions:** R-multiple histogram, hold-time distribution, win/loss streaks.
- **Time heatmaps:** performance by hour-of-day and by weekday (where the system makes/loses money) — heat cells.
- Clear labeling that simulated and live performance are distinct datasets.

### 4.10 Audit
- Virtualized, searchable, filterable log (correlation id, instrument, event type, time, sleeve). Event types: signal, gate result, sizing calc, order request, broker response, fill/partial, LLM verdict, error, mode change.
- **Trade reconstruction** by correlation id: Gate Trail as-was + full sizing math (R, qty, every clamp) + order lifecycle (placed → partial/filled → bracketed → exit) + realized outcome — the whole causal chain on one page.
- Export CSV/JSON for records/compliance.

### 4.11 Controls
- **Pause/Resume** (blocks new entries; existing positions still managed — stated).
- **Flatten-All** (panic): 2s hold-to-confirm + typed confirmation showing positions count + notional to close.
- **Per-sleeve enable/disable.**
- **Go-Live flip** (`SIMULATED → LIVE`): multi-step — surface the pre-live checklist booleans (compliance/tagging, fail-safe rehearsed, reconcile clean, alerts confirmed) → type `LIVE` to arm → confirm → Mode Frame turns vermilion app-wide. Back-to-SIM is one guarded step. In-UI hint: start LIVE at minimum risk %.
- **Kill-Switch reset** (enabled only when halted).
- Toasts speak the same verb as the button ("Flatten-All" → "All positions closed").

### 4.12 Settings
- **Config viewer/editor** for `risk` + `strategy_params` (per-trade risk %, daily max loss, sleeve caps, all pipeline thresholds) with min/max bounds shown; edits guarded + audit-logged; out-of-bounds requires explicit override confirm.
- Connection (broker token status + expiry + manual re-auth), alert recipients (email), density/theme, **layout/workspace management**, IST clock source.

---

## 5. Real-Time Data Layer
- **Transport:** native WebSocket push + REST for loads/actions. TanStack Query (REST cache/retry) + a Zustand WS store.
- **Typed events** (Appendix B) update the store; price/PnL/position changes trigger value-ticks; signal events animate the Gate Trail; market-grid quotes update in place.
- **Reconnection UX:** WS drop → health dot `--warn`, affected cells go **stale** (desaturate + "stale · HH:MM:SS"), auto-reconnect with backoff; on reconnect refetch authoritative REST state, *then* resume streaming (mirrors backend gap-reconciliation — never trust an accumulated stream across a gap).
- **Optimistic UI:** only for non-critical UI (filters, density, layout). **Never** for orders, flatten, or mode flips — those reflect confirmed backend state only.
- **Backpressure:** coalesce high-frequency ticks to animation-frame cadence; the dense Market grid and Charts must stay smooth under a tick storm (batch DOM writes, virtualize, memoize).

---

## 6. Technology Stack (decided)

| Concern | Choice | Reason |
|---|---|---|
| Framework | React 18 + **TypeScript** + Vite | Type safety for money math; matches backend |
| Styling | Tailwind CSS + CSS-variable token layer | Tokens (§2) drive the look, not default Tailwind |
| Headless primitives | Radix UI (custom-styled) | Accessible dialogs/popovers/menus, no templated skin |
| Price charts | **TradingView Lightweight Charts** | Candles, overlays, depth, markers — the pro standard |
| Stat/analytics charts | visx (or Recharts) | Equity/drawdown curves, histograms, gauges |
| Tables/grids | TanStack Table + virtualization (TanStack Virtual) | Dense Market/Positions/Audit/Chain grids |
| Layout engine | react-grid-layout (or dockview) | The Workspace multi-pane drag/resize + saved layouts |
| Server state | TanStack Query | REST cache/retry |
| Client/stream state | Zustand | WS store, UI state, layouts |
| Command palette | cmdk | ⌘K fuzzy nav + actions |
| Animation | Framer Motion | Deliberate motion, reduced-motion aware |
| Icons | Lucide | Consistent |
| Fonts | Geist + Geist Mono (fallbacks Inter / JetBrains Mono) | Distinctive, excellent tabular figures |
| Formatting | Intl + strict money/R util | ₹, tabular, R-units, signed % |
| Multi-monitor | Pop-out windows via window.open + BroadcastChannel | Panels on separate monitors, shared live state |
| Build/deploy | Vite build behind FastAPI / static host | Single origin with backend |

All chart and heatmap colors read from the token layer so the dark identity stays cohesive.

---

## 7. Multi-Monitor, Accessibility, Performance, Responsive
- **Multi-monitor pop-out:** any Workspace panel (or Charts/Market/Option Chain) can open in a separate browser window on another monitor; windows share live state via `BroadcastChannel` + a single WS connection in a leader tab. Critical for a serious desk.
- **A11y:** visible cyan focus ring on every control; full keyboard operation + Command Palette; ARIA live regions for kill-switch/safe-exit announcements; color never the sole signal (pair with ▲/▼ + labels); AA contrast on `--ink`; respect `prefers-reduced-motion`.
- **Performance:** virtualize all long grids; coalesce ticks to rAF; code-split per route; memoize dense cells; the shell stays responsive under a tick storm and a 10k-row audit/chain query. Target 60fps scroll on the Market grid with hundreds of live rows.
- **Responsive / mobile Watch mode:** below tablet width → single-column monitor (Mode badge + kill-switch gauge + net P&L + positions summary + activity feed + the two emergency controls, both hold-to-confirm). No config or layout editing on mobile.

---

## 8. Build Phases

Build in order; each phase self-contained with acceptance criteria. Code against the Appendix B contract; where backend isn't ready, use a thin **typed contract stub** returning real shapes (never fabricated trading data presented as real).

### Phase F0 — Design system, shell, workspace engine, command palette
**Deliverables:** token layer (§2) as CSS vars + Tailwind config; typography (Geist/Geist Mono, tabular); **Mode Frame** + Status Bar + Ticker Tape + Rail + Inspector dock; **Workspace** grid engine (drag/resize/add/remove panels) + saved-layout persistence; **Command Palette** (⌘K); **density modes**; routing for all screens; auth/login; WS client skeleton (connect, heartbeat, reconnect-backoff, stale plumbing); money/R formatting util; micro-viz primitives (sparkline, inline gauge, heat cell, R-chip, status dot); toast system; reduced-motion + focus baseline.
**Acceptance:** shell renders; mode flag flips the whole-viewport frame SIM↔LIVE; Workspace panels drag/resize and a layout saves/restores; ⌘K navigates; density toggle rescales; forced WS disconnect → health warn + panels stale; keyboard focus visible throughout.

### Phase F1 — Real-time layer + Command Center
**Deliverables:** typed WS handling + Zustand store; TanStack Query loads; Command Center fully live (hero P&L, kill-switch gauge, market context strip, dense stat grid, equity curve, sleeve strip, activity feed, system health) with value-ticks; stale-state verified end-to-end.
**Acceptance:** every value updates from real pushes and ticks on change; WS drop degrades honestly and recovers via REST refetch then resumes streaming.

### Phase F2 — Market grid + Charts + Depth
**Deliverables:** dense virtualized **Market** grid (all columns, heat cells, sparks, saved scans, column chooser, group-by-sleeve); **Charts** (TradingView + VWAP/EMA/ORB/ATR overlays + volume + OI/IV sub-panes) with **signal/trade markers** that open the Gate Trail in the Inspector; **depth/order-book** panel; multi-chart grid.
**Acceptance:** Market grid streams hundreds of live rows at ~60fps; sorting/filtering/saved-scans work; a chart plots real signals/trades and a marker opens its gate trail; quotes never freeze-as-live.

### Phase F3 — Positions + Sleeves
**Deliverables:** dense virtualized **Positions** table (grouped by sleeve + subtotals, sparks, R-at-risk, R-multiple, MAE/MFE, distance badges, F&O leg expansion + net Greeks, footer totals, guarded actions); **Sleeves** screen (cap vs deployed vs margin-bounded headroom, P&L sparks, mini equity curves, guarded toggles, allocation donut with idle cash).
**Acceptance:** positions reflect/reconcile with backend live; a spread shows legs + net max-loss/Greeks; disabling a sleeve blocks new entries without force-closing and says so.

### Phase F4 — Signals + Gate Trail + Rejection Analytics
**Deliverables:** **Gate Trail** component (pass/reject nodes, score bars, halt-on-reject, confidence + LLM node, resolve animation); Signals list + detail + context; **Rejection analytics** panel (which gates reject most, reasons, near-misses).
**Acceptance:** a live evaluation animates its trail; a reject halts at the failing gate; "why didn't it trade X?" is answerable from this screen; rejection analytics aggregate correctly over a window.

### Phase F5 — Option Chain + Greeks
**Deliverables:** full **Option Chain** grid (calls/puts, OI/OI-chg/IV/Greeks heat cells, ATM highlight, ITM shading, expiry selector); **OI buildup heatmap**; summary band (PCR, Max Pain, CE/PE OI, IV skew, DTE, VIX); strike → Inspector eligibility readout; highlight the strikes the engine's structures would use.
**Acceptance:** chain streams live OI/IV/Greeks; heatmaps render with the diverging scale; Max Pain/PCR/skew compute and update; selecting a strike shows pipeline eligibility.

### Phase F6 — Risk + Analytics
**Deliverables:** **Risk** screen (portfolio heat gauge + contributing-R table, **correlation matrix** heatmap + cluster flags, exposure breakdowns, margin live/used + timeline, leverage band gauge, drawdown curve + kill-switch history); **Analytics** suite (equity + drawdown curves, KPIs incl. expectancy in R, breakdowns by sleeve/setup/instrument/side, R-multiple + hold-time histograms, hour/weekday performance heatmaps; sim vs live separated).
**Acceptance:** open R and kill-switch proximity match backend; correlation matrix flags clusters; analytics compute from real trade data only and clearly separate sim vs live.

### Phase F7 — Audit + trade reconstruction
**Deliverables:** virtualized searchable/filterable **Audit** log; correlation-id **trade reconstruction** (gate trail as-was + sizing math + order lifecycle + outcome); export.
**Acceptance:** any past trade is fully reconstructable on one page; search/filter performant on a large log via virtualization.

### Phase F8 — Controls + Settings
**Deliverables:** **Controls** (pause/resume, hold-to-confirm Flatten-All with count/notional, sleeve toggles, multi-step **Go-Live flip** with checklist + type-`LIproceed to F6 and after that verify all the things are perfect in the frontend 0,1,2,3,4,5,6VE`, guarded kill-switch reset); **Settings** config editor (bound-checked, audit-logged), connection/alerts/layout management.
**Acceptance:** no critical action fires from a single accidental click; Go-Live requires the full sequence and visibly changes mode app-wide; out-of-bounds config edits are blocked or force explicit override.

### Phase F9 — Multi-monitor, mobile Watch, polish, hardening
**Deliverables:** panel **pop-out** to separate windows with shared live state (BroadcastChannel + leader tab); responsive **mobile Watch** mode (P&L, kill-switch gauge, positions summary, activity feed, emergency controls only); final a11y pass (AA, keyboard, live regions); performance pass (tick-storm + dense grids + 10k-row queries); empty/error/loading states across all screens in interface voice; self-critique pass ("every element earns its place").
**Acceptance:** a panel runs on a second monitor sharing live state; emergency controls work from a phone with hold-to-confirm; shell stays smooth under a tick storm and large queries; every screen has intentional empty/error/loading states; reduced-motion fully honored.

---

## Appendix A — Screen → Backend Data Map

| Screen | Reads | Acts |
|---|---|---|
| Workspace | composes any of the below | layout save/load |
| Command Center | account, day PnL, open R, sleeves, market context, health | pause, flatten (guarded) |
| Market | tracked instruments live quotes + RVOL/VWAP/OI/IV + signal state | open chart, add to layout |
| Charts | candles/history, overlays data, signals/trades, depth | — |
| Positions | open positions, structures, Greeks, LTP stream, MAE/MFE | close/modify (guarded) |
| Signals | signal events + gate results + confidence + LLM + rejection aggregates | — |
| Option Chain | chain (OI/IV/Greeks per strike), PCR, Max Pain, skew | — |
| Sleeves | per-sleeve cap/deployed/margin/PnL/curve | sleeve enable/disable |
| Risk | heat, correlation, exposure, margin, leverage, drawdown | kill-switch reset (guarded) |
| Analytics | trade history → KPIs, curves, breakdowns, heatmaps | period select |
| Audit | audit log + reconstruction by correlation id | export |
| Controls | mode, pre-live checklist, engine state | pause, flatten, sleeve toggle, mode flip, ks reset |
| Settings | risk + strategy config, connection, alerts, layouts | edit config (bound-checked, audited), manage layouts |

## Appendix B — API Contract the Frontend Expects (align with backend §9 + Appendix B)

```
REST (loads)
  GET /api/account            -> { live_capital, available_margin, used_margin, deployed_pct, mode }
  GET /api/pnl/today          -> { realized, unrealized, net, pct_of_capital, killswitch_limit, killswitch_used, equity_curve[] }
  GET /api/market             -> [ { instrument, sleeves[], ltp, chg, chg_pct, spark[], rvol, vwap_dist,
                                     or_state, vol_vs_avg, day_range:{lo,hi,pos}, oi, oi_chg, iv, iv_rank,
                                     pcr?, fno_ban, signal_state, eligible } ]
  GET /api/chart/{instrument} -> { candles[], overlays:{vwap[],emas{},or_box,atr_stop,sr[]}, markers[], depth:{bids[],asks[]} }
  GET /api/positions          -> [ { id, instrument, sleeve, side, qty, entry, ltp, spark[], stop, target,
                                     R_at_risk, R_multiple, unrealized, mae, mfe, time_held, state,
                                     structure?:{legs[], net_max_loss, greeks{delta,theta,gamma,vega}, iv, dte} } ]
  GET /api/sleeves            -> [ { sleeve, cap_pct, deployed, margin_headroom, day_pnl, cum_pnl, curve[],
                                     wins, losses, avg_R, enabled, positions } ]
  GET /api/risk               -> { open_R, portfolio_limit_R, max_positions, heat[], correlation_matrix,
                                   clusters[], exposure:{by_sleeve,by_sector,by_side}, margin:{used,available,timeline[]},
                                   leverage_x, drawdown_curve[], killswitch_history[] }
  GET /api/signals?filter=    -> [ { id, ts, instrument, sleeve, setup, gates:[{name,pass,score}],
                                     confidence, llm:{sentiment,event_risk,veto,reason}, action, size?, reject_gate? } ]
  GET /api/signals/rejections -> { by_gate[], by_reason[], near_misses[] }
  GET /api/optionchain/{u}    -> { expiry, strikes:[ { strike, call:{ltp,oi,oi_chg,iv,volume,delta,theta,gamma,vega},
                                     put:{...} } ], pcr, max_pain, ce_oi, pe_oi, iv_skew[], vix, dte, suggested_strikes[] }
  GET /api/analytics?period=  -> { equity_curve[], drawdown_curve[], kpis:{win_rate,profit_factor,expectancy_R,
                                   avg_win_R,avg_loss_R,max_dd,sharpe,trades}, by_sleeve[], by_setup[], by_instrument[],
                                   r_histogram[], holdtime_histogram[], hour_heatmap[], weekday_heatmap[], dataset:"sim"|"live" }
  GET /api/audit?...          -> paginated events; GET /api/audit/{correlation_id} -> full reconstruction
  GET /api/config             -> { risk{...}, strategy_params{...}, bounds{...} }
  GET /api/health             -> { feed, token, token_expiry, last_reconcile, rate_limit_headroom, loop_heartbeat, session_state, error_rate }
  GET /api/prelive-checklist  -> { compliance_tagging, failsafe_rehearsed, reconcile_clean, alerts_confirmed }
  GET /api/layouts            -> saved workspace layouts;  PUT /api/layouts -> persist

REST (actions — audited + UI-guarded)
  POST /api/controls/pause            { paused }
  POST /api/controls/flatten          { confirm:true }
  POST /api/controls/sleeve/{sleeve}  { enabled }
  POST /api/controls/mode             { mode, confirm_token:"LIVE" }
  POST /api/controls/killswitch/reset { confirm:true }
  POST /api/positions/{id}/close      { confirm:true }
  POST /api/positions/{id}/modify     { stop?, target? }
  PUT  /api/config                    { path, value }   // bound-checked server-side

WS (push — typed)
  price_update     { instrument, ltp, chg_pct, ts }     // also drives Market grid + Ticker
  quote_update     { instrument, rvol, vwap_dist, oi, oi_chg, iv, iv_rank, ... }
  pnl_update       { realized, unrealized, net, killswitch_used }
  position_update  { ...position }     position_closed { id, realized }
  signal_evaluated { ...signal with gate trail }        // drives live Gate Trail
  order_event      { id, status:placed|partial|filled|rejected, reason?, filled_qty? }
  chain_update     { underlying, expiry, strike-level OI/IV/Greeks deltas }
  health_update    { feed, token, rate_limit_headroom, loop_heartbeat, session_state }
  alert            { kind:killswitch|safe_exit|reconcile_mismatch|feed_down|token_fail, message, severity }
  mode_changed     { mode }                              // drives the Mode Frame
```

---

*End of v2 specification. Density is the brief — execute it with hierarchy and micro-visualizations so it reads as signal. Mode is never ambiguous; stale is never shown as live; critical actions resist accident; numbers are tabular and honest. The Gate Trail and Mode Frame are where this product is remembered.*
