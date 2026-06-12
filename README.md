# AI Trading System

Real-time algorithmic trading platform for Indian markets. The project targets NSE/BSE equities, F&O, and MCX commodities through Zerodha Kite Connect, with a FastAPI control plane, asyncio engine, TimescaleDB storage, Redis state/commands, and a React operator dashboard.

Important status: the system is useful for research, backtesting, simulation, paper-style `simulated_fill`, dashboards, and risk-engine development. It is **not live-production ready yet**. The live execution path exists, but the latest audit found several P0 safety gaps around mode switching, broker-fill accounting, partial fills, command durability, and live pre-flight checks. See [upgrade.md](upgrade.md) for the detailed hardening backlog.

## Current State

| Area | Status | Notes |
|---|---|---|
| Core repo structure | Implemented | Modular backend, dashboard, migrations, scripts, tests |
| Config system | Implemented | Pydantic settings plus YAML tunables |
| Database schema | Implemented | TimescaleDB tables for market data, trading, audit, dashboard, research |
| Broker adapter | Implemented | Kite adapter, token store, TOTP/login helpers, diagnostics |
| Market data | Implemented | Instruments, historical data, candles, feed, indicators, option chain, IV history |
| Strategy pipelines | Implemented | Intraday stocks, swing stocks, F&O, MCX intraday/swing |
| Risk engine | Implemented | R-sizing, sleeve caps, portfolio caps, kill switch, brakes, heat |
| Execution | Partially implemented | Simulated fill is stronger than live path; live path needs P0 hardening |
| F&O structures | Simulated implemented | Defined-risk structure lifecycle exists; live multi-leg execution is blocked |
| Backtesting | Implemented | Equity, momentum, swing, F&O, walk-forward, metrics |
| Research layer | Implemented | Trade journal, meta-labeler, feature extraction, discrimination reports |
| API | Implemented | Health, controls, market data, analytics, backtest, research, websocket |
| Dashboard | Implemented | React/Vite operator console |
| Tests | Implemented | Current suite: `55 passed` |
| Institutional live readiness | Not ready | See [upgrade.md](upgrade.md) |

## Safety Warning

Default mode is `simulated_fill`: real signals and live/recorded prices, but no real order in that mode. Live trading must remain disabled until the P0 items in [upgrade.md](upgrade.md) are fixed.

Known live blockers include:

- Runtime paper/live mode can diverge between executor, risk, capital, and kill-switch state.
- Pre-live checklist is not yet a real executable broker/readiness proof.
- Live exits currently need product-aware handling and broker-fill-based accounting.
- Partial fills need cancellation/reconciliation lifecycle hardening.
- Panic/flatten commands need durable acknowledgement and retry semantics.
- Venue-aware feed/session safety, especially MCX after NSE close, needs hardening.
- API/auth/secrets/infrastructure defaults need production hardening.

## Architecture

```text
dashboard/React
      |
      v
api/FastAPI  <----> Redis state, websocket, command queue
      |
      v
engine/asyncio orchestrator
      |
      +--> data feed, candles, indicators, option chain
      +--> strategy pipelines and gate results
      +--> confidence model and optional meta-label filter
      +--> risk engine, kill switch, brakes, heat
      +--> execution simulator or broker executor
      +--> TimescaleDB positions, orders, fills, signals, audit, research
```

## Repository Layout

```text
api/          FastAPI app, routes, websocket, services, analytics, backtest/research APIs
backtest/     historical simulation engines, simulated broker, metrics, walk-forward
broker/       broker adapter interface, Kite adapter, login/token helpers
common/       DB, Redis, audit, commands, alerts, events, logging, time utilities
config/       typed config loader, environment settings, YAML strategy/risk/execution tunables
dashboard/    React/Vite/Tailwind operator dashboard
data/         instruments, feed, candles, indicators, option chain, IV, OI, GEX, volume profile
engine/       asyncio engine, orchestrator, context builder, confidence model
execution/    cost model, simulator, executor, brackets, guards, structures, recovery
llm/          LLM/news context provider interface
migrations/   SQL migrations and migration runner
ops/          runbook, systemd unit, entrypoint, experiment log
research/     meta-labeler, feature extraction, journal, dataset, edge reports
risk/         capital reader, R-sizing, risk engine, kill switch, heat, circuits
scripts/      migrations, diagnostics, verification, reports, training helpers
strategies/   intraday, swing, F&O, MCX pipelines
tests/        unit tests for math, indicators, research, backtest, risk helpers
upgrade.md    audit-driven upgrade and bug-finder backlog
```

