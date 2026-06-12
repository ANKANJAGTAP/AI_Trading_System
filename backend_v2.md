# Backend Build Specification — AI Algorithmic Trading Platform

> **Version:** v2 (hardened). Adds: precise options R-sizing, capital-lock vs margin model, crash-recovery position adoption, candle gap reconciliation, corporate-action handling, partial-fill/rejection handling, rate-limit governor.
> **Audience:** This document is the authoritative build spec for an implementing engineer / Claude Opus.
> **Scope:** Backend only (data, decision pipelines, risk, execution, monitoring). A React dashboard is specified at the API contract level.
> **Market:** Indian markets via **Zerodha Kite Connect**. NSE/BSE equities + F&O, and MCX commodities.
> **Reality rule:** No dummy data, no synthetic feeds, no fabricated candles anywhere. Every input is real Kite data. The only non-real element permitted is the **simulated-fill execution mode** (real signals, real prices, no real money) which exists purely as a pre-live safety stage and is flipped to live manually by the operator.

---

## 0. Read This First — Philosophy & Non-Negotiables

These rules override any later detail if they ever conflict.

1. **No profit is guaranteed.** The system maximizes the *probability* of edge and *hard-caps* loss. Capital preservation outranks profit capture in every decision.
2. **Think in R, not in lots.** `R` = the rupee amount risked on a single trade (a fixed % of live capital). Position size is *derived* from R and the stop distance — never from "how many lots can I afford." This is the single most important behavioural difference from losing retail traders and must be enforced structurally (the system cannot place a trade whose risk it has not first computed in R).
3. **The pipeline is the decision-maker.** A deterministic, auditable gate pipeline decides every trade: every gate returns PASS or REJECT (or a 0–1 score). All gates must pass to proceed. The LLM layer can only *veto* or *contextualize* — it can never *originate* a trade.
4. **Risk engine is upstream of execution.** No order can reach the broker without passing the central Risk Engine (sizing, margin, sleeve cap, portfolio heat, kill-switch). There is no bypass path.
5. **Capital is read live, every session.** The system queries live available margin/funds from the broker at session start and sizes everything as a percentage of that. It is capital-agnostic: works identically at ₹50k or ₹50L.
6. **Fail safe, not fail open.** On any disconnect, auth failure, data gap, or unhandled error, the system moves toward *flat and halted*, never toward *more exposure*.
7. **Everything is logged.** Every signal, gate result, sizing calculation, order, fill, and error is written to an immutable audit log with timestamps and the full reasoning chain.

---

## 1. System Architecture Overview

```
                         ┌─────────────────────────────────────────┐
                         │            OPERATOR (you)                 │
                         │   React Dashboard  +  Email Alerts        │
                         └───────────────▲───────────────────────────┘
                                         │ REST / WebSocket
                         ┌───────────────┴───────────────────────────┐
                         │              FastAPI App                    │
                         │  (control plane, dashboard API, auth)       │
                         └───────────────▲───────────────────────────┘
                                         │
   ┌─────────────────────────────────────┼─────────────────────────────────────┐
   │                          ENGINE PROCESS (asyncio)                            │
   │                                                                              │
   │  ┌────────────┐   ticks   ┌──────────────┐  candles  ┌─────────────────────┐ │
   │  │ Kite Feed  │──────────▶│  Candle       │──────────▶│  Strategy Pipelines │ │
   │  │ WebSocket  │           │  Aggregator   │           │  (4 sleeves)        │ │
   │  └────────────┘           └──────┬───────┘           └──────────┬──────────┘ │
   │        │ (fast loop)             │ (slow loop, on candle close)  │ signals    │
   │        ▼                         ▼                               ▼            │
   │  ┌──────────────┐         ┌──────────────┐            ┌─────────────────────┐ │
   │  │ Risk Guards  │         │ Decision      │◀───────────│  Risk Engine        │ │
   │  │ (SL/TP/kill) │         │ Orchestrator  │            │  (R-sizing, margin, │ │
   │  └──────┬───────┘         │ + Confidence  │            │   heat, sleeve cap) │ │
   │         │                 │ + LLM Context │            └─────────────────────┘ │
   │         └────────────┬────┴──────────────┘                                     │
   │                      ▼                                                          │
   │              ┌──────────────────┐      ┌──────────────────────────┐            │
   │              │ Execution Layer  │─────▶│ Broker Adapter (Kite)     │            │
   │              │ sim-fill | live  │      │ smart orders OCO/GTT       │            │
   │              └──────────────────┘      └──────────────────────────┘            │
   └──────────────────────────────────────────────────────────────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         │   PostgreSQL + TimescaleDB     │  (ticks, candles, orders,
                         │           Redis                │   positions, audit, state)
                         └────────────────────────────────┘
```

