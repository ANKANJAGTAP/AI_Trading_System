# Risk Policy

The limits the risk engine enforces, and why. This is documentation; the **source of
truth is [`config/risk.yaml`](config/risk.yaml)** (every value is operator-tunable and
some are hot-overridable via `PUT /api/config`). Where a number here disagrees with the
YAML, the YAML wins. All limits apply to every sleeve unless stated otherwise.

Two principles run through everything below:

- **Exits are never blocked.** Every brake, circuit, and the kill switch stops *new
  entries* (and the kill switch additionally flattens). Closing, cancelling, and
  reducing risk are always allowed — the system can always get *out*.
- **Fail closed.** When a limit is ambiguous or a check can't run, the engine declines
  to add risk rather than assuming it's safe.

---

## Capital base

`R` (the rupee amount risked per trade) is a percentage of capital. Which capital:

| Mode | Capital used | Risk % source |
|------|--------------|---------------|
| Live | Live Kite margin / equity | `per_trade_risk_pct` (spec canonical) |
| Paper (`paper_capital > 0`) | Static `paper_capital` = **₹10,00,000** | `paper_per_trade_pct` |

The paper overlay is engine-only and leaves the canonical spec risk untouched; orders
are always `simulated_fill` (no real orders are sent in paper mode). Paper sizing
**compounds** (`paper_compound: true`) — it follows the running balance (₹10L + cumulative
realized P&L), so the month answers "what happens to my ₹10L," not fixed-notional
trading. Set `paper_capital: 0` to return to live capital + spec risk.

## Per-trade risk (R)

| | Live (spec) | Paper (today) |
|---|---|---|
| Per-trade risk | 1.0–2.0%, default **1.0%** | **1.0%** |

The paper per-trade was cut from 2% to 1% on 2026-06-12 because daily swings were too
large.

## Position sizing

Canonical formula (spec §4):

```
Stop-Loss %   = (entry_price − stop_price) / entry_price
Capital alloc = Risk Amount / Stop-Loss %          (== Quantity × entry_price)
Quantity      = Risk Amount (R, ₹) / (entry_price − stop_price)
Max Positions = Portfolio Risk Limit / Risk Per Trade
```

Computed size is then **clamped down** through a fixed precedence — per-instrument cap →
sleeve cap → portfolio remaining R → live margin — and floored to the instrument lot
size. Defined-risk option structures size off the structure's known max-loss per lot
instead of a stop distance. Confidence (0–1) scales R linearly. A position can only ever
come out **smaller** than the formula, never larger.

## Portfolio & concentration caps

| Limit | Value | What it bounds |
|---|---|---|
| `portfolio_risk_limit_pct` | **4.0%** | Max aggregate open R at once (⇒ ≤ 4 concurrent 1R positions) |
| `per_instrument_cap_pct` | **15.0%** | No single tradingsymbol > this % of capital (notional) |
| `per_underlying_risk_pct` | **4.0%** | Max aggregate open R on one underlying across all its strikes/legs |
| `leverage.target_effective_exposure` | **1.5–3.0×** | Target band, used "only when needed" — never max available |

The per-underlying cap exists because the per-instrument cap is *per symbol*, so stacked
strikes of the same name would otherwise bypass it.

## Kill switch (hard daily loss)

| | Live (spec) | Paper (today) |
|---|---|---|
| `daily_max_loss_pct` | 1.0–4.0%, default **3.0%** | **2.5%** |

On trip (`flatten_on_trip: true`): **block all new entries and square off** open
positions. The kill-switch state is global and survives restart; it clears only on an
explicit operator reset (`POST /api/controls/killswitch/reset`, ADMIN scope). A
correlation cluster (daily-return correlation > **0.7** over a 120-day lookback) is
treated as a single concentrated risk.

## Soft circuits (block new entries only — do **not** flatten)

| Circuit | Trigger |
|---|---|
| Max drawdown | Intraday equity drawdown from peak ≥ **8.0%** → halt new entries |
| Profit lock | Once peak day-P&L ≥ **2.0%** of capital, halt new entries if **> 35%** of that peak is given back |

These lock in green days and stop bleed without forcing liquidation — flattening is the
kill switch's job at the hard daily-loss line.

## Period brakes (slow-bleed protection)

The daily kill switch can't catch a slow grind (e.g. −2%/day for weeks never trips a 3%
daily line). Realized loss beyond these blocks new entries for the **rest of the period**
(latched; auto-resets when the period rolls):

| Brake | Limit |
|---|---|
| `weekly_max_loss_pct` | **6.0%** realized loss since Monday |
| `monthly_max_loss_pct` | **10.0%** realized loss since the 1st |

## Activity brakes (per day, reset midnight IST)

| Brake | Limit |
|---|---|
| `max_trades_per_day` | **15** (a structure counts once by correlation_id, not per leg) |
| `max_consecutive_losses` | **4** straight losers in a sleeve → that sleeve stops entering for the day |
| `reentry_cooldown_minutes` | **20** min block on re-entering the same instrument/underlying after a close (kills the churn loop) |

## Strategy guard (expectancy discipline)

A losing system is disabled rather than negotiated with after the fact:

| Window | Condition | Action |
|---|---|---|
| Rolling 20 trades (min 10) | Mean R < **−0.2** | Auto-disable the sleeve |
| Lifetime ≥ 60 trades | Mean R < **−0.1** | Kill + **human review required** (no auto re-enable) |

## Volatility-scaled sizing

`vol_scaling.enabled: true`. At or below `reference_vix` = **15.0**, full size; above it,
per-trade R shrinks proportionally (`ref / VIX`), floored at **0.4×**. High India VIX also
spikes margins, so positions sized for calm regimes would otherwise get force-liquidated
in storms.

## Cost & utilization gates

| Gate | Rule |
|---|---|
| `cost_edge_max_fraction` | Skip a trade if round-trip costs exceed **15%** of expected reward at target |
| `min_risk_utilization` | If caps/margin clamp the position below **1%** of intended R, skip entirely (a 1-share token position is noise, not a trade) |

## How limits are enforced

Sizing math lives in dependency-light pure helpers (`risk/sizing.py`) and the entry/exit
gates in `execution/policy.py`, so the policy is unit-tested without a database. The
engine evaluates brakes continuously; the API exposes current state on the Risk and
Pre-Live Readiness screens. Operators tune limits in `config/risk.yaml` (restart to apply)
or hot-override the two paper knobs via `PUT /api/config` (bounded + audited).

> This describes the system's automated controls. It is not investment or financial
> advice. Validate your own SEBI / broker obligations before trading live capital.