## Implemented Trading Sleeves

| Sleeve | Product Intent | Current Logic |
|---|---|---|
| `intraday_stocks` | NSE/BSE intraday equity | ORB and VWAP-pullback with liquidity, time, regime, breadth, stop-distance, RVOL, momentum, gap/sector filters |
| `swing_stocks` | CNC equity swing | Fundamentals, 200 DMA, market regime, sector strength, technical setup, event gate, ATR stop |
| `fno` | Defined-risk options | IV-regime routing, DTE gate, OI/direction, credit/debit structures, Greeks, finite max loss |
| `mcx_commodities` | MCX intraday/swing | Reuses intraday/swing logic with commodity session assumptions and no equity sector/fundamental requirement |

## Strategy Gate Model

Each strategy is a deterministic gate pipeline. A hard gate can reject a signal. Soft gates contribute score. Accepted signals carry:

- sleeve
- instrument
- side
- setup
- entry
- stop
- target
- detail payload
- gate trail
- confidence
- correlation id

The LLM layer, where used, is designed as context/veto only. It should not be the primary decision maker.

## Core Risk Math

The system thinks in `R`, not lots.

### Per-Trade R

```text
R_rupees = capital * per_trade_risk_pct / 100
effective_R = R_rupees * confidence
```

`confidence` is clamped to `[0, 1]`, so confidence can reduce size but cannot exceed the configured R budget.

### Price-Stop Position Sizing

Used for equities, futures, and option buys where risk is defined by entry and stop:

```text
risk_per_unit = abs(entry_price - stop_price)
raw_units = floor(effective_R / risk_per_unit)
quantity = floor_to_lot(raw_units, lot_size)
actual_risk = quantity * risk_per_unit
capital_allocated = quantity * entry_price
```

Then quantity is clamped by:

```text
per_instrument_cap_units = floor_to_lot((capital * per_instrument_cap_pct / 100) / entry_price)
sleeve_cap_units = floor_to_lot(sleeve_remaining_capital / entry_price)
portfolio_risk_units = floor_to_lot(portfolio_remaining_R / risk_per_unit)
live_margin_units = floor_to_lot(margin_available / margin_per_unit)
```

If final quantity is below one share/lot, the trade is rejected.

### Defined-Risk F&O Structure Sizing

Used for credit spreads, debit spreads, and iron condors:

```text
effective_R = capital * per_trade_risk_pct / 100 * confidence
raw_lots = floor(effective_R / max_loss_per_lot)
quantity = raw_lots * lot_size
actual_risk = raw_lots * max_loss_per_lot
```

Then lots are clamped by:

```text
portfolio_lots = floor(portfolio_remaining_R / max_loss_per_lot)
underlying_lots = floor(underlying_remaining_R / max_loss_per_lot)
margin_lots = floor(margin_available / margin_per_lot)
max_lots_per_structure
```

### Max Concurrent Positions

```text
max_concurrent_positions = floor(portfolio_risk_limit_pct / per_trade_risk_pct)
```

Structures are counted as one trade, not one trade per leg.

### Portfolio Remaining R

```text
portfolio_R_limit = capital * portfolio_risk_limit_pct / 100
portfolio_remaining_R = max(0, portfolio_R_limit - total_open_R)
```

### Sleeve Remaining Capital

```text
sleeve_cap_rupees = capital * sleeve_cap_pct / 100
sleeve_remaining = max(0, sleeve_cap_rupees - deployed_by_sleeve)
```

### India VIX Volatility Scaling

When enabled:

```text
if India_VIX <= reference_vix:
    vol_scale = 1
else:
    vol_scale = max(min_scale, reference_vix / India_VIX)

vol_scaled_per_trade_risk_pct = per_trade_risk_pct * vol_scale
```

This reduces new position size in high-volatility regimes.

## Kill Switch And Risk Circuits

### Daily Kill Switch

```text
max_loss_limit = -starting_capital * daily_max_loss_pct / 100
day_pnl = realized_pnl + unrealized_pnl
trip = day_pnl <= max_loss_limit
```

When tripped, new entries are blocked. Depending on config, flattening can also be triggered.

### Intraday Drawdown Brake

```text
drawdown = peak_day_pnl - current_day_pnl
breached = drawdown >= capital * max_drawdown_pct / 100
```

This blocks new entries rather than being a forced flatten rule.

### Profit Lock Brake

```text
trigger = capital * trigger_pct / 100
floor = peak_pnl * (1 - max_giveback_pct / 100)
breached = peak_pnl >= trigger and current_pnl <= floor
```

Used to stop adding risk after a large green day gives back too much.

### Sleeve Expectancy Brake

```text
expectancy_R = mean(recent_R_multiples)
disable_sleeve = len(recent_R_multiples) >= min_trades and expectancy_R < expectancy_floor
```

### Period Loss Brake

```text
breached = realized_period_pnl <= -(capital * max_period_loss_pct / 100)
```

### Loss Streak Brake

```text
breached = most_recent_N_trade_pnls are all negative
```

## Confidence Math

Confidence is a transparent weighted average over evaluated gates:

```text
confidence = sum(weight_i * gate_score_i) / sum(weight_i)
```

Hard-gate failures reject before confidence is used. Soft weak gates remain in the denominator and reduce confidence. The risk engine then uses:

```text
effective_R = raw_R * confidence
```

## Indicator Math

The indicator library is implemented directly with pandas/numpy, without a black-box TA dependency.

### SMA

```text
SMA_n = rolling_mean(close, n)
```

### EMA

```text
EMA_n = exponentially_weighted_mean(close, span=n, adjust=False)
```

### 200 DMA

```text
DMA_200 = SMA_200(daily_close)
```

### True Range And ATR

```text
TR = max(high - low, abs(high - previous_close), abs(low - previous_close))
ATR_n = Wilder_EMA(TR, alpha=1/n)
```

### ADX / DI

```text
up_move = high.diff()
down_move = -low.diff()
+DM = up_move if up_move > down_move and up_move > 0 else 0
-DM = down_move if down_move > up_move and down_move > 0 else 0
+DI = 100 * Wilder_EMA(+DM) / ATR
-DI = 100 * Wilder_EMA(-DM) / ATR
DX = 100 * abs(+DI - -DI) / (+DI + -DI)
ADX = Wilder_EMA(DX)
```

### RSI

```text
delta = close.diff()
gain = max(delta, 0)
loss = max(-delta, 0)
RS = Wilder_EMA(gain) / Wilder_EMA(loss)
RSI = 100 - 100 / (1 + RS)
```

### RVOL

```text
RVOL = current_volume / rolling_mean(volume, n)
```

### VWAP

```text
typical_price = (high + low + close) / 3
VWAP = cumulative_sum(typical_price * volume) / cumulative_sum(volume)
```

### Session VWAP

Same as VWAP, but cumulative sums reset each trading day.

### MACD

```text
MACD_line = EMA_12(close) - EMA_26(close)
signal_line = EMA_9(MACD_line)
histogram = MACD_line - signal_line
```

### Bollinger Bands

```text
middle = SMA_20(close)
upper = middle + k * population_std(close, 20)
lower = middle - k * population_std(close, 20)
```

### Donchian Channel

```text
upper = rolling_max(high, n)
lower = rolling_min(low, n)
middle = (upper + lower) / 2
```

### SuperTrend

```text
HL2 = (high + low) / 2
basic_upper = HL2 + multiplier * ATR
basic_lower = HL2 - multiplier * ATR
```