**Two-loop principle (mandatory):**
- **Fast loop** — runs on every tick. Pure Python, sub-millisecond to low-millisecond latency, no LLM, no network calls. Only hard risk guards: stop-loss hit, target hit, trailing stop, kill-switch, square-off timer.
- **Slow loop** — runs only on candle close (or a discrete event such as a news trigger). This is where pipelines, the Risk Engine, the confidence model, and the LLM context layer run. The LLM is **never** on the tick path.

---

## 2. Technology Stack (decided)

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Ecosystem, Kite SDK, async support |
| Broker SDK | `kiteconnect` (Zerodha Kite Connect) | Mature, 10y intraday history, robust WebSocket |
| Async engine | `asyncio` + `websockets` | Single-process concurrency for feed + loops |
| API / control plane | FastAPI + Uvicorn | Dashboard API, control endpoints, WebSocket push |
| Time-series store | PostgreSQL 15+ with **TimescaleDB** | Hypertables for ticks/candles; SQL for everything else |
| Cache / state / bus | Redis | Live position state, fast↔slow loop event bus, locks |
| Scheduler | APScheduler | Pre-market screen, token refresh, EOD jobs |
| Numerics | pandas, numpy, `ta` / `pandas-ta` | Indicators (VWAP, ATR, EMA, RSI) |
| Options math | `mibian` or `py_vollib` | IV, Greeks (delta/theta/vega/gamma) |
| LLM | **Anthropic Claude** — Sonnet (news synthesis + pre-trade sanity veto), Haiku (high-volume news classification) | Off the hot path; low cost |
| Dashboard | React (Vite) + Recharts | Operator console |
| Packaging / deploy | Docker + docker-compose, `systemd` unit on VPS | Always-on, restart-on-failure |
| Alerts | SMTP email (configurable provider) | Operator notifications |
| Secrets | `.env` + OS keyring / cloud secret manager | Never hardcode API keys |

**VPS:** AWS / GCP / Azure (decision pending — any works). Requirement: always-on Linux VM, low latency to NSE (Mumbai region preferred — AWS `ap-south-1`), persistent disk for the DB, automatic restart.

---

## 3. Capital, Sleeves & Allocation Model

- **Capital source:** read live from Kite `margins()` at session start and on demand. All sizing is a % of live available capital. No hardcoded capital number anywhere.
- **Four sleeves** with **default caps** (operator-tunable in config):

| Sleeve | Default cap (% of capital) | Instruments |
|---|---|---|
| Intraday Stocks | 30% | NSE equity, MIS |
| F&O | 30% | Index + stock options (weekly & monthly) |
| Swing Stocks | 30% | Nifty-100 + strong mid/large caps, CNC |
| MCX Commodities | 10% | Gold, GoldM, Silver, SilverM, Crude, Natural Gas (futures + liquid options) |

- **Allocation is signal-driven within bounds.** Capital flows to wherever a *qualifying* signal exists, subject to three hard ceilings checked in this order: (1) total **portfolio risk limit** (max aggregate open R), (2) **per-sleeve cap**, (3) **live available margin**. If any ceiling is hit, the trade is rejected or downsized.
- No sleeve may borrow another sleeve's cap. Unused cap stays idle (cash is a valid position).
- **Capital-locked vs available-margin (mandatory clarification):** sleeve caps are limits on *deployed capital / open risk per sleeve*, **not** a guarantee of free margin. Swing (CNC) positions lock real cash for days/weeks; intraday and F&O (MIS) consume margin that the broker computes live. The system must treat **live available margin from Kite as the final, non-negotiable clamp** on every order, regardless of how much sleeve cap is nominally "free." Concretely: (a) recompute available margin before each order via `order_margins`/`basket_margins`; (b) capital locked in open swing holdings reduces what intraday/F&O can deploy the next session, and the allocator must account for this rather than assuming the full sleeve cap is spendable; (c) if sleeve cap says "room" but live margin says "no," **live margin wins** and the trade is rejected or downsized.

---

## 4. Core Risk Model (applies to all sleeves)

Implement exactly. These are the parameters the operator confirmed.

```yaml
risk:
  per_trade_risk_pct:        # R as % of live capital
    min: 1.0
    max: 2.0
    default: 1.0
  daily_max_loss_pct:        # kill-switch trigger
    min: 1.0
    max: 4.0
    default: 3.0
  # Position sizing (image-confirmed):
  #   Stop-Loss % is defined as (entry_price - stop_price) / entry_price.
  #   Capital allocated = Risk Amount / Stop-Loss %   (== Quantity * entry_price)
  #   Quantity = Risk Amount (R, in ₹) / (entry_price - stop_price)
  # Max concurrent positions (image-confirmed formula):
  #   Max Positions = Portfolio Risk Limit / Risk Per Trade
  portfolio_risk_limit_pct:  # max aggregate open R at once
    default: 6.0             # e.g. 6% / 1% per trade => max 6 open positions of 1R
  leverage:
    mode: only_when_needed
    target_effective_exposure: [1.5, 3.0]   # never max available
  per_instrument_cap_pct: 15.0   # no single instrument > this % of capital
```

