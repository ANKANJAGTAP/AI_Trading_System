# World-Class F&O Algorithmic Trading Platform — Architecture & Implementation Plan

**Project:** Evolution of `AI_Trading_System` into a best-in-class systematic F&O platform
**Instrument focus (Phase A):** NIFTY 50, FINNIFTY (Nifty Financial Services), SENSEX — options & futures
**Author:** Prepared for Manan (ANKANJAGTAP/AI_Trading_System)
**Version:** 1.0 — Design blueprint (implementation to follow in phased builds)
**Status:** Plan / architecture document. No live-trading changes are proposed until the safety items below are met.

---

## 0. How to read this document

This is the master blueprint. It is deliberately exhaustive because the goal is "world-class, state-of-the-art." It is organised around **five engineering pillars** plus the cross-cutting concerns (execution, risk, compliance, infra) that turn those pillars into a real platform:

1. **Data Layer** — acquiring, cleaning and storing 15–20 years of point-in-time-correct F&O data.
2. **Technical-Analysis Knowledge Base** — "teaching the engine" the full vocabulary of TA, market profile, and options analytics as a machine-readable feature library.
3. **Quant/ML Research & Training Stack** — labelling, modelling, and rigorous validation that train the engine on that history without fooling yourself.
4. **F&O Backtesting Engine** — an options-aware, bias-resistant simulator that is the single source of truth for "does this edge exist?"
5. **F&O Strategy/Signal Engine** — the live alpha pipeline that turns models + rules into defined-risk option structures for the three indices.

Each pillar has: *what world-class looks like*, *what you already have* (from your README), *the gap*, and *the concrete design*. A phased roadmap at the end sequences the work and maps it onto the P0 items already in your `upgrade.md`.

> **One honest framing up front (please read §1.2).** You asked to "beat HFTs like iRage / Dolat / Tower." On their turf — sub-microsecond, co-located, FPGA market-making — a Kite-Connect-based system **cannot and will not compete**, and any plan that claims otherwise is selling you something. What *is* achievable, and where this plan aims, is to be world-class on the axes a serious systematic desk actually wins on: **data quality, signal research rigour, risk engineering, execution-cost control, and disciplined ML**. That is the realistic path to "better than the retail platforms, and operating with institutional-grade method."

---

## Table of Contents

1. Executive Summary & Honest Positioning
2. Scope, Instruments & 2026 Contract Realities
3. Competitive Benchmark & Gap Analysis
4. Target Architecture (the upgraded system)
5. Pillar 1 — Data Layer & 15–20 Year Historical Ingestion
6. Pillar 2 — Technical-Analysis Knowledge Base
7. Pillar 3 — Quant/ML Research & Training Stack
8. Pillar 4 — F&O Backtesting Engine
9. Pillar 5 — F&O Strategy / Signal Engine
10. Execution & Risk (institutional-grade hardening)
11. Platform & UX Features (matching best-in-class)
12. Technology Stack & Infrastructure
13. SEBI Compliance & Regulatory Architecture (2026 framework)
14. Phased Implementation Roadmap
15. Success Metrics & KPIs
16. Risks & Honest Limitations
17. Appendices (feature catalog, schemas, vendor comparison, references, glossary)

---

## 1. Executive Summary & Honest Positioning

### 1.1 The vision

Turn `AI_Trading_System` from a strong **research/paper-trading** platform into a **world-class systematic F&O engine** that:

- ingests and curates **15–20 years** of NSE/BSE index-derivatives data with point-in-time correctness;
- represents the **entire technical-analysis + options-analytics vocabulary** as a versioned, reusable feature library;
- trains and validates models on that history with **anti-overfitting discipline** (purged/combinatorial cross-validation, deflated Sharpe, PBO);
- selects and sizes **defined-risk option structures** on NIFTY, FINNIFTY and SENSEX;
- backtests them in an **options-aware, cost-realistic, bias-resistant** engine; and
- executes through Kite Connect (and pluggable brokers) under an **institutional-grade risk and compliance layer** that satisfies SEBI's 2026 retail-algo framework.

### 1.2 Where you can and cannot be "the best"

| Dimension | HFT desks (iRage/Dolat/Tower) | Best retail platforms (Tradetron/Streak/AlgoTest/uTrade/Quantiply) | **Your achievable world-class target** |
|---|---|---|---|
| Latency / co-location | Microseconds, FPGA, exchange co-lo, DMA | Seconds (cloud + broker API) | Seconds; **not** a latency competitor — design *around* it |
| Market making / spread capture | Core business | Not offered | **Not a goal** (you are a liquidity taker) |
| Data depth & curation | Full tick + L2 book | 4–7.5 yrs, mostly EOD/1-min | **15–20 yrs, point-in-time, multi-resolution** ← you win here |
| Signal/ML research rigour | World-class | Light (rule builders) | **Institutional-grade (CPCV, meta-labelling, PBO)** ← you win here |
| Risk engineering | World-class | Basic SL/target, margin calc | **R-based, Greeks-aware, scenario VaR, kill-switches** ← you win here |
| Execution-cost modelling | World-class | Crude | **Order-book-based fills, full STT/GST/impact model** ← you win here |
| Strategy expressiveness | Bespoke | No-code builders | **Code + no-code, defined-risk structures, regime-routed** ← match + exceed |

**Conclusion:** position the platform as a *quant-grade systematic options desk for index derivatives*, not an HFT. Win on rigour, not speed.

### 1.3 What changes vs. your current system

Your README shows a genuinely strong base: modular backend, R-based risk engine, gate pipelines, simulated fills, a logistic meta-labeler, TimescaleDB, FastAPI/asyncio/React. The upgrades that move it to world-class are, in priority order:

1. **A real data foundation** — deep history, point-in-time contract specs, bias elimination. Today this is the biggest gap (Kite alone is shallow for options).
2. **A research/ML stack that cannot fool itself** — your single logistic model + simple walk-forward becomes a full feature store, gradient-boosted + sequence models, and CPCV/PBO validation.
3. **A two-tier backtester** — a fast vectorised research engine plus an event-driven, options-aware validation engine that models expiry, Greeks, margin and assignment.
4. **Closing the live P0s** in `upgrade.md` (mode atomicity, broker-fill accounting, partial fills, durable panic) before any real capital.
5. **SEBI 2026 compliance built into the core** (Algo-ID tagging, broker-registered strategies, OPS limits, static IP/OAuth/2FA).

---

## 2. Scope, Instruments & 2026 Contract Realities

### 2.1 Phase-A instrument set

We deliberately start narrow and deep, exactly as you asked — three index-derivative complexes:

| Index | Exchange | Underlying | Options | Futures | Notes for the engine |
|---|---|---|---|---|---|
| **NIFTY 50** | NSE | Nifty 50 index | Weekly **+** monthly | Monthly (3 serial) | The most liquid; the workhorse for weekly income & event strategies |
| **FINNIFTY** | NSE | Nifty Financial Services | **Monthly only** (weekly discontinued) | Monthly | ⚠️ Weekly income strategies no longer possible — design monthly-cycle strategies |
| **SENSEX** | BSE | BSE Sensex 30 | Weekly **+** monthly | Monthly | BSE liquidity has grown; weekly is the active contract |

### 2.2 Why a *point-in-time contract specification database* is non-negotiable

Indian index-derivative rules have changed **repeatedly** in 2024–2026, and will keep changing. Any of the following, if hard-coded, will silently corrupt a 15–20-year backtest:

- **Weekly expiries were rationalised**: SEBI limited each exchange to a single weekly-expiry index. FINNIFTY, BANKNIFTY and MIDCPNIFTY weeklies were **discontinued**; only NIFTY (NSE) and SENSEX (BSE) keep weeklies.
- **Expiry weekdays shifted multiple times** (Thursday → Monday → Tuesday cycles on NSE; Friday/Thursday on BSE) over 2024–2026. Holiday roll-back rules apply.
- **Lot sizes changed** several times across history (e.g., the Nifty lot was revised upward most recently when SEBI raised the minimum derivatives contract value to ~₹15–20 lakh in late 2024) — so lot size must always be resolved as-of the historical date, never assumed constant.
- **Weekly options didn't always exist** — Nifty weeklies began ~2019, FinNifty ~2021. Pre-history has *only* monthlies.
- **STT/stamp/exchange-fee schedules changed** several times, materially affecting net P&L of high-frequency option strategies.

**Design rule:** every contract attribute (lot size, tick, expiry weekday, weekly-availability, fee schedule, market hours) is stored as **effective-dated reference data** and resolved *as-of the simulated date*. The backtester never asks "what is Nifty's lot size?" — it asks "what was Nifty's lot size on 2017-08-23?". This single discipline separates a credible options backtest from a misleading one.