Final bands trail until price closes through them. Direction is `+1` when the supertrend line is the lower band and `-1` when it is the upper band.

### Anchored VWAP

```text
anchored_VWAP = cumulative_sum(typical_price * volume from anchor) / cumulative_sum(volume from anchor)
```

## Regime And Context Math

### Intraday Regime

If enough candles exist:

```text
trend if ADX >= adx_trend_min
trending_up if +DI >= -DI and price >= VWAP
trending_down if -DI > +DI and price <= VWAP
otherwise choppy
```

Fallback:

```text
if abs(price - VWAP) / VWAP <= 0.0015:
    choppy
elif price > VWAP:
    trending_up
else:
    trending_down
```

### Opening Range

```text
OR_high = max(high from 09:15 to 09:30)
OR_low = min(low from 09:15 to 09:30)
```

### Gap Percentage

```text
gap_pct = (today_open - previous_daily_close) / previous_daily_close * 100
```

### ATR Percentage

```text
atr_pct = ATR_14 / last_price * 100
```

### Relative Strength

```text
relative_strength = stock_20d_return_pct - index_20d_return_pct
```

## Intraday Stock Logic

Hard gates:

1. Liquidity and spread.
2. Entry time window.
3. Trending regime; choppy rejects.
4. ORB or VWAP-pullback setup.
5. Optional breadth agreement.
6. Stop-distance sanity.
7. VWAP-side and RVOL confirmation.
8. Sector strength when required.

Setup math:

```text
ORB long:  price > OR_high and regime == trending_up and extension <= max_extension_pct
ORB short: price < OR_low and regime == trending_down and extension <= max_extension_pct

VWAP pullback long:  abs(price - VWAP) / VWAP <= 0.003 and price >= VWAP
VWAP pullback short: abs(price - VWAP) / VWAP <= 0.003 and price <= VWAP

stop_pct = abs(entry - stop) / entry * 100
target = entry +/- reward_R * abs(entry - stop)
```

Soft confidence inputs include MACD histogram, SuperTrend direction, gap, and sector state.

## Swing Stock Logic

Hard gates:

1. Fundamentals: market cap, ROE, revenue growth, EPS growth, debt/equity, promoter trend, ADV.
2. Price above 200 DMA.
3. Broad market uptrend.
4. Sector strength.
5. Pullback/base-breakout technical setup.
6. Event window gate.

Stop/target math:

```text
stop = last_price - atr_multiple * ATR
risk = last_price - stop
target = last_price + 2 * risk
```

## F&O Logic

The F&O sleeve is defined-risk only. Naked option selling is intentionally not allowed.

### IV Regime Routing

```text
if IV_rank < low_max:
    regime = buy_debit
    DTE window = weekly_buy
elif IV_rank > high_min:
    regime = sell_credit
    DTE window = credit_sell
else:
    regime = spread
    DTE window = swing_buy
```

Credit selling is blocked when IV is actively spiking beyond the configured 5-day threshold.

### Direction And OI

Daily direction:

```text
SMA20 = mean(last 20 daily closes)
bullish if spot > SMA20 * (1 + band)
bearish if spot < SMA20 * (1 - band)
neutral otherwise
```

Put-call ratio:

```text
PCR = put_OI / call_OI
PCR signal = bullish if PCR > 1.2, bearish if PCR < 0.8, neutral otherwise
```

OI buildup matrix:

```text
price up   + OI up   = long buildup / bullish
price down + OI up   = short buildup / bearish
price up   + OI down = short covering / bullish
price down + OI down = long unwinding / bearish
```

OI delta bias:

```text
if PE_OI_change - CE_OI_change > 0:
    bullish
elif CE_OI_change - PE_OI_change > 0:
    bearish
else:
    neutral
```

### Structure Selection

Low IV and bullish:

```text
bull_call_debit = buy ATM CE, sell OTM CE
max_loss = net_debit * lot_size
```

Low IV and bearish:

```text
bear_put_debit = buy ATM PE, sell OTM PE
max_loss = net_debit * lot_size
```