**Sizing algorithm (canonical):**
1. `R_rupees = live_capital * per_trade_risk_pct/100`
2. `stop_distance = abs(entry_price - stop_price)` (price-based instruments)
3. `raw_qty = floor(R_rupees / stop_distance)` → round to lot size for F&O/MCX
4. Clamp by: per-instrument cap, sleeve remaining cap, portfolio remaining risk, **live available margin** (via Kite margin/`order_margins`).
5. If clamped qty < 1 lot / 1 share → **REJECT** (cannot size within risk).

**Sizing by instrument type (mandatory precision):**
- **Equity (intraday/swing):** `qty = floor(R_rupees / (entry_price − stop_price))`.
- **Futures (F&O/MCX):** same as equity but on the futures price, then round down to whole lots; `risk_per_lot = lot_size × (entry − stop)`; `lots = floor(R_rupees / risk_per_lot)`.
- **Naked option BUY:** stop is on the **premium**. `risk_per_lot = lot_size × (entry_premium − stop_premium)`; `lots = floor(R_rupees / risk_per_lot)`.
- **Defined-risk structure (credit/debit spread, condor):** R maps to the structure's **known max loss**. `max_loss_per_lot = (defined max loss of the structure per lot, net of premium received)`; `lots = floor(R_rupees / max_loss_per_lot)`. The structure's max loss is computed at build time and must be finite (this is *why* naked selling is banned — its max loss is not finite and cannot be R-sized).
- In all cases the final lot/share count is additionally clamped by live available margin; sub-1-lot/share → REJECT.

**Kill-switch:** if realized + unrealized PnL for the day ≤ `-daily_max_loss_pct`, the system: (a) blocks all new entries, (b) optionally flattens open positions (config flag, default = flatten), (c) emails the operator, (d) stays halted until manual reset next session.

**Portfolio heat & correlation:** track total open R and flag clusters (e.g. >2 highly correlated positions in one sector). Correlated cluster counts as concentrated risk against the portfolio limit.

---

## 5. The Four Strategy Pipelines (gate-based)

Each pipeline is a deterministic funnel: `Universe → Regime/Context → Signal → Confirmation → Risk+Margin Gate → Execution → Management`. Every gate returns PASS/REJECT or a 0–1 score. **All gates must pass.** Gate scores feed the confidence model (Section 6).

> All numeric thresholds below are **professional defaults**. They live in a single `config/strategy_params.yaml` and must be tunable without code changes. Calibrate during the simulated-fill phase.

### 5.1 Intraday Stocks Pipeline

**Universe (pre-market screen):** dynamic, profit-oriented liquid set from Nifty 50 / Nifty 100.
- Liquidity gate: avg daily volume ≥ 5 lakh shares (preferred 20–50 lakh); bid-ask spread ≤ 0.10%.
- Gap classification: tag gap-up/gap-down (> 0.5%); treat the first candle specially.

**Regime gate:** index vs its VWAP, India VIX level, trending vs choppy day classification. Choppy → disable breakout setups; trending → enable.

**Opening Range:** mark the **9:15–9:30** 15-minute high/low. Entry window **9:30–11:00**.

**Signal — two setups:**
- *ORB (Opening Range Breakout):* price breaks above OR high (long) / below OR low (short); volume expands.
- *VWAP Pullback:* strong trend, price above (below) VWAP, pulls back to VWAP, VWAP holds as support (resistance), confirming candle, enter.

**Confirmation gates:**
- Price on correct side of VWAP (long only above, short only below).
- Relative volume (RVOL): ORB ≥ 1.5 (ideal 2.0); VWAP pullback 1.2–1.5.
- Professional filters (ORB): gap-up, above VWAP, sector strong, high relative volume, market trend supports the trade.

**Time gates:** last new entry **2:30 PM**; **soft exit 3:10 PM** (begin reducing); **hard force-exit 3:20 PM** (flatten all intraday). Reward target **1.5R–3R**.

**Stop:** below OR low / pullback low (long), mirror for short.

### 5.2 F&O Pipeline

**Eligibility gate:** underlying not in F&O ban; chosen strike liquid (OI + volume + tight spread). Weekly & monthly both in scope; index options + stock options.

**Volatility regime gate (first, decisive):** compute **IV Rank / Percentile**.

| IV environment | IV Rank | Preferred strategy |
|---|---|---|
| Low | < 20 | Option **buying** (debit) |
| Medium | 20–70 | Directional **spreads** |
| High | > 70 | Premium **selling** (credit spreads) |

