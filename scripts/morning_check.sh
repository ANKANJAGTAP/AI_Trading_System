#!/usr/bin/env bash
# Morning paper-trading check — run from the Mac on a trading day.
# READ-ONLY: broker-token/feed health, then readiness + paper P&L. Places no orders,
# changes no state. This is the only routine you run daily; see RUNBOOK.md
# "Daily paper operation". Override target with ATS_HOST / ATS_KEY / ATS_DEST.
#
#   ./scripts/morning_check.sh
set -euo pipefail

KEY="${ATS_KEY:-$HOME/.ssh/ats-key}"
HOST="${ATS_HOST:-ubuntu@43.205.112.232}"
DEST="${ATS_DEST:-ai-trading}"
RUN="cd $DEST && sudo docker compose exec -T api python"

echo "=== 1/2  Broker token / feed health — every endpoint should read [OK] ==="
if ! ssh -i "$KEY" "$HOST" "$RUN scripts/diag_kite_endpoints.py"; then
  echo
  echo "!! token/feed check failed — refresh the Kite token in the server .env yourself,"
  echo "   then re-run this script. (No script here touches the token.)"
  exit 1
fi

echo
echo "=== 2/2  Readiness + paper P&L  (orchestrator_enabled flips True after 09:15;"
echo "         kill_switch_active must be False) ==="
ssh -i "$KEY" "$HOST" "$RUN scripts/pnl_report.py"

echo
echo "done — re-run any time during the session (after 09:25 IST) to watch open"
echo "structures accrue unrealized MTM."