Medium/high IV and bullish:

```text
bull_put_credit = sell OTM PE, buy farther OTM PE
max_loss = (width - credit) * lot_size
max_profit = credit * lot_size
```

Medium/high IV and bearish:

```text
bear_call_credit = sell OTM CE, buy farther OTM CE
max_loss = (width - credit) * lot_size
max_profit = credit * lot_size
```

Neutral premium-selling:

```text
iron_condor = bear call credit spread + bull put credit spread
max_loss = (wing_width - total_credit) * lot_size
max_profit = total_credit * lot_size
```

Short strikes are selected by walking away from ATM until absolute delta is at or below the configured maximum.

### Fill-Based Structure Risk

After simulated fills, real fill prices replace model estimates:

```text
net_premium = sum(SELL_entry * qty) - sum(BUY_entry * qty)
width_rupees = structure_width * qty

if net_premium >= 0:
    max_loss = width_rupees - net_premium
    max_profit = net_premium
else:
    debit = -net_premium
    max_loss = debit
    max_profit = width_rupees - debit
```

Structure guard:

```text
combined_pnl = sum(leg_pnl) - entry_fees
target when combined_pnl >= target_fraction * max_profit
stop when combined_pnl <= -stop_fraction * max_loss
```

## Black-Scholes And Options Math

Implemented directly in `data/options.py`.

### Normal CDF/PDF

```text
N(x) = 0.5 * (1 + erf(x / sqrt(2)))
phi(x) = exp(-0.5 * x^2) / sqrt(2*pi)
```

### d1 / d2

```text
d1 = (ln(S/K) + (r + 0.5*sigma^2)*t) / (sigma*sqrt(t))
d2 = d1 - sigma*sqrt(t)
```

Where:

- `S` = spot
- `K` = strike
- `t` = years to expiry
- `r` = annual risk-free rate
- `sigma` = implied volatility

### Call And Put Prices

```text
call = S*N(d1) - K*exp(-r*t)*N(d2)
put = K*exp(-r*t)*N(-d2) - S*N(-d1)
```

### Greeks

```text
call_delta = N(d1)
put_delta = N(d1) - 1
gamma = phi(d1) / (S * sigma * sqrt(t))
vega = S * phi(d1) * sqrt(t) / 100

call_theta_per_day =
    (-(S*phi(d1)*sigma)/(2*sqrt(t)) - r*K*exp(-r*t)*N(d2)) / 365

put_theta_per_day =
    (-(S*phi(d1)*sigma)/(2*sqrt(t)) + r*K*exp(-r*t)*N(-d2)) / 365
```

### Implied Volatility

Implied volatility is solved by bisection:

```text
lo = 0.0001
hi = 5.0
repeat 100 times:
    mid = (lo + hi) / 2
    diff = BS_price(mid) - market_price
    if diff > 0:
        hi = mid
    else:
        lo = mid
```

If price is below intrinsic or expiry is zero, IV returns `0`.

### IV Rank

```text
IV_rank = (current_IV - min(history_IV)) / (max(history_IV) - min(history_IV)) * 100
```

### IV Percentile

```text
IV_percentile = count(history_IV < current_IV) / len(history_IV) * 100
```

## Market Microstructure Math

### Gamma Exposure

```text
GEX_leg = gamma * open_interest * contract_size * spot^2 * 0.01
call_GEX adds
put_GEX subtracts
net_GEX = sum(call_GEX - put_GEX)
```

Interpretation:

- Positive gamma: dealers hedge against moves; mean-reverting/vol-suppressing.
- Negative gamma: dealers hedge with moves; trend/vol-amplifying.
- Call wall: strike with largest positive GEX.
- Put wall: strike with largest negative GEX.
- Flip strike: approximate cumulative zero-gamma crossing.

### Order Book Imbalance

```text
bid_qty = sum(top_N_bid_quantities)
ask_qty = sum(top_N_ask_quantities)
imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
```

Bias:

```text
buy if imbalance > 0.2
sell if imbalance < -0.2
neutral otherwise
```