**Strategy mix (default, operator-confirmed):** 70% credit spreads, 20% debit spreads, 10% naked **buying**.
**Hard rule:** **No naked option selling, ever.** Defined-risk structures only. Sellers express views via credit *spreads* (capped loss).

**DTE gate:**
- Swing buying: 20–45 DTE. Positional buying: 30–60 DTE. Weekly buying: 3–10 DTE.
- **Avoid:** 0 DTE, 1 DTE, expiry-day gambling — unless an explicitly enabled pure-intraday module.
- Credit spreads: sell 15–45 DTE, **close early** (book ~50% of max premium, then exit).

**Direction + OI gate:** combine spot signal with OI interpretation —
- Price↑ + OI↑ = long buildup (bullish); Price↓ + OI↑ = short buildup (bearish); Price↑ + OI↓ = short covering; Price↓ + OI↓ = long unwinding.
- PCR and Max Pain as context only.

**Greeks gate:**
- **Theta:** if buying, projected theta decay over expected hold must not exceed expected favourable move → else REJECT.
- **Delta** (strike selection): buyers ATM **0.40–0.60**; credit spread short leg **0.15–0.30**; iron condor legs **0.10–0.20**. Avoid far-OTM lottery tickets.
- **Vega/IV-crush:** if IV high and buying, prefer spread or REJECT.
- **Gamma:** flag near-expiry gamma risk on short legs.

**Structure selection:** map (IV regime + direction + risk budget) → concrete structure (bull call / bear put / credit spread / condor), max-loss known and within R.

**Risk + margin gate:** SPAN+Exposure margin available; structure max-loss ≤ R; sleeve & portfolio ceilings.

**Management:** buyers exit before decay accelerates; sellers book ~50% premium or exit on spot breach of short strike; adjust on IV spikes.

### 5.3 Swing Stocks Pipeline

**Universe:** Nifty-100 + large cap + strong mid caps (dynamic profit-oriented screen). Daily/weekly candles (full history available from Kite — realistic backtests possible).

**Corporate-action handling (mandatory for swing):** splits, bonuses, and dividends break raw daily candles, the 200 DMA, and held-position quantity/cost math. The system must use **split/bonus-adjusted** historical series for all swing indicators and screens, detect corporate actions on held positions (from the instruments feed / a corporate-actions source), and adjust stored stops, targets, average price, and quantity accordingly. Never compute a 200 DMA or a stop off an unadjusted series across a split.

**Fundamental filter (junk removal) — practical screen:**

| Metric | Threshold |
|---|---|
| Market cap | > ₹5,000 Cr |
| ROE | > 15% |
| Revenue growth | > 10% |
| EPS growth | > 15% |
| Debt / Equity | < 0.5 |
| Promoter holding | stable or rising |
| Avg daily volume | > 10 lakh shares |
| Price | > 200 DMA |

(Fundamental data source: Indian fundamentals API — see Section 7.)

**Market regime gate:** broad market uptrend (index above key MAs, breadth healthy). Bear market → reduce exposure / go cash.

**Sector strength gate:** stock's sector outperforming index; positive relative strength.

**Technical setup (daily/weekly):** trend (above key MAs) + pullback-to-support **or** base/consolidation breakout, with volume confirmation. (Pattern matching belongs here — deep daily history available.)

**Event gate:** if earnings/major event falls within the intended holding window → reduce size or skip (configurable; default reduce-or-skip). Avoid surprise risk.

**Risk gate:** stops are wide (ATR-based / swing-low) ⇒ **smaller size**. Account for **overnight gap risk** — never oversize. Portfolio heat & sector correlation check.

**Holding horizon:** target hold **5–20 trading days**; **soft limit 30**, **hard limit 60** trading days. If thesis hasn't played out by the soft/hard limit → exit and redeploy.

**Stops:** swing-low / support / ATR multiple. Trail on daily candles; exit on trend break; partial book at target; risk-off before major events.

### 5.4 MCX Commodities Pipeline

Reuses the intraday + swing logic, adapted to commodities.
- **Instruments:** Gold, GoldM, Silver, SilverM, Crude Oil, Natural Gas (liquid futures; options only where liquid).
- **Sessions:** extended hours — engine must support MCX session calendar (roughly 09:00 to ~23:30 IST; load exact timings from exchange calendar). Square-off timers and last-entry gates use MCX session, not equity session.
- **Intraday MCX:** VWAP / ORB-style momentum adapted to the commodity's session open.
- **Swing MCX:** trend-following on daily futures; no fundamental filter (use inventory/macro context via the LLM news layer instead — optional, contextual only).
- **Risk:** same R-unit model; commodities can be volatile and gap on global cues, so honour `target_effective_exposure` and never max-leverage.

