#!/usr/bin/env bash
# RVOL mover-test — the one surviving equity-breakout lead. Backfills ~26 high-beta /
# mid-cap movers (5m, ~1yr) then reruns the confluence breakout on them TWICE: once
# plain (is the UNIVERSE alone enough?) and once with the --min-rvol 3 "in-play" gate
# (does conditioning on activity help?). Decision: does any K go gross-positive enough
# to clear the ~0.10% round-trip cost AND hold forward-OOS — vs the cost-killed +0.03%
# on large-caps? Historical only; run from the Mac, no market hours needed.
#
#   ./scripts/rvol_test.sh                 # backfill + both retests
#   ./scripts/rvol_test.sh --retest-only   # data already backfilled -> just the retests
set -euo pipefail

KEY="${ATS_KEY:-$HOME/.ssh/ats-key}"
HOST="${ATS_HOST:-ubuntu@43.205.112.232}"
DEST="${ATS_DEST:-ai-trading}"
FROM="${ATS_FROM:-2025-07-01}"
TO="${ATS_TO:-2026-06-20}"
SCRIP="https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
RUN="cd $DEST && sudo docker compose exec -T api python"

# High-beta / liquid mid-cap movers — where breakout alpha should live (vs mean-reverting
# mega-caps). Unresolvable tickers are skipped by the backfill; that's fine.
MOVERS="NSE:ADANIENT NSE:ADANIPORTS NSE:TATAMOTORS NSE:TATASTEEL NSE:JSWSTEEL NSE:HINDALCO NSE:VEDL NSE:BAJFINANCE NSE:INDUSINDBK NSE:SAIL NSE:NMDC NSE:BHEL NSE:ONGC NSE:COALINDIA NSE:IRFC NSE:PNB NSE:CANBK NSE:ASHOKLEY NSE:DLF NSE:RBLBANK NSE:IDFCFIRSTB NSE:FEDERALBNK NSE:DELHIVERY NSE:PERSISTENT NSE:COFORGE NSE:DIXON"

if [[ "${1:-}" != "--retest-only" ]]; then
  echo "=== 1/3  Backfill ${FROM}..${TO} 5m for the mover universe (throttled; ~10-20 min) ==="
  OUT=$(ssh -i "$KEY" "$HOST" "$RUN scripts/dhan_backfill.py --symbols $MOVERS --interval 5m --from $FROM --to $TO --scrip-master $SCRIP" 2>&1) || true
  echo "$OUT"
  # Fail LOUD on a broken fetch — never run the backtests (and print a verdict) on
  # incomplete data. A 401 = expired DHAN_ACCESS_TOKEN; 0 rows = nothing landed.
  if echo "$OUT" | grep -q "401 Client Error"; then
    echo
    echo "!! Dhan backfill returned 401 (auth): the DHAN_ACCESS_TOKEN in the server .env is"
    echo "   expired/invalid (this is the Dhan DATA token, separate from Kite). Regenerate it"
    echo "   in the Dhan developer portal, update .env, then re-run. You refresh it — no"
    echo "   script here touches credentials. Skipping the backtests (no verdict off bad data)."
    exit 1
  fi
  rows=$(echo "$OUT" | sed -n 's/^done: \([0-9][0-9]*\) candle rows upserted.*/\1/p' | tail -1)
  if [[ -z "${rows:-}" || "${rows:-0}" -eq 0 ]]; then
    echo
    echo "!! Backfill upserted 0 rows — not running the backtests on incomplete data."
    echo "   Check the Dhan token / Data API plan, then re-run."
    exit 1
  fi
  echo "[backfill ok] ${rows} candle rows upserted"
else
  echo "=== skipping backfill (--retest-only) ==="
fi

echo
echo "=== 2/3  Breakout on movers — PLAIN (no RVOL gate): is the universe alone enough? ==="
ssh -i "$KEY" "$HOST" "$RUN scripts/confluence_breakout.py --symbols $MOVERS --from $FROM --to $TO --k-values 4,5,6,7,8 --mode breakout"

echo
echo "=== 3/3  Breakout on movers — IN-PLAY (--min-rvol 3): does activity-gating help? ==="
ssh -i "$KEY" "$HOST" "$RUN scripts/confluence_breakout.py --symbols $MOVERS --from $FROM --to $TO --k-values 4,5,6,7,8 --mode breakout --min-rvol 3"

echo
echo "done. Verdict to read: net>0 in BOTH IS and OOS on the same K, win% lifting above"
echo "~33%, and DSR/PBO not flagging overfit. If still cost-killed -> equities are closed."