### 2.3 Out of scope for Phase A (explicitly deferred)

Equities intraday/swing, MCX commodities, naked option selling, US/international markets, and any latency-sensitive market-making. These remain in the codebase (your existing sleeves) but are frozen while the F&O core is rebuilt to world-class standard.

---

## 3. Competitive Benchmark & Gap Analysis

### 3.1 What the retail platforms do well (and what to copy)

| Platform | Best-in-class capability worth absorbing |
|---|---|
| **Tradetron** | ~150-keyword visual condition engine; strategy *marketplace*; 3-mode fill assumption (best/worst/mid) in backtests; multi-broker incl. international |
| **AlgoTest** | ~7.5 yrs options history; **side-by-side multi-strategy backtest comparison**; payoff/heatmap/Greeks visualisers; forward + paper + live continuum; index coverage incl. NIFTY/FINNIFTY/SENSEX |
| **Streak (Zerodha)** | 100+ indicator no-code builder; clean backtest report (P&L, win rate, max DD, profit factor, trade log); deep Kite integration |
| **uTrade Algos** | In-app **option chain leg-building**; portfolio-level payoff curves; integrated margin calculator; pre-built multi-leg templates |
| **Quantiply** | Fully-automated index F&O deployment; **per-strategy live MTM** and instant order updates; multi-broker (Groww, Bigul, etc.) |

**Takeaways to build in:** multi-leg option-chain builder with live payoff/Greeks, multi-strategy comparison, a clean canonical backtest report, paper→forward→live continuum, per-strategy live MTM, and (optionally) an internal strategy library/marketplace.

### 3.2 What the institutional/quant world does that retail platforms *don't*

| Source | Capability to absorb |
|---|---|
| **QuantInsti / Blueshift** | Curated, **bias-free, fully-adjusted** datasets; research→backtest→live continuity; Python-native; ML-strategy support |
| **HFT desks (iRage/Dolat/Tower)** | **Market-microstructure signals** (order-book imbalance, microprice, OFI), rigorous infra/observability, reconciliation discipline, kill-switch culture — adaptable to your latency tier |
| **Academic SOTA** | Triple-barrier labelling & meta-labelling, fractional differentiation, purged/combinatorial CV, deflated Sharpe, PBO, microprice/OFI signals, regime models (HMM) |

### 3.3 Your platform today vs. world-class target

| Capability | Your system today | World-class target | Gap size |
|---|---|---|---|
| Historical data depth | Kite (shallow for options) | 15–20 yrs, point-in-time, multi-resolution | **Large** |
| Contract/expiry handling | Implicit | Effective-dated spec DB | **Large** |
| Feature library | Solid TA + research features | Versioned feature *store* + full options analytics | Medium |
| Labelling | Win/loss meta-label | Triple-barrier + meta-labelling + sample weights | Medium |
| Models | Logistic regression | GBM + sequence + regime ensemble | Medium |
| Validation | Walk-forward | CPCV + embargo + deflated Sharpe + PBO | **Large** |
| Backtester | Single engine, simulated fills | Two-tier; options-aware (Greeks/expiry/margin/assignment) | **Large** |
| Microstructure signals | Order-book imbalance (described) | OFI, microprice, queue dynamics (latency-appropriate) | Medium |
| Execution live path | P0 gaps (per upgrade.md) | Hardened, reconciled, partial-fill safe | **Large** |
| Compliance | Audit log + correlation IDs | Full SEBI-2026 algo framework | **Large** |
| Risk | Strong R-based engine ✅ | + Greeks-aggregated scenario VaR & stress | Small–Medium |

The good news: your **risk philosophy, gate architecture, and audit/correlation-ID discipline are already close to institutional**. The heavy lifting is **data, validation rigour, and the options-aware backtester**.

---

## 4. Target Architecture (the upgraded system)

### 4.1 Layered view

```
                          ┌───────────────────────────────────────────────┐
                          │  OPERATOR / RESEARCHER SURFACES                 │
                          │  React dashboard · Strategy builder · Notebooks │
                          │  Jupyter/Lab · Grafana observability            │
                          └───────────────┬───────────────────────────────┘
                                          │  REST + WebSocket
                          ┌───────────────▼───────────────────────────────┐
                          │  API / CONTROL PLANE (FastAPI)                  │
                          │  auth(OAuth/2FA) · controls · market/analytics  │
                          │  backtest · research · compliance/Algo-ID       │
                          └───────────────┬───────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────────┐
        │                                 │                                       │
┌───────▼────────┐   ┌──────────────────▼─────────────────┐   ┌─────────────────▼───────────────┐
│ LIVE ENGINE     │   │ RESEARCH & ML PLATFORM              │   │ DATA PLATFORM                     │
│ (asyncio)       │   │  feature store · labelling          │   │  ingestion (Kite + vendors)       │
│  feed→features  │   │  training (GBM/seq/regime)          │   │  contract-spec DB (effective-dated)│
│  →model→struct  │   │  CPCV/PBO validation                │   │  TimescaleDB (hot/warm)           │
│  →risk→exec     │   │  model registry (MLflow)            │   │  Parquet/ClickHouse lake (cold)   │
│                 │   │  backtester (2-tier)                │   │  quality & adjustment jobs        │
└───────┬─────────┘   └──────────────────┬─────────────────┘   └─────────────────┬───────────────┘
        │                                 │                                       │
        └───────────────┬─────────────────┴───────────────────┬───────────────────┘
                        │                                       │
              ┌─────────▼─────────┐                  ┌──────────▼──────────┐
              │ STATE / MESSAGING │                  │ PERSISTENCE          │
              │ Redis (state,     │                  │ TimescaleDB · Parquet│
              │ streams, commands)│                  │ object store · MLflow│
              └─────────┬─────────┘                  └──────────────────────┘
                        │
              ┌─────────▼─────────┐
              │ BROKER ADAPTERS    │  Kite (primary) · pluggable (Dhan/Fyers/...)
              │ + RECONCILIATION   │  Algo-ID tagging · OPS limiter · static-IP/OAuth
              └────────────────────┘
```

### 4.2 Key architectural decisions

1. **Separate the live engine from the research platform**, but make them share one **feature library** and one **contract-spec service** so a feature computed in research is *bit-identical* to the one computed live. This "train/serve parity" is the single most common failure point in ML trading; we design it out from day one.

2. **Two-tier backtester.** A fast **vectorised** engine (pandas/Polars/NumPy) for research sweeps over 15–20 years, and a slower **event-driven** engine that is the *authority* for any strategy promoted toward live — it replays the order of events, models latency, partial fills, margin and expiry. A strategy must pass *both* and they must agree within tolerance.

3. **Everything is point-in-time.** The feature store, the contract-spec DB, and the data lake all answer "as-of date T" queries. No look-ahead, ever.

4. **Redis Streams (or Kafka) as the event spine** between feed, engine, and execution, so the live path is replayable and auditable, and the same event log can be fed to the event-driven backtester ("replay live = backtest" symmetry).

5. **Compliance is a first-class service**, not an afterthought: Algo-ID tagging, OPS rate-limiting, and broker-strategy registration sit in the control plane and wrap every order.

6. **Keep your existing module boundaries** (`api/ engine/ data/ strategies/ risk/ execution/ backtest/ research/ broker/ common/ config/`). We *add* `dataplatform/`, `features/`, `ml/`, and `compliance/`, and substantially deepen `backtest/`, `research/`, and `data/`.

### 4.3 New/expanded top-level modules

| Module | New? | Responsibility |
|---|---|---|
| `dataplatform/` | **New** | Vendor adapters, ingestion DAGs, contract-spec DB, adjustment & quality jobs, the cold lake |
| `features/` | **New** | The versioned TA + options feature library (single source of truth for live & research) |
| `ml/` | **New** | Labelling, model training, CPCV/PBO validation, model registry, drift monitoring |
| `compliance/` | **New** | Algo-ID, OPS limiter, broker-strategy registry, regulatory audit exports |
| `backtest/` | Expand | Add event-driven options engine, margin/SPAN model, scenario/MC, bias guards |
| `research/` | Expand | Feature store interface, experiment tracking, edge reports → CPCV-based |
| `data/` | Expand | Real-time feature computation parity with `features/`; IV surface, GEX, OFI |
| `risk/` | Expand | Greeks aggregation, scenario VaR, stress; keep R-engine & kill-switches ✅ |
| `execution/` | Expand | Partial-fill reconciliation, smart slicing, broker reconciliation loop |

---

## 5. Pillar 1 — Data Layer & 15–20 Year Historical Ingestion

> This is the foundation. Models, backtests and signals are only as good as the data beneath them. Budget the **most** time here.