---

## 6. Decision Orchestrator, Confidence & LLM Context Layer

**Do we need the seven-agent swarm?** No. For real money, a literal multi-LLM swarm adds latency, cost, non-determinism, and failure points. The chosen design keeps the *structure* (named modules) without the fragility:

- **Decision modules (deterministic code, not LLMs):** Technical, Volatility/Greeks, Microstructure/OI, Fundamental, Regime. Each emits a 0–1 score + PASS/REJECT for its gates.
- **Decision Orchestrator:** runs the relevant pipeline, collects gate results, and only proceeds if all hard gates PASS.
- **Confidence model:** combines gate scores into a single 0–1 confidence. Confidence maps to size *within* the R cap — strong agreement → up to full 1R; weak → fraction of R or skip. (Included for robustness, as requested. Implement as a transparent weighted function; weights live in config, no opaque ML required for v1.)
- **LLM Context & News layer (single Claude call, slow loop only):** ingests structured news/events for the candidate instrument, returns a structured risk signal `{sentiment, event_risk, veto: bool, reason}`. It can **only veto or downsize** a trade the pipeline already approved. It can never create a trade, and it is never on the tick path. If the LLM call fails or times out → treat as "no veto, no boost" (fail neutral) and log it.

```
pipeline gates ──▶ all PASS? ──no──▶ skip
       │ yes
       ▼
 confidence score ──▶ Risk Engine sizing (R, margin, caps)
       │
       ▼
 LLM context veto? ──yes──▶ skip / downsize (logged)
       │ no
       ▼
 Execution Layer
```

---

## 7. Data Layer

**Market data (Kite Connect):**
- Instruments master (full dump, refreshed daily; map tradingsymbol ↔ instrument_token ↔ lot size ↔ expiry ↔ strike).
- Historical candles for backfill (Kite provides deep daily history; intraday history far longer than Groww — backfill on first run and nightly).
- Live **WebSocket** tick stream (`KiteTicker`) for subscribed instruments; tag mode (LTP/quote/full) per need. Full mode for instruments needing depth/OI.
- **Candle aggregation client-side** from ticks (the feed pushes ticks, not pre-formed candles): build 1m/3m/5m/15m/daily OHLCV; for F&O/MCX attach OI snapshot at candle close. Persist closed candles immediately.
- **Gap reconciliation on reconnect (mandatory):** if the WebSocket drops, candles built during the outage have holes. On reconnect, the aggregator must detect the gap (last persisted candle vs current time), **backfill the missing candles from the Kite historical API**, persist them, and only then resume slow-loop decisions. Decisions must not run on a known-incomplete series.

**Rate-limit governor (mandatory):** Kite enforces hard limits (orders/sec, quotes/sec, historical-data/sec, per-minute and daily order caps). Implement a central throttling/queue layer that all REST calls pass through: token-bucket per endpoint class (quote, historical, order), backoff-and-retry on 429/`TooManyRequests`, and a daily order-count guard that alerts and halts new entries before the exchange cap is hit. No component may call Kite REST directly outside this governor.

**Own database archive (mandatory):** persist every closed candle and (optionally) raw ticks to TimescaleDB hypertables. This is the long-term store the strategies and future calibration depend on — start archiving from day one so granular history accrues over time. `candle` row order mirrors a standard payload: `ts, open, high, low, close, volume, oi`.

**Data Kite does NOT provide → external sources:**
- **Fundamentals / financials** (for the swing pipeline): an **Indian fundamentals API** (operator-provided). Define a thin `FundamentalsProvider` interface so the concrete API is swappable: `get_fundamentals(symbol) -> {market_cap, roe, revenue_growth, eps_growth, debt_equity, promoter_holding_trend, ...}`.
- **News** (required across sleeves — feeds the LLM context layer): a `NewsProvider` interface: `get_news(symbol|index, since) -> [{headline, body, source, ts}]`. The LLM converts these into the structured risk signal. News is **contextual/veto only**, never a primary trigger.

**Auth automation:** Kite access token expires daily. Implement automated login (TOTP-based) to refresh the token before market open each day; store securely; alert operator on failure. Never proceed to live trading with a stale/failed token — halt and email.

---

## 8. Execution & Order Management

- **Broker abstraction:** all broker calls go through a `BrokerAdapter` interface (concrete: `KiteAdapter`). This keeps the system broker-agnostic for any future switch.
- **Two execution modes (single switch, operator-controlled):**
  - `simulated_fill` (**default**): real signals, real live prices, realistic fill simulation (use live bid/ask + slippage + cost model), **no real orders sent**. Tracks a shadow portfolio and PnL.
  - `live`: real orders to Kite. Operator flips to live **manually** when satisfied with simulated performance (no automatic promotion).