### Volume Profile

Each candle volume is assigned to the bin of its typical price:

```text
typical_price = (high + low + close) / 3
bin_width = (highest_high - lowest_low) / bins
```

Then:

- POC = bin with maximum volume.
- Value area expands from POC until about 70% of volume is captured.
- VAH = highest price bin inside value area.
- VAL = lowest price bin inside value area.

## Execution Math

### Cost Model

For each leg:

```text
turnover = quantity * price
brokerage = flat fee or min(turnover * brokerage_pct / 100, flat_cap)
STT = turnover * stt_pct / 100 according to segment and side rules
CTT = turnover * ctt_pct / 100 for MCX sell side
transaction_fee = turnover * exchange_txn_pct / 100
SEBI_fee = turnover * sebi_per_cr / 1e7
stamp_duty = turnover * stamp_pct / 100 on BUY side
GST = (brokerage + transaction_fee + SEBI_fee) * gst_pct / 100
total_cost = brokerage + STT/CTT + transaction_fee + SEBI_fee + stamp_duty + GST
```

Round trip:

```text
round_trip_cost = entry_leg_cost + exit_leg_cost
```

### Simulated Fill Price

`simulated_fill` uses real quote/depth but does not send an order.

For a BUY, the simulator crosses the sell book. For a SELL, it crosses the buy book.

```text
book_vwap = sum(taken_quantity_i * price_i) / sum(taken_quantity_i)
slippage = book_vwap * slippage_bps / 10000

BUY_fill = book_vwap + slippage
SELL_fill = book_vwap - slippage
```

If quantity exceeds visible depth, remaining size is filled at the worst visible level plus an extra impact penalty:

```text
impact_penalty = worst_visible_price * slippage_bps * beyond_book_penalty / 10000
```

## Backtest Metrics

The canonical metrics are in `backtest/metrics.py`.

```text
win_rate = winning_trades / total_trades * 100
gross_win = sum(pnl where pnl > 0)
gross_loss = abs(sum(pnl where pnl < 0))
profit_factor = gross_win / gross_loss
expectancy_R = mean(R_multiples)
net_pnl = sum(pnl)
return_pct = net_pnl / starting_capital * 100
equity_curve_t = cumulative_pnl_t
drawdown_t = cumulative_pnl_t - peak_cumulative_pnl_so_far
max_drawdown = min(drawdown_t)
sharpe_like_R = mean(R_multiples) / population_stdev(R_multiples)
```

Walk-forward summary:

```text
mean_expectancy_R = mean(fold_expectancy_R)
expectancy_stdev = stdev(fold_expectancy_R)
folds_positive = count(fold_expectancy_R > 0)
verdict = consistent_positive / consistent_negative / mixed
```

## Research And Meta-Labeling Math

### Feature Extraction

The research layer stores continuous features, not only gate pass/fail:

- confidence
- hour, weekday
- RVOL
- gap percentage
- VWAP distance percentage
- MACD histogram
- SuperTrend direction
- spread percentage
- opening range percentage
- ATR percentage
- relative strength
- breadth flags
- stop percentage
- reward:risk
- IV, IV rank, IV change
- DTE
- PCR
- F&O direction flags
- moneyness
- credit ratio

### Logistic Meta-Labeler

Training standardizes features:

```text
X_standard = (X - mean(X)) / std(X)
z = X_standard @ weights + bias
p_win = 1 / (1 + exp(-z))
```

Loss optimization uses gradient descent with L2:

```text
weights = weights - learning_rate * (X.T @ error / n + l2 * weights)
bias = bias - learning_rate * mean(error)
```

Optional class weighting balances win/loss samples:

```text
positive_weight = n / (2 * positive_count)
negative_weight = n / (2 * negative_count)
```

Deployment semantics:

```text
if p_win < veto_below:
    multiplier = 0.0
elif p_win >= neutral_above:
    multiplier = 1.0
else:
    multiplier = soft_floor + (1 - soft_floor) * (p_win - veto_below) / (neutral_above - veto_below)
```