### 5.1 What F&O data you actually need (and at what resolution)

| Data class | Resolution | History target | Used for |
|---|---|---|---|
| **Index spot** (Nifty/FinNifty/Sensex) | 1-min + EOD; tick if available | 20 yrs (EOD), 8–10 yrs (1-min) | Regime, trend/vol features, underlying path |
| **Index futures** (near/next/far) | 1-min + EOD | 15–18 yrs | Basis, roll, cost-of-carry, continuous contract |
| **Option chains** (all strikes, both expiries) | 1-min snapshots; EOD greeks/OI | 6–10 yrs realistically | The core: IV surface, skew, OI, structure backtests |
| **Per-option OHLCV** | 1-min | 6–10 yrs | Multi-leg structure fills & P&L |
| **Open interest** (per option + aggregate) | per snapshot + EOD | 6–10 yrs | OI buildup, PCR, GEX, max-pain |
| **Order book L1/L5** (where available) | event/snapshot | 1–3 yrs (storage-heavy) | Microstructure (OFI, microprice) — recent only |
| **India VIX** | 1-min + EOD | 12+ yrs | Vol regime scaling |
| **Corporate actions / index reconstitutions** | event | full | Adjustments, survivorship-free index |
| **Expiry calendar & holidays** | event | full | Expiry handling, roll, settlement |
| **Contract specs** (lot, tick, fees) | effective-dated | full | Point-in-time sizing & cost |

**Reality check on option-chain history:** clean, deep, *intraday* option-chain history in India is the scarcest and most expensive data. EOD option data goes back further and cheaper; 1-min option data is typically available ~2017–2018 onward from vendors; full L2 book is recent and huge. So the 15–20-year ambition is **tiered**: 20 years of spot/EOD, ~8–10 years of 1-min underlying/futures, ~6–10 years of usable intraday option chains. Plan strategies accordingly — older history trains *regime/underlying* models; the options-specific edge is validated on the last ~6–10 years.

### 5.2 Kite Connect — what it gives you, and its limits

Kite Connect (your primary broker API) is excellent for **live** trading and recent history, but is **not** a research-grade historical source:

- **Historical API** returns candles (minute to day) but with **limited look-back windows** per request and **rate limits**; minute data depth is capped and instrument-token churn (weekly options expire and tokens are reused) makes deep historical option reconstruction painful.
- **No deep options chain history** — you cannot pull years of full chains efficiently.
- **Live**: WebSocket streaming quotes/depth (good), order placement, positions, margins, GTT. This is your **live feed and execution path** — keep it.
- **SEBI-2026 constraints** now apply to API usage (static IP, OAuth, 2FA, OPS limits, Algo-ID) — see §13.

**Verdict:** use Kite for **live data + execution + recent backfill**, and a **dedicated historical vendor** for the 6–20-year research corpus.

### 5.3 Recommended historical data vendors (India F&O)

Build a **pluggable adapter interface** (`dataplatform/vendors/`) so you are never locked in. Recommended sources, roughly best-fit first:

| Vendor | Strengths | Best for | Notes |
|---|---|---|---|
| **TrueData** | Long F&O history, tick/1-min, options chains, Python API | Primary research corpus (1-min options + futures) | Paid; popular with Indian quant retail |
| **Global Datafeeds (GDFL/AlgoTrader feed)** | Authorised NSE/BSE/MCX vendor, tick & snapshot | Tick-level + authorised real-time | Paid; exchange-authorised |
| **GFDL / iCharts / Investing-grade EOD** | Deep EOD index/futures | 15–20 yr EOD underlying/futures | Cheaper, EOD focus |
| **NSE/BSE official historical** (incl. NSE data shop, Bhavcopy archives) | Authoritative EOD F&O bhavcopy (free archives) | Survivorship-free EOD options/OI history | Free bhavcopy back many years; build a parser |
| **Samco/Dhan/Fyers/ICICI Breeze APIs** | Alt-broker historical & live | Cross-validation, redundancy | Varies by broker |
| **Sensibull/Opstra-style derived** | IV/Greeks/OI analytics | Sanity-checking your own IV/Greeks | Derived, not raw |
| **AlgoTest/iVolatility-style options datasets** | Pre-cleaned options datasets | Jump-start options research | Paid; verify licensing |

**Concrete recommendation:**
1. **Free first:** ingest **NSE/BSE F&O bhavcopy archives** (EOD per-contract OHLC, settlement, OI) going back as far as published — this gives a *survivorship-free EOD options/futures spine* for ~15+ years at zero data cost.
2. **Paid core:** subscribe to **TrueData** (or Global Datafeeds) for **1-min options + futures** (~2017→present) — the intraday research corpus.
3. **Live:** **Kite Connect** WebSocket for real-time + execution; use a second broker (e.g., **Dhan/Fyers**) as a redundant live feed.
4. **Derived check:** periodically reconcile your computed IV/Greeks/GEX against a derived provider to catch bugs.

> ⚠️ **Licensing:** exchange data is licensed. Redistribution and certain commercial uses require exchange approval. Keep raw vendor data private; never expose it via a public API. This plan assumes personal/registered use.

### 5.4 Storage architecture (hot / warm / cold)

```
            Kite WS (live)        Vendor batch (TrueData/GDFL/bhavcopy)
                  │                          │
                  ▼                          ▼
        ┌───────────────────┐      ┌───────────────────────┐
        │ Redis Streams      │      │ Ingestion DAGs         │
        │ (live ticks/events)│      │ (Prefect/Airflow)      │
        └─────────┬──────────┘      └───────────┬────────────┘
                  │                              │
                  ▼                              ▼
        ┌───────────────────────────────────────────────────┐
        │  TimescaleDB  (HOT/WARM — operational truth)        │
        │  hypertables: ticks, candles_1m, option_snapshots,  │
        │  oi, futures, vix, signals, orders, fills, positions│
        └───────────────────────┬───────────────────────────┘
                                 │  nightly ETL (compress + export)
                                 ▼
        ┌───────────────────────────────────────────────────┐
        │  COLD LAKE  (research — Parquet on object store,    │
        │  queried via DuckDB/Polars; or ClickHouse if scale) │
        │  partitioned by symbol/expiry/date; columnar        │
        └───────────────────────────────────────────────────┘
```

- **TimescaleDB** (you already use it) stays the operational store: hypertables, native compression, continuous aggregates for multi-timeframe candles. Great for the last ~2–3 years hot + live.
- **Cold research lake**: export older/bulk history to **Parquet** (partitioned `symbol/year/month`, columnar, compressed) on local disk or object storage, and query with **DuckDB or Polars** — this is what makes scanning 15–20 years for feature computation fast and cheap. If volumes explode (full L2 book), graduate the lake to **ClickHouse**.
- **Why both:** Timescale is excellent for time-range operational queries and live writes; Parquet+DuckDB is dramatically faster and cheaper for wide analytical scans across the full history during research. Use each where it wins.

### 5.5 The contract-specification & expiry service (the unsung hero)

A dedicated, effective-dated reference store (`dataplatform/contracts/`):

```sql
-- effective-dated contract specs: query "as of" any historical date
CREATE TABLE contract_spec (
    underlying      TEXT,         -- 'NIFTY','FINNIFTY','SENSEX'
    exchange        TEXT,         -- 'NSE','BSE'
    attribute       TEXT,         -- 'lot_size','tick_size','weekly_available','expiry_weekday'
    value           TEXT,
    valid_from      DATE,
    valid_to        DATE,         -- NULL = current
    source          TEXT,
    PRIMARY KEY (underlying, attribute, valid_from)
);

CREATE TABLE expiry_calendar (
    underlying      TEXT,
    expiry_date     DATE,
    expiry_type     TEXT,         -- 'weekly','monthly'
    is_settlement   BOOLEAN,
    trading_days    INT,          -- days to expiry context
    PRIMARY KEY (underlying, expiry_date)
);

CREATE TABLE market_holidays (
    exchange TEXT, holiday_date DATE, segment TEXT,
    PRIMARY KEY (exchange, holiday_date, segment)
);
```

Resolver API: `spec.as_of(underlying, attribute, date)` and `expiry.resolve(underlying, ref_date, which='current_weekly')`. **Every** sizing, cost, and expiry decision in research, backtest and live goes through this resolver, so a rule change (like the FinNifty weekly discontinuation) is a *data update*, not a code change.

### 5.6 Data quality, adjustments & bias elimination

Bias-free data is what separates Blueshift-grade research from retail. Build these jobs:

- **Survivorship-free universe**: use bhavcopy-derived index reconstitution history so backtests "see" the index as it was, not as it is.
- **Continuous futures series**: stitch near-month futures with documented roll (e.g., roll on expiry-N days; back-adjust or ratio-adjust) — store *both* raw and adjusted.
- **Corporate-action adjustments** for any single-stock extensions later; for indices, handle dividend/index-methodology changes.
- **Point-in-time IV/Greeks**: compute IV from *that day's* risk-free rate and *that day's* option prices; never re-derive with today's params.
- **Gap/outlier detection**: flag missing candles, zero-volume prints, crossed quotes, stale OI; quarantine rather than silently drop.
- **Reconciliation**: cross-check vendor vs. bhavcopy settlement prices and OI; alert on divergence beyond tolerance.
- **Immutable raw + versioned curated**: keep raw vendor files immutable; all cleaning produces a *new version* of the curated dataset with a manifest (so a backtest can pin a dataset version for reproducibility).

### 5.7 Ingestion pipeline (orchestration)

Use **Prefect** (lighter) or **Airflow** for scheduled DAGs:

1. **Daily EOD DAG** — pull bhavcopy (NSE/BSE), vendor EOD, settlement & OI; update `contract_spec`/`expiry_calendar`; run quality checks; export to lake.
2. **Intraday DAG** — vendor 1-min option/futures backfill; reconcile against live-captured Redis stream.
3. **Live capture** — the engine's feed handler persists ticks/snapshots to Timescale + Redis Streams (this *is* tomorrow's history; capturing it well now compounds).
4. **Adjustment DAG** — rebuild continuous contracts and curated dataset versions weekly.
5. **Quality DAG** — nightly anomaly report → Grafana/alerts.

**Deliverable for this pillar:** a `dataplatform/` package with vendor adapters, the contract/expiry resolver, the Timescale schema + Parquet exporter, quality jobs, and a reproducible "dataset manifest" mechanism.

---

## 6. Pillar 2 — Technical-Analysis Knowledge Base ("teach the engine all TA")

You asked to "teach the engine all concepts of technical analysis." The right way to do this is **not** to hand-code 200 rules, but to build a **versioned feature library** — every TA and options concept expressed as a deterministic, point-in-time function — and then let the ML layer (Pillar 3) learn which features matter, in which regime. Rules still exist (as hard safety gates), but *edge discovery is data-driven*.

Your README already implements a strong indicator set (SMA/EMA/ATR/ADX/RSI/RVOL/VWAP/MACD/Bollinger/Donchian/SuperTrend/Anchored-VWAP, plus Black-Scholes, GEX, volume profile, order-book imbalance). The plan is to (a) formalise these into the shared `features/` library with strict train/serve parity, and (b) **expand** to a complete catalog.

### 6.1 Design principles for the feature library

1. **Pure functions, point-in-time.** Each feature is `f(history_up_to_T) -> value_at_T`. No future leakage. Unit-tested against known fixtures.
2. **Train/serve parity.** The *same* function computes the feature in research (over Parquet) and live (over the streaming buffer). One implementation, two callers.
3. **Versioned & cataloged.** Each feature has an ID, version, inputs, lookback, and category. Changing a formula bumps the version; backtests pin versions.
4. **Multi-timeframe by construction.** Features are parameterised by timeframe (1m/5m/15m/1h/1d) and composed across timeframes.
5. **Stationarity-aware.** Provide fractionally-differentiated variants of price-derived features (so models see memory-preserving, more-stationary inputs — López de Prado).
6. **Cheap to add.** Adding a feature = one function + one catalog entry + one test.

### 6.2 The feature catalog (taxonomy)

**A. Trend / moving averages**
SMA, EMA, WMA, HMA, DEMA/TEMA, KAMA, VWMA, 200-DMA distance, MA slopes & crossovers, linear-regression slope/R², Supertrend, Parabolic SAR, Ichimoku (Tenkan/Kijun/Senkou/Chikou, cloud thickness), Donchian mid, price-vs-VWAP, anchored VWAP from swing/expiry/event.

**B. Momentum / oscillators**
RSI (+ divergences), Stochastic (%K/%D), Stochastic RSI, MACD (line/signal/hist + slope), ROC/Momentum, CCI, Williams %R, TSI, Awesome Oscillator, Coppock, Connors RSI, RSI-of-RSI, rate-of-change of OI.

**C. Volatility**
ATR & ATR%, Bollinger Bands (width, %B, squeeze), Keltner Channels, Donchian width, historical/realised vol (close-to-close, Parkinson, Garman-Klass, Yang-Zhang), Chaikin Volatility, normalized range, gap size, India-VIX level/percentile/term, IV-vs-RV spread.

**D. Volume / participation**
RVOL, OBV, Accumulation/Distribution, Chaikin Money Flow, MFI, VWAP & session-VWAP bands, volume delta (up/down vol), VPIN-style toxicity proxy, volume z-score, first-hour vs day volume ratio.

**E. Market & volume profile (auction theory)**
POC, Value Area High/Low, VA width, single prints, Initial Balance (IB high/low/range), IB extension, naked POC, developing VA migration, TPO counts, balance vs imbalance day classification.

**F. Market microstructure / order flow** *(recent history only; latency-appropriate live)*
Order-book imbalance (L1..L5), **Order Flow Imbalance (OFI)**, **microprice** = `(bid·ask_sz + ask·bid_sz)/(bid_sz+ask_sz)`, spread/effective-spread, depth slope, quote intensity, trade-sign imbalance (Lee-Ready), Kyle's lambda (price impact), roll measure, queue-position proxy. (See §9.3 for the realistic latency framing.)

**G. Regime / state**
ADX-based trend/chop, DI alignment, Hurst exponent, variance-ratio test, autocorrelation, realised-vol regime buckets, **HMM/GMM regime label** (trend-up/trend-down/mean-revert/high-vol), VIX regime, breadth/sector-rotation context, time-of-day & day-of-week, days-to-expiry buckets, event-proximity flags (RBI/Fed/budget/expiry).

**H. Statistical / cross-asset**
Rolling correlation/beta to index, Nifty-vs-FinNifty spread & z-score, futures **basis** & annualised carry, calendar spread, lead-lag (futures→spot), cointegration residual z-score, relative strength vs index.

**I. Options analytics (the F&O core)** — see §6.3.

### 6.3 Options-analytics feature group (the part retail platforms underuse)

This is where an index-options engine earns its keep. Built on your existing Black-Scholes module, extended:

- **Per-option Greeks** (Δ, Γ, Θ, Vega, Vanna, Charm, Vomma) — point-in-time, from that day's rate & IV.
- **Implied-volatility surface**: IV by strike × expiry; fit a smooth surface (SVI or cubic spline); store ATM IV, 25Δ risk-reversal, 25Δ butterfly.
- **Skew & term structure**: put-call skew, skew slope, term-structure slope (front vs next), IV-rank & IV-percentile (you have these), **VRP** (IV − subsequent RV).
- **Open-interest analytics**: OI by strike, OI change, **PCR** (OI & volume), OI buildup matrix (long/short buildup, covering/unwinding — you have this), max-pain strike, OI-weighted support/resistance.
- **Dealer-gamma / GEX** (you have a base version): per-strike GEX, **net GEX**, **call wall / put wall**, **zero-gamma flip strike**, gamma regime (positive→mean-revert, negative→trend) — a genuinely differentiating signal for index options.
- **Vanna/Charm exposure** (dealer hedging flows into expiry) — explains expiry-day drift.
- **Greeks-aggregated portfolio exposures**: net Δ/Γ/Θ/Vega of the live book (feeds risk, §10).

### 6.4 From rules to learned features (how the engine "learns" TA)

1. Compute the full feature vector point-in-time for every decision timestamp over 15–20 years.
2. Store it in the **feature store** (Pillar 3) keyed by `(symbol, timestamp, feature_version)`.
3. Label outcomes (triple-barrier, §7.2).
4. Train models to map features→outcome, and **inspect feature importance / SHAP** to *discover* which TA concepts actually carry edge in each regime — turning "all of TA" from folklore into measured signal.
5. Keep a small set of **hard rules as safety gates** (liquidity, spread, stop-distance, defined-risk only) that can *veto* but never *manufacture* a trade.

**Deliverable:** a `features/` package: catalog (YAML), pure-function implementations, multi-timeframe composer, fractional-diff utilities, and a parity test harness (research value == live value on the same bar).

---

## 7. Pillar 3 — Quant/ML Research & Training Stack

> Goal: train the engine on 15–20 years **without fooling yourself**. The hardest part of quant trading is not building a model that fits the past — it's proving the edge is real. This stack is engineered around that.

### 7.1 Feature store

A point-in-time feature store (`ml/feature_store/`) so research and live share identical, reproducible features:

- **Offline store**: Parquet/DuckDB tables keyed `(symbol, timestamp, feature_version)` for the full history — used to assemble training sets fast.
- **Online store**: Redis hash per symbol holding the latest feature vector — read by the live engine with the *same* computation path.
- **Point-in-time joins**: assemble `(features as-of T)` ↔ `(label realised after T)` with strict temporal correctness.
- Use **Feast** if you want an off-the-shelf store, or a thin custom layer over DuckDB+Redis (lighter, fewer deps). Recommendation: **custom-thin first**, Feast later if needed.

### 7.2 Labelling — the part most retail systems get wrong

Replace ad-hoc win/loss labels with **triple-barrier + meta-labelling** (López de Prado, *Advances in Financial ML*):

1. **Triple-barrier method.** For each candidate entry, set an upper barrier (profit target, e.g. `+kσ` or `+R`), a lower barrier (stop, `−R`), and a vertical barrier (max holding / expiry). The label is which barrier is hit first → {+1, −1, 0}. This produces *path-aware, risk-aware* labels that match how the strategy actually exits.
2. **Sample weighting by uniqueness.** Overlapping labels (concurrent positions) violate IID; weight samples by label uniqueness and apply time-decay so recent regimes count more.
3. **Meta-labelling.** A *primary* model/rule decides direction & whether to act; a *secondary* (meta) model predicts the probability the primary signal is correct, and is used **only to size or veto** — never to flip direction. This is exactly the role your current logistic meta-labeler plays; we keep the philosophy and upgrade the machinery. (Meta-label can shrink/veto, never inflate — consistent with your README.)
4. **Fractional differentiation** of price features to retain memory while gaining stationarity.

### 7.3 Models — a layered ensemble, not one black box

| Layer | Model | Role |
|---|---|---|
| Baseline | **Logistic regression** (you have this) | Interpretable benchmark; never delete it — it's your sanity floor |
| Workhorse | **Gradient boosting (LightGBM/XGBoost)** | Tabular feature→outcome; handles nonlinearity & interactions; SHAP for interpretability |
| Sequence | **Temporal CNN / LSTM / small Transformer** | Path/sequence patterns in intraday series; use cautiously, regularise hard |
| Regime | **HMM / GMM** | Unsupervised market-state labels feeding all other models as context |
| Vol model | **GARCH / HAR-RV** | Forecast realised vol → compare to IV → VRP signal for options |
| Ensemble | **Stacking / regime-gated blend** | Combine the above; weights conditioned on regime |

**Principles:** start simple, add complexity only when it beats the simpler model *out-of-sample on CPCV*. Every model ships with feature-importance/SHAP and a plain-English "why." Prefer **interpretable + robust** over exotic-but-fragile. For options specifically, much of the edge is in **VRP, skew dynamics, GEX regime, and event/expiry effects** — frequently better captured by GBM on good features than by deep nets.

### 7.4 Validation — the anti-overfitting core (this is where you out-class retail)

Retail platforms offer a single in-sample backtest. World-class means:

- **Walk-forward** (you have this) — necessary but not sufficient.
- **Purged K-Fold + embargo** — remove training samples whose labels overlap the test window, and embargo a buffer after each test fold, to kill leakage from overlapping/serially-correlated labels.
- **Combinatorial Purged Cross-Validation (CPCV)** — train/test over many combinatorial splits to get a *distribution* of out-of-sample performance, not a single lucky path.
- **Deflated Sharpe Ratio (DSR)** — adjust the observed Sharpe for the number of trials you ran (multiple-testing); a Sharpe that survives DSR is meaningfully more trustworthy.
- **Probability of Backtest Overfitting (PBO)** — via combinatorially-symmetric cross-validation, estimate the chance your "best" config is actually overfit.
- **Minimum Backtest Length** awareness — don't trust a 6-month options backtest; require enough independent expiry cycles.
- **Reality checks** — White's Reality Check / Hansen's SPA when screening many strategies.

A strategy is **not** promoted to paper-live unless it clears CPCV (positive across most combinatorial folds), DSR > threshold, and acceptable PBO. This gate is the single biggest reason most retail "profitable backtests" fail live — and designing it in is how you genuinely beat them.

### 7.5 Training on 15–20 years — pipeline & ops

- **Experiment tracking**: **MLflow** logs every run (params, dataset version, features, CPCV scores, DSR/PBO, artifacts). Reproducible by construction.
- **Model registry**: promote models through `dev → shadow → paper → live` stages; live engine loads only `live`-stage models by signed reference.
- **Dataset pinning**: every training run pins a curated dataset version + feature versions (from Pillars 1–2) so results are reproducible years later.
- **Compute**: GBM/HMM train comfortably on CPU; sequence models benefit from a GPU but are optional. The full-history feature build is the heavy job — parallelise over Parquet partitions with Polars/Dask.
- **Retraining cadence**: scheduled walk-forward retrain (e.g., monthly) + event-triggered retrain on drift.
- **Drift monitoring**: track feature-distribution drift (PSI/KL) and live-vs-backtest performance; alert and optionally auto-demote a model to shadow if drift breaches thresholds.

### 7.6 Reinforcement learning — a deliberate "later, maybe"

RL is fashionable but data-hungry and easy to overfit on financial series. **Defer it.** If pursued, restrict to a *narrow* problem with a faithful simulator — e.g., **execution scheduling** (how to slice a multi-leg order) — where the environment is well-specified, rather than end-to-end "learn to trade." Gate any RL behind the same CPCV/DSR scrutiny.

**Deliverable:** an `ml/` package: feature-store interface, triple-barrier/meta-label/sample-weight utilities, model trainers (logistic/LightGBM/HMM/sequence), a CPCV+DSR+PBO validation harness, MLflow integration, and a model registry the live engine reads from.

---

## 8. Pillar 4 — F&O Backtesting Engine (world-class)

> The backtester is the **arbiter of truth**. If it lies (look-ahead, unrealistic fills, ignored costs), every downstream decision is poisoned. Options make this 10× harder than equities because of expiry, Greeks, margin and multi-leg fills.

### 8.1 Two-tier design

| Tier | Engine | Speed | Fidelity | Use |
|---|---|---|---|---|
| **Research** | Vectorised (Polars/NumPy) | Very fast | Approximate fills | Sweep parameters across 15–20 yrs, screen ideas, feed CPCV |
| **Validation** | Event-driven | Slower | High (latency, partial fills, margin, expiry, assignment) | Authority for promotion to paper-live |

A strategy must pass both; their headline metrics must agree within tolerance, or the discrepancy is investigated (usually it reveals an unrealistic fill assumption in the vectorised pass).

### 8.2 Options-aware mechanics (what most backtesters skip)

- **Expiry & settlement**: cash-settled index options/futures; settle at the official closing/settlement value; handle the vertical barrier at expiry; auto-square or settle ITM legs. Drive all expiry dates from the **expiry-calendar service** (§5.5), not hard-coding.
- **Multi-leg structures as atomic units**: a bull-call-spread / iron-condor is one position with combined max-loss/max-profit (you already model this); the backtester tracks legs but P&L/risk at the structure level.
- **Greeks-based P&L attribution**: decompose P&L into Δ (direction), Γ, Θ (decay), Vega (IV change), and residual — so you *understand why* a strategy made/lost money, not just the number.
- **Roll logic**: model rolling positions across expiries with realistic roll costs (FinNifty is monthly-only — roll discipline matters more there).
- **Assignment/exercise**: for index options it's cash settlement, simplifying vs. single stocks; still model early-expiry pin risk and settlement slippage.
- **Margin & SPAN**: model **SPAN + exposure** margin per position and at portfolio level (defined-risk spreads get margin benefit); enforce margin availability as a real constraint on sizing — your README already clamps by `live_margin_units`; the backtester must replicate the *same* margin math so backtest and live agree.

### 8.3 Realistic fills & transaction costs

Extend your existing simulated-fill + cost model:

- **Order-book-based fills** where book history exists (cross the book VWAP + slippage + beyond-book impact — you already do this for live sim; bring it into backtest where L2 is available).
- **Conservative fills where only OHLC exists**: offer Tradetron-style **best/mid/worst** assumptions and default to *worst-realistic* for promotion decisions; never assume mid on illiquid far strikes.
- **Liquidity filter**: reject backtest fills on strikes whose historical volume/OI was below threshold — a backtest that "trades" illiquid options is fiction.
- **Full cost model** (you have the components): brokerage, STT/CTT (segment & side aware), exchange txn, SEBI, stamp, GST, plus **bid-ask half-spread** and **market impact**. For high-churn weekly-option strategies, costs frequently *are* the strategy's P&L — model them ruthlessly.

### 8.4 Bias avoidance (the credibility checklist the engine enforces)