- **Order types:** dynamic — market or limit chosen per setup; use **smart orders (OCO / GTT)** for bracketed entries (entry + stop + target) where supported.
- **Cost model (always on, both modes):** brokerage, STT (note: options STT bites hard on expiry), exchange fees, GST, stamp duty, slippage. Costs are subtracted in simulated PnL so the live transition holds no surprises.
- **Position book:** single source of truth in Redis (live state) mirrored to Postgres (durable). Reconcile against Kite `positions()`/`holdings()` on every cycle; alert on mismatch.
- **Partial fills & order rejections (mandatory):** handle each order's full lifecycle, not just "placed." On **partial fill**, size the protective stop/target bracket to the *actually filled* quantity, and decide per config whether to chase the remainder (limit re-quote within a price band) or cancel the unfilled balance — default: cancel remainder, manage what filled. On **rejection** (margin, circuit, freeze-quantity, ban, exchange reject), do not retry blindly: log the reason, surface it, and retry only if the cause is transient (e.g. network) within a capped retry count. Freeze-quantity limits on large F&O orders must be respected by slicing into allowed clips.
- **Cold-start / crash recovery (mandatory):** on engine restart, the broker is the source of truth. Before resuming, the system must **adopt existing open positions and pending orders from Kite**, rebuild each position's R-state (entry, quantity, and reconstructed/reattached stop & target), re-arm the fast-loop guards, and reconcile against the durable Postgres book. If a position cannot be safely reconstructed (e.g. missing stop), flag it for operator attention rather than leaving it unmanaged. The system never resumes trading with unmanaged live exposure.

**Fail-safe behaviour (mandatory):** on WebSocket disconnect, auth failure, repeated API errors, data staleness, or unhandled exception → **safe-exit all positions** (square off / close), block new entries, email the operator, and halt until manual restart. Never hold exposure through an unknown state.

---

## 9. Monitoring, Dashboard, Alerts, Audit

**React dashboard (operator console)** — backend exposes these via FastAPI (REST + WebSocket push):
- Live capital, available margin, per-sleeve utilization vs caps.
- Open positions with live PnL, R-at-risk, stops/targets.
- Today's signals: each with its full gate trail (which gates passed, scores, confidence, LLM verdict).
- Realized/unrealized PnL, daily-loss vs kill-switch line, portfolio heat.
- Mode indicator (SIMULATED / LIVE) — prominent, unmistakable.
- Controls: pause/resume engine, flatten-all (panic button), per-sleeve enable/disable, **mode flip (with explicit confirm)**, kill-switch reset.

**Email alerts (SMTP):** trade entered/exited, stop/target hit, kill-switch triggered, safe-exit event, auth/token failure, data-feed disconnect, position reconciliation mismatch, daily EOD summary.

**Audit log (immutable, Postgres):** every signal, gate result + score, sizing calculation (R, qty, clamps applied), order request, broker response, fill, LLM verdict + reason, error, and mode change — all timestamped with a correlation id so any trade can be fully reconstructed.

---

## 10. Compliance Note

SEBI retail-algo framework and broker algo-API approval / order-tagging requirements were confirmed as handled by the operator. Implementation must still: tag orders as required by the broker/exchange, respect rate limits, and keep the audit trail that the framework expects. Do not enable `live` mode until tagging/compliance settings are wired.

---

# BUILD PHASES

Build strictly in order. Each phase is self-contained with explicit deliverables and acceptance criteria. Do not start a phase until the previous phase's acceptance criteria pass against **real Kite data**.

### Phase 0 — Foundations
**Objective:** project skeleton, infra, secrets, DB, broker auth.
**Deliverables:**
- Repo structure (`/engine`, `/api`, `/strategies`, `/risk`, `/execution`, `/data`, `/broker`, `/llm`, `/dashboard`, `/config`, `/migrations`, `/ops`).
- Central typed config loader (`config/*.yaml` + `.env`); all parameters from this spec present and tunable.
- Docker + docker-compose (app, Postgres+TimescaleDB, Redis); `systemd` unit; restart-on-failure.
- DB schema + migrations: instruments, ticks (hypertable), candles (hypertable), orders, fills, positions, signals, gate_results, audit_log, daily_pnl, config_state.
- `BrokerAdapter` interface + `KiteAdapter` skeleton; **automated daily TOTP login + token refresh**; secure token storage; failure alert.
**Acceptance:** containers come up; Kite auth succeeds and refreshes automatically; a live `margins()` and `instruments()` call returns real data and persists.

