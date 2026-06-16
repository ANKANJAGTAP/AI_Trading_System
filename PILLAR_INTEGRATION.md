# Pillar Integration — Deploy Runbook

How the 5 research pillars (`dataplatform`, `features`, `ml`, `fno_backtest`,
`fno_signals`) are wired into the live system, and how to deploy it.

## What was integrated (and what was deliberately *not*)

The live app is already mature: it has its own defined-risk F&O pipeline
(`strategies/fno.py`), a López-de-Prado purged-CV meta-labeler (`research/`),
drawdown circuits, and a paper/live mode switch. The new pillars overlap with
some of that, so they were wired **where they are additive, not duplicative**:

1. **Shared data layer (Pillar 1).** `eod_fno` (+ `option_snapshot`,
   `candles_1m`, `contract_spec`, `expiry_calendar`, `market_holidays`) now live
   in the app's TimescaleDB (`migrations/sql/0013_dataplatform.sql`). The
   data platform writes the curated point-in-time F&O lake + this shared DB, so
   research/backtest/ML and the live app share **one** data layer.

2. **Research API over the lake** (`api/fno_lake.py`, routes in `api/routes.py`):
   - `GET /api/fno/lake` — coverage per underlying
   - `GET /api/fno/analytics` — per-day PCR / ATM-IV / net-GEX / max-pain / skew
   - `GET /api/fno/features` — point-in-time TA + options feature matrix
   - `GET /api/fno/backtest` — `fno_signals` decisions over the `fno_backtest`
     engine on the lake (defined-risk only, bias-audited). This is where
     `features` + `ml` + `fno_signals` + `fno_backtest` actually run on real data.
   All read-only; none touch the trading/broker path.

3. **Verified reference data** (earlier commit): the effective-dated expiry/lot
   seed was audited and corrected (FinNifty monthly = Tuesday; pre-2023 Sensex
   monthly = Thursday; Sensex lots 10→20). The backtester uses `lot_size=65` for
   NIFTY straight from this seed.

**Deliberately NOT done — `fno_signals` in the live tick loop.** The live
`build_fno_context` only fetches the ATM CE/PE quotes; `fno_signals.decide()`
needs a full option-chain DataFrame. Forcing it into the live loop would mean a
costly live chain-fetch to duplicate a pipeline the engine already has. So
`fno_signals` runs in its natural habitat — the research/backtest layer on the
point-in-time lake — not as a redundant second live engine. (A flag-gated live
*shadow* can be added later if you want a side-by-side on live data.)

## Deploy

All commands run in your **app directory on the server** (where `docker-compose.yml`
and `.env` live, e.g. `~/ai-trading`), unless marked **(Mac)** or **(host venv)**.

```bash
# 1. (Mac) push the integration commits
cd ~/Downloads/"Algo Trading Platform" && git push

# 2. (server) get the new code into the build context
cd ~/ai-trading && git pull        # or scp the changed files if not a git clone

# 3. (server) let the host cron write the SHARED TimescaleDB: add to ~/ai-trading/.env
echo 'TIMESCALE_DSN=postgresql://ats:ats@localhost:5544/ats' >> ~/ai-trading/.env

# 4. (server) rebuild + restart api & engine — the entrypoint auto-applies
#    migration 0013 on startup; the host lake is bind-mounted into both.
docker compose up -d --build api engine

# 5. (host venv) one-off backfill into the lake + shared DB (isolated host token)
cd ~ && source ~/atsvenv/bin/activate
set -a; source ~/ai-trading/.env; set +a
python -m dataplatform.ingestion.daily --source kite --days-back 60
```

The daily host cron (`dataplatform/daily_capture.sh`) keeps compounding history
forward from there. The in-engine ingest job stays **off** by default
(`system.dataplatform.enabled: false`) because minting a Kite token inside the
live engine would share the app's token file — the host cron is the safe primary.

## Verify

```bash
# migration applied + table present
docker compose exec timescaledb psql -U ats -d ats -c "\dt eod_fno" \
  -c "SELECT count(*) FROM eod_fno;"

# research API (add  -H "Authorization: Bearer $API_AUTH_TOKEN"  if it's set)
curl -s localhost:8000/api/fno/lake | python3 -m json.tool
curl -s "localhost:8000/api/fno/analytics?underlying=NIFTY&start=2026-04-01" | python3 -m json.tool
curl -s "localhost:8000/api/fno/backtest?underlying=NIFTY&start=2026-01-01" | python3 -m json.tool
```

`/api/fno/analytics` is meaningful immediately; `/api/fno/features` and
`/api/fno/backtest` need ~20+ trading days of lake history before TA/labels fill
in (they return a "need more history" note until then).

## Rollback

```bash
cd ~/ai-trading && git revert --no-edit <commit-range> && docker compose up -d --build api engine
```

Migration 0013 only *adds* tables (and skips the app's existing `iv_history`), so
it is safe to leave in place even on rollback.
