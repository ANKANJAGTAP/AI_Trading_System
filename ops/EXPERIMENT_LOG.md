# Experiment Log & Trading Discipline Protocol

> Tier-3 process alpha. The market punishes improvisation; this file is the contract
> with ourselves. **Every parameter change gets a dated entry here BEFORE it goes live.**

## Baseline v1 — FROZEN 2026-06-12 (pre-open)

The configuration as deployed this morning. **No parameter changes until at least
2026-06-26 (10 sessions) or 60 closed trades, whichever comes first** — except for
genuine bug fixes (which must be logged below).

| Area | Setting | Source |
|---|---|---|
| Per-trade risk | 2% of running balance (compounding), VIX-scaled (ref 15, floor 0.4) | spec + vol-targeting research |
| Daily / weekly / monthly stops | −4% kill-switch / −6% brake / −10% brake | layered drawdown control |
| Activity | ≤15 trades/day, 4-loss streak benches a sleeve, 20-min re-entry cooldown | SEBI cost study (churn = death) |
| Concentration | ≤3 concurrent trades, ≤4% open R per underlying, sleeve caps | portfolio construction |
| Equity entries | Top-5 RVOL ("stocks in play"), breadth day-type gate, ORB ≤0.3% extension, stop ≤1.5%, cost-edge ≤15% | Zarattini et al. + regime research |
| Credit spreads | 30–45 DTE entry, short ≤0.22Δ, exit 50% profit / 50% max-loss / 21 DTE | premium-harvest research consensus |
| Debit spreads | exit 50%/50%, ≤2 DTE, ≤10 days held | theta/gamma control |
| Event discipline | No structures on FOMC ±1d, underlying expiry day; monthly-expiry equity flat by 14:30 | event/pinning studies |
| Vol guard | No fresh credit when ATM IV +15%/5d | vol-spike protection |
| ML overlay | Meta-labeler armed; activates only after OOS validation (≥80 trades, lift ≥5pp) | López de Prado / Hudson & Thames |

## Kill criteria (pre-committed — the machine enforces these)

- **Rolling:** sleeve expectancy < −0.2R over last 20 trades (≥10 samples) → sleeve auto-disabled for the day(s).
- **Lifetime:** after ≥60 closed trades, sleeve expectancy < −0.1R → **sleeve killed + email; human review required to re-enable. Do not re-enable on a feeling.**
- **System-level:** if the account is below ₹9.0L (−10%) at any month-end, halt everything and do a full strategy review before another rupee of (even paper) risk.

## Change protocol (one variable at a time)

1. Propose the change here with date, hypothesis, and the metric that will judge it.
2. Run it through walk-forward first: `python scripts/backtest.py --symbols ... --walkforward 4` — verdict must not be `inconsistent`.
3. Deploy ONE change. Observe ≥10 sessions or ≥40 trades before judging or changing anything else.
4. Judge on expectancy (R/trade) and max drawdown — never on a single day's P&L.

## What we do NOT do (standing rules, all machine-enforced where possible)

- ❌ No 0–1 DTE / expiry-day entries (`dte.avoid`, expiry-day gate) — the documented retail graveyard.
- ❌ No naked option selling, ever (`no_naked_selling` hard rule; every short leg hedged).
- ❌ No new indicators/filters without walk-forward proof (this log + review).
- ❌ No raising risk to "make it back" (period brakes latch; risk % only changes via this log).
- ❌ No judging or re-tuning before 60 trades (kill criteria timing; variance ≠ verdict).
- ❌ No overriding a tripped brake/kill-switch intra-period without writing the reason here first.

## Scheduled instrumentation (what watches the edge)

- **15:35 IST daily** — equity-curve email (running balance vs ₹10L + projection).
- **16:30 IST daily** — meta-labeler retrain (activates only if OOS-validated).
- **16:45 IST Friday** — edge-decay email (weekly expectancy per sleeve + feature lift).
- On demand: `python -m scripts.edge_report`, `python scripts/backtest.py --walkforward 4`.

---

## Change log

| Date | Change | Hypothesis | Judge by | Result (fill ≥10 sessions later) |
|---|---|---|---|---|
| 2026-06-12 | Baseline v1 frozen (all of the above) | research-backed defaults are net-positive after costs | expectancy ≥ +0.05R over first 60 trades | _pending_ |
| 2026-06-12 (EOD) | v1.1: per-trade R 2%->1%, daily stop 4%->2.5%, portfolio 6%->4%; dynamic exits (BE at +1R, lock 65% of peak past 80% of target); F&O-first caps 45/20/25/10; VRP credit routing; MCX wired; ML CV gate | smaller swings, same edge; winners can't round-trip to losers | 10-session observation starting 2026-06-13; judge at >=40 trades | _pending_ |

### Incident 2026-06-12 (EOD): -Rs 39,645 day — root-caused, 80% was an execution bug
- Condor stop fired on a GARBAGE book (24400CE bid~90/ask 228.8 — adjacent strikes can't differ by more than width; fill paid ~3x fair on one leg): planned stop -10.1k, realized -37.4k. Real market loss on the day's +1.9% NIFTY trend: ~-4.7k. Equities were NET POSITIVE (+1.7k).
- Fixes deployed same evening: marks AND exits reject any leg book with spread > 8% (`max_book_spread_pct`); structure close cost hard-capped at 115% of defined max loss (`max_close_loss_overrun`); bad-book exits postpone up to 5 cycles then force with alert; emergency paths (kill-switch/failsafe/operator) always force.
- Kill-switch + flatten verified working under real stress; manually reset after review per protocol. Balance: Rs 983,200 (-1.68% vs 10L start).