### Phase 1 — Market Data Layer
**Objective:** real-time feed + candle archive.
**Deliverables:**
- Instruments master loader (daily refresh; symbol↔token↔lot↔expiry↔strike map).
- Historical backfill from Kite (daily deep history + intraday) into hypertables; nightly incremental.
- `KiteTicker` WebSocket subscription manager (mode selection, reconnect with backoff, heartbeat/staleness detection).
- Candle gap reconciliation: on reconnect, backfill missing candles from the historical API before resuming decisions.
- Rate-limit governor: central token-bucket throttle for all Kite REST calls (quote/historical/order classes), 429 backoff-retry, daily order-count guard.
- Client-side candle aggregator (1m/3m/5m/15m/daily; OI snapshot at close for F&O/MCX); persist closed candles immediately.
- Indicator library wiring: VWAP, ATR, EMA/SMA (incl. 200 DMA), RSI, RVOL; options IV + Greeks (delta/theta/vega/gamma) + IV Rank/Percentile.
**Acceptance:** live ticks flowing for a real subscription set; candles built and stored matching Kite's own candles within tolerance; indicators + Greeks computed on real data; reconnect verified by forced disconnect.

### Phase 2 — Risk & Capital Engine
**Objective:** the upstream gate everything must pass. Build before any strategy.
**Deliverables:**
- Live capital/margin reader; sleeve cap manager (Section 3); allocation ceilings (portfolio risk → sleeve cap → live margin).
- R-unit sizing engine (Section 4 canonical algorithm) incl. lot rounding, per-instrument cap, leverage bound, margin clamp; rejects sub-1-unit trades.
- Max-concurrent-positions = portfolio_risk_limit / per_trade_risk.
- Kill-switch (daily max loss) with block + optional flatten + alert + manual-reset.
- Portfolio heat & sector-correlation tracker.
**Acceptance:** given a real candidate (entry, stop, instrument), the engine returns a correct R-sized quantity respecting every ceiling, and correctly rejects when ceilings or margin block it; kill-switch trips on a simulated loss breach and halts new entries.

### Phase 3 — Execution & Order Management
**Objective:** order layer with sim-fill default + live, fail-safe.
**Deliverables:**
- Execution Layer with `simulated_fill` (default) and `live` modes behind one operator switch.
- Realistic fill simulation using live bid/ask + slippage + full cost model (brokerage, STT, fees, GST, stamp).
- Smart orders (OCO/GTT) for bracketed entry/stop/target; market/limit selection.
- Order lifecycle handling: partial fills (size bracket to filled qty), rejections (reason-aware, no blind retry), freeze-quantity slicing.
- Cold-start / crash recovery: adopt open positions + pending orders from Kite, rebuild R-state, re-arm guards, reconcile to Postgres; flag unreconstructable positions.
- Position book (Redis live + Postgres durable) with reconciliation against Kite each cycle.
- Fail-safe handler: disconnect/auth/error → safe-exit all + block + alert + halt.
**Acceptance:** a Decision object routes to a simulated fill with correct cost-adjusted PnL and an OCO/GTT bracket created; a partial fill correctly resizes the bracket; a simulated restart adopts an existing open position and re-arms its guards; forced fault triggers safe-exit and halt; reconciliation flags an injected mismatch.

### Phase 4 — Strategy Pipelines
**Objective:** the four gate pipelines emitting scored signals.
**Deliverables:**
- Intraday Stocks pipeline (5.1) with exact gates/params.
- F&O pipeline (5.2) incl. IV-regime routing, DTE gate, Greeks gate, defined-risk structure builder, **no naked selling**.
- Swing Stocks pipeline (5.3) incl. fundamental screen (via `FundamentalsProvider`), regime, sector strength, event gate, holding-horizon limits.
- MCX pipeline (5.4) with extended-session calendar.
- All thresholds in `config/strategy_params.yaml`; each gate returns PASS/REJECT + 0–1 score.
**Acceptance:** on real live/historical data, each pipeline produces correct PASS/REJECT decisions with a full per-gate trail; a known disqualifying condition (e.g. F&O ban, choppy regime, fundamental fail, IV-regime mismatch) is correctly rejected.

### Phase 5 — Decision Orchestrator + Confidence + LLM Context
**Objective:** wire pipelines → confidence → risk → LLM veto → execution.
**Deliverables:**
- Orchestrator running the right pipeline per instrument/sleeve on the slow loop; fast-loop risk guards on the tick loop.
- Confidence model (transparent weighted gate-score combination → size within R).
- LLM Context & News layer (single Claude call; `NewsProvider` ingest; structured `{sentiment, event_risk, veto, reason}`; veto/downsize only; fail-neutral; logged).
- Full end-to-end flow: tick → candle close → pipeline → confidence → risk sizing → LLM veto → execution (sim-fill).
**Acceptance:** end-to-end, a real qualifying setup flows through to a simulated order with the complete reasoning chain in the audit log; LLM veto demonstrably blocks/downsizes a trade and fail-neutral on LLM error is verified.