- **Look-ahead**: features computed strictly from `≤ T`; the contract resolver answers as-of T; settlement values not visible before close.
- **Survivorship**: index composition as-of date; expired contracts present in history.
- **Snooping / overfitting**: validation via CPCV/DSR/PBO (Pillar 3), not a single curve.
- **Liquidity & capacity**: position size capped by historical volume/OI; flag strategies that only work at tiny size.
- **Cost realism**: worst-realistic fills + full statutory costs by default.
- **Point-in-time params**: lot size, fees, expiry rules resolved historically.

Each backtest report carries a **"bias audit" header** stating which guards were active — a strategy with guards disabled is marked "exploratory, not promotable."

### 8.5 Scenario, stress & Monte Carlo

- **Scenario VaR / stress**: shock spot (±%), IV (±vol points), and time (Θ) jointly; evaluate the option book under a grid (e.g., spot −7%..+7% × IV −5..+10) — essential for options where Greeks make linear VaR misleading.
- **Historical stress replays**: 2008, COVID-2020 crash, 2024 election-result day, expiry-day gamma squeezes — replay the book through these.
- **Monte Carlo on the trade sequence**: bootstrap/reshuffle trade order to get a *distribution* of drawdowns and terminal equity, not a single equity curve — exposes path/drawdown risk that a single backtest hides.
- **Capacity analysis**: at what AUM does slippage erode the edge?

### 8.6 Canonical report (extend yours)

Keep your metrics (win rate, profit factor, expectancy-R, max DD, Sharpe-like, walk-forward verdict) and add: **CPCV score distribution, deflated Sharpe, PBO, Sortino/Calmar, tail ratio, Greeks-attributed P&L, cost drag %, capacity estimate, and the bias-audit header.** Support **multi-strategy side-by-side comparison** (AlgoTest-style) and portfolio-level aggregation.

**Deliverable:** an expanded `backtest/` package: vectorised engine, event-driven options engine, SPAN-style margin model, scenario/MC modules, bias-guard enforcement, and the upgraded canonical report.

---

## 9. Pillar 5 — F&O Strategy / Signal Engine