The meta-labeler can only veto or shrink confidence. It cannot increase size.

### Feature Discrimination

For every feature:

```text
median = median(feature_values)
win_rate_high = wins where feature >= median / count(feature >= median)
win_rate_low = wins where feature < median / count(feature < median)
lift = win_rate_high - win_rate_low
```

Verdict:

```text
insufficient_data if samples < 100
edge_present if best_abs_lift >= 0.15
weak_or_none otherwise
```

## Database And Persistence

Migrations create and evolve:

- instruments
- ticks and candles hypertables
- signals
- gate results
- orders
- fills
- positions
- audit log
- daily P&L
- config state
- dashboard state
- backtest tables
- IV history
- meta-model registry
- signal features
- journal tables

Audit entries and trading records carry correlation IDs so a decision can be traced through signal, gates, execution, and position state.

## API And Dashboard

Implemented API areas:

- health and mode/status
- account/risk/positions/signals
- control endpoints
- market data and chart endpoints
- option-chain endpoints
- analytics
- backtest
- research/meta-labeling
- websocket streaming

Dashboard areas:

- command center
- controls
- market/watch
- positions
- risk
- signals
- charts
- option chain
- analytics
- audit
- backtest
- settings
- sleeves

## Quick Start

### Docker

```bash
cp .env.example .env
# Fill broker, DB, Redis, SMTP, and optional LLM values.

make up
make migrate
curl -s localhost:8000/health
```

### Local Backend

```bash
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
python scripts/migrate.py
uvicorn api.app:app --reload
python -m engine.main
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev
```

## Verification

Current Python test suite:

```bash
PYTHONPATH=. python -m pytest tests -q
```

Latest known result:

```text
55 passed
```

Additional verification scripts:

```bash
python scripts/verify_phase0.py
python scripts/verify_phase1.py
python scripts/verify_phase2.py
python scripts/verify_phase3.py
python scripts/verify_phase4.py
python scripts/verify_phase5.py
python scripts/verify_phase6.py
python scripts/verify_phase6b.py
python scripts/verify_fno_exec.py
python scripts/verify_llm.py
```

Diagnostics:

```bash
python scripts/diag_engine.py
python scripts/diag_feed.py
python scripts/diag_kite_login.py
python scripts/diag_kite_endpoints.py
python scripts/diag_ticker.py
python scripts/diag_fno_context.py
python scripts/diag_fno_data.py
python scripts/diag_fno_segment.py
```

Reports/training:

```bash
python scripts/backtest.py
python scripts/equity_curve.py
python scripts/edge_report.py
python scripts/journal.py
python scripts/pnl_report.py
python scripts/train_meta.py
```

## Configuration

Main configuration files:

```text
.env.example              deployment and secret template
config/risk.yaml          R, caps, kill switch, brakes, heat
config/sleeves.yaml       sleeve capital allocation
config/execution.yaml     mode, slippage, fees, execution settings
config/data.yaml          feed, universe, rate limits, sessions
config/system.yaml        confidence, alerts, LLM/system behavior
config/strategy_params.yaml strategy gate thresholds and F&O routing
```

Secrets should stay in `.env` or an external secret manager. `.env`, `.secrets/`, dashboard build output, node modules, caches, and local assistant state are ignored by git.

## Current Main Limitations

The latest audit produced [upgrade.md](upgrade.md). Highest-priority fixes:

1. Atomic runtime mode state across API, executor, risk, capital, and kill switch.
2. Executable pre-live readiness checks.
3. Mode/account-scoped positions, capital, and P&L.
4. Product-aware live exits.
5. Broker-fill-based live close accounting.
6. Partial-fill cancellation and reconciliation.
7. Durable acknowledged panic/flatten commands.
8. Broker reconciliation loop.
9. Venue-aware session/feed watchdog.
10. Production-grade auth, secrets, Redis/Postgres exposure, CI, backups, and restore tests.

## GitHub

Remote repository:

```text
https://github.com/ANKANJAGTAP/AI_Trading_System.git
```

Current initial commit:

```text
e850b34 first commit
```