### Phase 6 — Monitoring, Dashboard, Alerts, Audit
**Objective:** operator visibility & control.
**Deliverables:**
- FastAPI endpoints (REST + WebSocket push) for all dashboard data in Section 9.
- React dashboard: capital/sleeves, positions, signal trails, PnL vs kill-switch, prominent SIMULATED/LIVE indicator, controls (pause/resume, flatten-all, sleeve toggles, mode flip w/ confirm, kill-switch reset).
- SMTP email alerts for all listed events + EOD summary.
- Immutable audit log surfaced/queryable; correlation-id reconstruction of any trade.
**Acceptance:** dashboard reflects live engine state in real time; every alert type fires correctly; any trade is fully reconstructable from the audit log; controls work (flatten-all halts and squares off).

### Phase 7 — Go-Live & Operations
**Objective:** safe transition to real money.
**Deliverables:**
- Ops runbook: daily startup/shutdown, token-refresh verification, disaster recovery, DB backup, restart procedure.
- Pre-live checklist: compliance/tagging wired, rate-limit handling verified, fail-safe rehearsed, reconciliation clean, alerts confirmed.
- **Manual go-live procedure:** operator reviews simulated performance, then flips mode `simulated_fill → live` via the confirmed dashboard control. No automatic promotion. Recommend starting live at the **minimum** `per_trade_risk_pct` and a reduced portfolio risk limit, then scaling.
**Acceptance:** system runs unattended in `simulated_fill` across full real sessions (all sleeves, including MCX extended hours) with no fail-open events, clean reconciliation, and correct alerts — ready for the operator's manual live flip.

---

## Appendix A — Confirmed Parameter Reference (quick lookup)

**Risk:** per-trade 1–2% (default 1%); daily max loss 1–4% (default 3%); portfolio risk limit 6% default; leverage only-when-needed, effective 1.5–3x; per-instrument cap 15%. Sizing = R / stop-distance. Max positions = portfolio limit / per-trade risk.

**Intraday:** OR 9:15–9:30; entry 9:30–11:00; last entry 2:30; soft exit 3:10; hard exit 3:20; RVOL ORB ≥1.5 (ideal 2.0), VWAP-pullback 1.2–1.5; liquidity ADV ≥5L (pref 20–50L), spread ≤0.10%; reward 1.5R–3R; setups ORB + VWAP pullback; filters gap-up/above-VWAP/sector-strong/high-RVOL/trend-supports.

**F&O:** mix 70% credit / 20% debit / 10% naked buying; **no naked selling**; IV Rank <20 buy, 20–70 spreads, >70 sell; DTE swing-buy 20–45, positional 30–60, weekly 3–10, avoid 0–1/expiry gambling, credit sell 15–45 & close early (~50%); delta buyers 0.40–0.60, credit short 0.15–0.30, condor 0.10–0.20; OI buildup matrix; defined-risk only.

**Swing:** hold target 5–20d, soft 30, hard 60; universe Nifty-100 + large/strong-mid; fundamentals mcap >₹5000Cr, ROE >15%, rev growth >10%, EPS growth >15%, D/E <0.5, promoter stable/rising, ADV >10L, price >200DMA; regime uptrend; sector relative strength; ATR/swing-low stops; event gate reduce/skip.

**MCX:** Gold/GoldM/Silver/SilverM/Crude/NaturalGas; futures + liquid options; extended session calendar; intraday VWAP/ORB-style + swing trend; same R model.

## Appendix B — Key Interfaces (signatures to implement)

```
BrokerAdapter: login(); refresh_token(); margins(); instruments();
  historical(token, from, to, interval); subscribe(tokens, mode);
  place_order(...); place_gtt(...); place_oco(...); modify_order(...);
  cancel_order(...); positions(); holdings(); order_margins(orders)

FundamentalsProvider: get_fundamentals(symbol) -> dict
NewsProvider:        get_news(symbol_or_index, since) -> list[news]
LLMContextLayer:     assess(instrument, news, setup) -> {sentiment, event_risk, veto, reason}
RiskEngine:          size(entry, stop, instrument, sleeve, confidence) -> {qty, R, clamps} | REJECT
                     size_structure(structure, sleeve, confidence) -> {lots, R, max_loss} | REJECT  # defined-risk options
                     check_kill_switch(); portfolio_heat(); available_margin_clamp(order)
Pipeline.evaluate(instrument, ctx) -> {decision, gates:[{name, pass, score}], confidence}
Executor.execute(decision, mode) -> fill | partial | rejection   # mode in {simulated_fill, live}
Executor.adopt_open_positions() -> [reconstructed_position]      # cold-start recovery
RateGovernor.call(endpoint_class, fn, *args)                      # all Kite REST routed through this
```

---

*End of specification. Build phases in order; never bypass the Risk Engine; never send a real order in `simulated_fill` mode; fail safe, not open; log everything.*