This is where everything converges into live decisions. Keep your **deterministic gate pipeline** (it's a strength), but elevate it into a clean, layered decision flow.

### 9.1 The decision pipeline

```
 market context (features, regime, IV surface, GEX, OI)
        │
        ▼
 [1] SIGNAL GENERATION  ── primary models/rules produce a directional/vol view
        │                  (e.g., "bullish, low-IV" or "range-bound, high-IV")
        ▼
 [2] HARD GATES         ── liquidity, spread, time-window, DTE, event, stop-sanity
        │                  (can only REJECT; defined-risk only; no naked selling)
        ▼
 [3] META-LABEL FILTER  ── secondary model P(signal correct) → veto or shrink size
        │
        ▼
 [4] STRUCTURE SELECTION ── map view+IV-regime → defined-risk option structure
        │                   (debit/credit spread, condor, calendar, ratio-defined)
        ▼
 [5] POSITION SIZING     ── R-based, confidence-scaled, capped by margin/portfolio
        │                   (your existing R-engine — reused as-is ✅)
        ▼
 [6] PRE-TRADE RISK      ── Greeks limits, scenario check, kill-switch/brake state
        │
        ▼
 [7] EXECUTION           ── multi-leg routing, slicing, partial-fill handling
```

Every accepted signal still carries your rich payload (sleeve, instrument, side, setup, entry/stop/target, gate trail, confidence, correlation ID) — extended with regime label, IV-regime, model version, and feature snapshot for full traceability.

### 9.2 Strategy families for NIFTY / FINNIFTY / SENSEX

All **defined-risk** (consistent with your no-naked-selling rule). IV-regime routing (you have the skeleton) decides the family:

| Market view × IV regime | Structure | Indices best suited |
|---|---|---|
| Bullish, **low** IV | Bull call **debit** spread | NIFTY/SENSEX weekly; FINNIFTY monthly |
| Bearish, **low** IV | Bear put **debit** spread | All three |
| Bullish, **high** IV | Bull put **credit** spread | NIFTY/SENSEX weekly |
| Bearish, **high** IV | Bear call **credit** spread | NIFTY/SENSEX weekly |
| Neutral, **high** IV | Iron condor / iron fly | NIFTY/SENSEX weekly income |
| Neutral, **low** IV | Calendar / diagonal (defined) | NIFTY monthly; FINNIFTY monthly |
| Event-vol play | Defined-risk strangle/condor around RBI/budget/expiry | NIFTY/SENSEX |
| Expiry-day gamma | Tight defined-risk expiry structures driven by GEX flip/walls | NIFTY/SENSEX weekly |

**FinNifty note:** with weeklies gone, FinNifty strategies center on the **monthly cycle** — theta capture is slower, roll discipline and event-positioning (financials-sector events, RBI policy) matter more. Don't port weekly-income logic onto it.

Strategy logic remains **regime-routed and data-validated**: each family is a hypothesis tested through Pillars 3–4 before it can deploy, with the meta-label model gating live size.

### 9.3 Microstructure / order-flow signals — the *honest* HFT-inspired layer

You can borrow HFT *concepts* (OFI, microprice, book imbalance, trade-sign imbalance) **without** pretending to HFT *speeds*. The realistic framing:

- At Kite-API latency (tens of ms to seconds), you **cannot** scalp the spread or race quotes. Don't try.
- You **can** use microstructure as **short-horizon context/confirmation** for entries/exits you'd hold seconds-to-minutes: e.g., enter a defined-risk structure only when OFI and book imbalance *agree* with the model's direction; delay/skip when the microprice diverges or the book is thin/toxic.
- Use it heavily in **execution** (§10): time the slices, avoid crossing into thin books, detect adverse flow before completing a multi-leg order.
- Capture L1/L5 now (Pillar 1) so this layer has data; treat it as **edge-enhancing, not edge-creating** at your latency tier.

### 9.4 IV-surface / skew / GEX routing (your differentiator)

Beyond direction, route and time trades using the options-analytics features:

- **VRP** (IV − forecast RV from the GARCH/HAR model): persistently positive VRP favors premium-selling structures (credit spreads/condors) sized for defined risk.
- **Skew & risk-reversal**: rich downside skew → prefer put-spread financing / specific condor wings.
- **Term structure**: front-vs-next slope → calendars when favorable.
- **GEX regime**: positive net-GEX (mean-reverting) favors range/condor; negative net-GEX (trend-amplifying) favors directional debit spreads and tighter risk; trade *toward* call/put walls, respect the **zero-gamma flip** as a regime boundary — especially on expiry day.

**Deliverable:** an expanded `strategies/` + `engine/` flow implementing the 7-step pipeline, the structure-selection library for the three indices, the microstructure-confirmation module, and IV/GEX routing — all reusing your R-based sizing and kill-switch infrastructure.

---

## 10. Execution & Risk (institutional-grade hardening)

Your `upgrade.md` already names the right P0s. This section frames them as the execution/risk target and adds the options-portfolio risk layer. **No real capital until §10.1 is complete.**

### 10.1 Live-path P0s (from your audit — must close first)

1. **Atomic runtime mode state** across API, executor, risk, capital, and kill-switch — a single source of truth for `simulated_fill | paper | live`, changed transactionally, with no window where components disagree.
2. **Executable pre-live readiness check** — a real, automated checklist (broker connectivity, token validity, margin, clock sync, feed liveness, reconciliation clean) that *blocks* going live if anything fails.
3. **Mode/account-scoped positions, capital & P&L** — never mix paper and live state.
4. **Product-aware live exits** + **broker-fill-based close accounting** — P&L from actual fills, not model prices.
5. **Partial-fill lifecycle** — cancel/replace/reconcile for multi-leg structures; never leave a structure half-on (a half-filled iron condor is undefined risk — exactly what you must prevent).
6. **Durable, acknowledged panic/flatten** — commands persisted, retried, idempotent, confirmed.
7. **Broker reconciliation loop** — continuously reconcile internal state vs. broker positions/orders/margins; alert and halt on divergence.
8. **Venue/session watchdog** — guard against acting on stale feeds or out-of-session quotes.

### 10.2 Smart execution for multi-leg options

- **Leg sequencing** to minimise legging risk (enter the harder-to-fill/long leg first, or use exchange spread orders where supported).
- **Slicing**: TWAP/POV slicing for larger orders; microstructure-aware timing (§9.3).
- **Bracket/OCO** for stops/targets at the structure level.
- **Slippage budget** per structure; abort if fills breach it.
- **Idempotent order management** keyed by correlation ID (you already use correlation IDs — extend to execution idempotency).

### 10.3 Options-portfolio risk layer (new, on top of your strong R-engine)

Keep everything you have (R-sizing, sleeve/portfolio caps, daily kill-switch, drawdown/profit-lock/expectancy/period/streak brakes, VIX scaling — all excellent ✅) and add:

- **Greeks aggregation**: live net Δ/Γ/Θ/Vega limits at portfolio level; block trades that breach exposure caps.
- **Scenario VaR / stress gate**: pre-trade, evaluate the *post-trade* book over the spot×IV grid; reject if worst-case loss exceeds limit (linear VaR is wrong for options — use the grid).
- **Pin/expiry risk control**: tighten limits into expiry; flatten or de-risk gamma near the zero-gamma flip on expiry day.
- **Concentration & correlation**: cap exposure that is really the same bet across NIFTY/FINNIFTY/SENSEX (they're highly correlated — three "independent" index trades may be one macro bet).
- **Margin headroom monitor**: keep buffer above SPAN+exposure; auto-throttle new entries as utilisation rises.

---

## 11. Platform & UX Features (matching best-in-class)

To match/exceed the retail platforms on usability (these are the visible features users love — built on top of the serious engine):

- **Visual multi-leg strategy builder** with live **payoff diagram**, breakevens, max-P/L, and **Greeks** (uTrade/AlgoTest parity), driven by your real IV surface.
- **Option-chain leg-builder**: click strikes to add legs; live margin via the SPAN model.
- **Multi-strategy backtest comparison** side-by-side (AlgoTest parity) with the CPCV/DSR columns retail tools *don't* have.
- **Paper → forward → live continuum**: one strategy, three modes, same code path (your `simulated_fill` is the foundation).
- **Per-strategy live MTM & order updates** (Quantiply parity) over WebSocket.
- **Command center / risk / signals / audit dashboards** (you have these) + a **research notebook** surface (Jupyter) wired to the feature store.
- **Internal strategy library** (Tradetron-marketplace concept, but private) with versioning and one-click paper-deploy.
- **Backtest report viewer** with the bias-audit header, Greeks attribution, and scenario heatmaps.

---

## 12. Technology Stack & Infrastructure

Keep your proven core; add the research/ops tooling that makes it world-class.

| Concern | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** (keep); optional **Rust/C++** later for hot loops | Your codebase + ecosystem; speed up only proven bottlenecks |
| Live engine | **asyncio** (keep) | Already in place |
| API | **FastAPI** (keep) + OAuth2/2FA | Already in place; add SEBI-grade auth |
| Operational DB | **TimescaleDB** (keep) | Time-series, compression, continuous aggregates |
| Research lake | **Parquet + DuckDB/Polars** (new); **ClickHouse** if scale demands | Fast wide scans over 15–20 yrs |
| State/queue | **Redis + Redis Streams** (keep/extend); **Kafka** only if needed | Event spine, replayability |
| Orchestration | **Prefect** (or Airflow) | Ingestion/retrain DAGs |
| ML | **scikit-learn, LightGBM/XGBoost, statsmodels/arch, PyTorch (optional), hmmlearn** | Layered models |
| Experiment tracking | **MLflow** | Reproducibility, model registry |
| Feature store | Custom thin (DuckDB+Redis) → **Feast** if needed | Train/serve parity |
| Dashboard | **React/Vite/Tailwind** (keep) | Already in place |
| Observability | **Prometheus + Grafana**, structured logs, **Sentry** | HFT-grade ops discipline |
| Packaging | **Docker + docker-compose** (keep) → k8s only if you scale out | You already have compose/migrate |
| CI/CD | **GitHub Actions**: lint, type-check, **pytest (your 55+ suite)**, backtest smoke, security scan | Quality gates |
| Secrets | **Vault / SOPS / cloud secret manager** | SEBI-grade secret handling |

**Latency note:** none of this makes you an HFT, and that's fine. Co-locate the live engine near the broker/exchange region (low-latency VPS in the same metro), keep the hot path lean, but **invest your effort in signal/risk quality, not microseconds** — that's where your ROI is.

---

## 13. SEBI Compliance & Regulatory Architecture (2026 framework)

SEBI's retail-algo framework (circular **SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013**, 4 Feb 2025) is **mandatory from 1 April 2026** — i.e., it is in force now. Compliance must be **built into the platform**, not bolted on. Key obligations and how the architecture meets them:

| SEBI requirement | Architecture response |
|---|---|
| **Algo-ID on every order** (exchange-assigned, traceable) | `compliance/` service tags every order with its registered Algo-ID + correlation ID before it reaches the broker adapter; immutable audit trail (you already have correlation IDs — extend) |
| **Broker-registered, exchange-approved strategies** | Strategy registry maps each deployable strategy to its broker/exchange registration; un-registered strategies are blocked from `live` mode |
| **OPS (orders-per-second) threshold** — <10 OPS = normal API user; ≥ triggers algo-trader obligations | An **OPS limiter** in the order path enforces a configurable cap (stay in the retail/normal band by design); throttle + alert on approach |
| **Static IP whitelisting** | Live engine runs from a fixed whitelisted IP (dedicated VPS); documented in deployment |
| **OAuth login + 2FA; auto session logout before pre-open** | FastAPI auth uses broker OAuth + 2FA; scheduled token invalidation before each market pre-open |
| **Broker responsible for monitoring** | Provide broker-facing logs/exports; design assuming the broker can audit your flow |
| **Investor-grievance / kill-switch** | Durable panic/flatten (§10.1) + audit exports |

**Compliance is a gate, not a feature flag:** the control plane refuses to arm `live` mode unless Algo-ID, registration, static-IP, auth, and OPS-limit checks all pass (this folds into the §10.1 pre-live readiness check).

> This section describes engineering for compliance; it is **not legal advice**. Confirm current obligations with your broker and a qualified professional before live deployment — the framework is new and details evolve.

---

## 14. Phased Implementation Roadmap

Sequenced so each phase delivers standalone value and de-risks the next. Durations assume focused part-time effort; compress with more resourcing. The four pillars you selected are spread across phases by dependency (data must come first).

### Phase 0 — Foundations & safety (do first)
- Stand up `dataplatform/` skeleton, contract-spec & expiry resolver (§5.5), market-holiday DB.
- Ingest **free EOD bhavcopy** history (NSE/BSE) → survivorship-free EOD spine (~15+ yrs).
- Repo/infra hygiene: CI (your 55+ tests), MLflow, Prefect, Parquet lake, observability baseline.
- **Begin closing live P0s** from `upgrade.md` (mode atomicity, reconciliation scaffolding) — even though live is off, build it right.
- *Exit criteria:* as-of contract resolution works; EOD history queryable from the lake; CI green.

### Phase 1 — Data depth & feature library *(Pillar 1 + Pillar 2)*
- Add **paid 1-min vendor** (TrueData/GDFL) adapter; backfill ~6–10 yrs of 1-min options/futures.
- Build the **`features/` library** (full §6 catalog) with parity tests; compute & store features over full history.
- IV surface, skew, term-structure, GEX, OI analytics implemented and validated vs. a derived provider.
- *Exit criteria:* feature store populated; live==research parity proven; bias-guard data ready.

### Phase 2 — Research, labelling & validation *(Pillar 3)*
- Triple-barrier + meta-labelling + sample weighting; fractional-diff features.
- Train baseline→GBM→regime models; build **CPCV + DSR + PBO** validation harness.
- MLflow tracking + model registry with `dev→shadow→paper→live` staging.
- *Exit criteria:* a strategy can be evaluated end-to-end with CPCV/DSR/PBO and a reproducible run.

### Phase 3 — Backtesting engine *(Pillar 4)*
- Vectorised research engine + **event-driven options engine**; SPAN-style margin model.
- Greeks-attributed P&L, scenario/stress/Monte-Carlo, bias-audit header, multi-strategy comparison.
- *Exit criteria:* both engines agree within tolerance on reference strategies; reports include all rigour metrics.

### Phase 4 — Strategy/signal engine *(Pillar 5)*
- Implement the 7-step pipeline; structure-selection library for NIFTY/FINNIFTY/SENSEX.
- IV/GEX routing + microstructure confirmation; integrate meta-label sizing + your R-engine.
- Validate a small portfolio of defined-risk strategies through Phases 2–3 gates.
- *Exit criteria:* ≥1 strategy per index passes CPCV/DSR/PBO and event-driven backtest.

### Phase 5 — Execution & risk hardening (finish the P0s)
- Complete all §10.1 P0s; smart multi-leg execution; partial-fill reconciliation; broker reconciliation loop.
- Options-portfolio risk layer (Greeks limits, scenario-VaR gate, pin/expiry control).
- *Exit criteria:* full pre-live readiness check passes; paper-trading runs clean for a sustained period.

### Phase 6 — Compliance, paper-live & UX
- SEBI `compliance/` service (Algo-ID, OPS limiter, registration, static-IP/OAuth/2FA).
- Visual strategy builder, payoff/Greeks, multi-strategy comparison, per-strategy MTM.
- Extended **paper/forward trading** across full expiry cycles; shadow-mode models.
- *Exit criteria:* compliance gate green; paper results track backtest expectations.

### Phase 7 — Controlled live (only after everything above)
- Tiny capital, one index, one strategy; broker reconciliation verified live; scale **only** on evidence.
- Continuous drift monitoring, scheduled retrain, ongoing CPCV re-validation.

> **Sequencing rule:** never let strategy enthusiasm outrun data/validation maturity. The order (data → features → validation → backtest → strategy → execution → compliance → live) is deliberate; skipping ahead is how good ideas become real losses.

---

## 15. Success Metrics & KPIs

Define "world-class" by measurable gates, not vibes:

**Data quality**
- ≥15 yrs EOD + ≥6 yrs 1-min options coverage; <0.1% unflagged gaps; 100% point-in-time contract resolution; vendor-vs-bhavcopy settlement match within tolerance.

**Research rigour**
- Every promoted strategy: positive across **>60% of CPCV combinatorial folds**, **Deflated Sharpe > 0**, **PBO < 0.5**; reproducible from a pinned dataset + feature versions.

**Backtest fidelity**
- Vectorised vs. event-driven headline metrics agree within tolerance; costs modelled to the rupee; bias-audit header all-green for promotable runs.

**Live (post-P0) operational**
- Broker reconciliation divergences = 0 unresolved; pre-live readiness check pass-rate enforced; partial-fill incidents auto-resolved; panic/flatten acknowledged < target latency.

**Risk**
- No breach of portfolio Greeks/scenario-VaR limits; kill-switch/brakes verified by drills; max drawdown within mandate across Monte-Carlo distribution.

**Strategy performance** *(track, never promise)*
- Out-of-sample expectancy-R, Sortino/Calmar, cost drag %, capacity — judged on the **CPCV distribution**, not a single curve.

---

## 16. Risks & Honest Limitations

A world-class plan states its own risks plainly:

1. **You will not out-latency HFTs.** This plan deliberately does not try. If a strategy's edge requires beating co-located firms to a quote, it is not for you.
2. **Deep intraday options history is scarce/expensive.** The 15–20-yr ambition is *tiered* (§5.1); the options-specific edge is validated on ~6–10 yrs, not 20. Setting this expectation correctly prevents disappointment and bad backtests.
3. **Overfitting is the default outcome**, not the exception. The entire Pillar-3 apparatus (CPCV/DSR/PBO) exists because most "profitable" options backtests are statistical mirages. Respect the gates even when a curve looks beautiful.
4. **Costs can be the whole strategy.** High-churn weekly-option strategies live or die on slippage + statutory costs; model them worst-realistic.
5. **Regulatory change is constant.** Expiry rules, lot sizes, fees, and the SEBI algo framework itself keep moving — which is why everything is effective-dated and compliance is a core service.
6. **Live trading risks real capital.** Nothing here is a profit guarantee. The P0 safety items and the paper→shadow→tiny-live progression exist to make failure survivable.
7. **This is not investment or legal advice.** It is a software architecture plan. Trading index derivatives carries substantial risk of loss; position sizing and the risk engine reduce — but never eliminate — that risk. Validate compliance with your broker and a qualified professional before going live.

---

## 17. Appendices

### 17.A Feature catalog (machine-readable seed)

A `features/catalog.yaml` should enumerate every feature. Seed structure:

```yaml
- id: rsi_14_5m
  category: momentum
  fn: features.momentum.rsi
  params: {period: 14, timeframe: 5m}
  lookback_bars: 100
  version: 1
  point_in_time: true
- id: atr_pct_14_1d
  category: volatility
  fn: features.volatility.atr_pct
  params: {period: 14, timeframe: 1d}
  version: 1
- id: net_gex
  category: options
  fn: features.options.net_gex
  params: {strikes: full_chain}
  version: 1
- id: vrp_atm
  category: options
  fn: features.options.variance_risk_premium
  params: {iv: atm, rv_model: har}
  version: 1
- id: ofi_l5
  category: microstructure
  fn: features.microstructure.order_flow_imbalance
  params: {levels: 5}
  version: 1
  history: recent_only
```

### 17.B Core data schemas (Timescale hot store — sketch)

```sql
CREATE TABLE option_snapshot (           -- hypertable on ts
  ts TIMESTAMPTZ, underlying TEXT, expiry DATE, strike NUMERIC, opt_type CHAR(2),
  ltp NUMERIC, bid NUMERIC, ask NUMERIC, bid_qty INT, ask_qty INT,
  volume BIGINT, oi BIGINT, iv NUMERIC, delta NUMERIC, gamma NUMERIC,
  theta NUMERIC, vega NUMERIC, source TEXT
);
SELECT create_hypertable('option_snapshot','ts');

CREATE TABLE candles_1m (                 -- underlying + futures + per-option
  ts TIMESTAMPTZ, symbol TEXT, o NUMERIC, h NUMERIC, l NUMERIC, c NUMERIC,
  volume BIGINT, oi BIGINT, source TEXT
);
SELECT create_hypertable('candles_1m','ts');

CREATE TABLE iv_history (ts TIMESTAMPTZ, underlying TEXT, expiry DATE,
  atm_iv NUMERIC, rr_25 NUMERIC, bf_25 NUMERIC, iv_rank NUMERIC, iv_pct NUMERIC);
```

Cold lake mirrors these as Parquet partitioned by `underlying/year/month`, queried via DuckDB.

### 17.C Vendor comparison (quick reference)

| Vendor | Data | History | Cost | Role in this plan |
|---|---|---|---|---|
| NSE/BSE bhavcopy | EOD F&O OHLC/OI/settlement | ~15+ yrs | Free | Survivorship-free EOD spine |
| TrueData | tick/1-min, options chains | ~2017→ | Paid | Primary intraday research corpus |
| Global Datafeeds (GDFL) | tick/snapshot, authorised | recent-deep | Paid | Authorised tick + redundancy |
| Kite Connect | live + shallow historical | recent | Incl. w/ broker | Live feed + execution |
| Dhan/Fyers/Breeze | live + historical | varies | Incl./paid | Redundant live feed |
| Sensibull/Opstra (derived) | IV/Greeks/OI analytics | — | Freemium/paid | Cross-check your computations |

### 17.D Key references / concepts to study

- M. López de Prado, *Advances in Financial Machine Learning* — triple-barrier, meta-labelling, sample uniqueness, fractional differentiation, CPCV, PBO, deflated Sharpe.
- Bailey & López de Prado — *The Deflated Sharpe Ratio*; *Probability of Backtest Overfitting*.
- Easley, López de Prado, O'Hara — *VPIN / flow toxicity*.
- Cont, Kukanov, Stoikov — *Order Flow Imbalance & price impact*.
- Gatheral — *The Volatility Surface* (SVI); options skew/term-structure.
- QuantInsti / Blueshift docs — bias-free dataset & research→live methodology (benchmark for your research platform).
- SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (retail algo framework) — confirm latest with your broker.

### 17.E Glossary (selected)

**CPCV** — Combinatorial Purged Cross-Validation. **DSR** — Deflated Sharpe Ratio. **PBO** — Probability of Backtest Overfitting. **OFI** — Order Flow Imbalance. **GEX** — Gamma Exposure. **VRP** — Variance Risk Premium (IV − realised vol). **SPAN** — Standard Portfolio Analysis of Risk (margin). **Triple-barrier** — path-aware labelling via profit/stop/time barriers. **Meta-labelling** — secondary model sizing/vetoing a primary signal. **Microprice** — size-weighted fair price between bid/ask. **Point-in-time** — using only information available as-of the historical instant.

---

## Closing note

This blueprint keeps the genuine strengths of `AI_Trading_System` (R-based risk, gate pipelines, audit/correlation discipline, simulated fills, meta-labelling philosophy) and rebuilds the rest to an institutional standard: **deep point-in-time data, a complete feature library, anti-overfitting validation, an options-aware backtester, and a compliant, hardened live path** — focused, as you asked, on NIFTY / FINNIFTY / SENSEX F&O.

It is intentionally realistic about HFT: you win on **rigour, risk, and research**, not microseconds. Build the foundation in the order given, let the validation gates do their job, and the result will out-class the retail platforms on the things that actually compound — while never pretending to be something it isn't.

*Next step:* on your go-ahead, I'll start implementing **Phase 0 + Pillar 1** (the `dataplatform/` package: contract/expiry resolver, bhavcopy EOD ingestion, Timescale schema + Parquet lake, quality jobs) as working code in this folder.










