#!/usr/bin/env bash
# Daily Kite forward-capture — refresh token, pull the last 2 days' chains into
# the lake. Runs unattended after market close so history compounds over time.
#
# One-time setup on the server:
#   chmod +x ~/dataplatform/daily_capture.sh
#   crontab -e        # add the line below, then save:
#   0 13 * * 1-5  /home/ubuntu/dataplatform/daily_capture.sh
#   (13:00 UTC = 18:30 IST; Mon-Fri, after the 15:30 IST close.)
#
# Watch it:  tail -f ~/capture.log
set -uo pipefail
H="/home/ubuntu"
LOG="$H/capture.log"

cd "$H"
source "$H/atsvenv/bin/activate"
set -a; source "$H/ai-trading/.env"; set +a

# Route writes to the SHARED TimescaleDB (the same DB the live app uses) by setting
# TIMESCALE_DSN in ~/ai-trading/.env. From the HOST, reach the container's published
# port (docker-compose maps 5544:5432):
#   TIMESCALE_DSN=postgresql://ats:ats@localhost:5544/ats
# If unset, ingestion still writes the Parquet lake and mirrors EOD to local SQLite.

echo "===== $(date -u) forward-capture start =====" >> "$LOG"

# Try to mint a fresh access token (auto-login + TOTP). If Zerodha blocks the
# programmatic login, the existing token is used; if that's stale the pull just
# logs empty rows and you re-mint manually:  python -m dataplatform.kite_auth --manual
python -m dataplatform.kite_auth >> "$LOG" 2>&1 \
  || echo "$(date -u) token auto-refresh FAILED — run 'python -m dataplatform.kite_auth --manual'" >> "$LOG"

# Pull the last 2 sessions into the lake + operational store (idempotent upsert).
# Writes to TimescaleDB when TIMESCALE_DSN is set, else the local SQLite mirror.
python -u -m dataplatform.ingestion.daily --source kite --days-back 2 >> "$LOG" 2>&1

echo "===== $(date -u) forward-capture done =====" >> "$LOG"
