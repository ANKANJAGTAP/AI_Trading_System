# dataplatform — Phase 0 + Pillar 1

The **point-in-time data foundation** for the world-class F&O platform (see
`../WORLDCLASS_FNO_PLATFORM_PLAN.md`). This is the layer everything else —
features, ML, backtester, signals — depends on. Focus: **NIFTY, FINNIFTY,
SENSEX** index derivatives.

It runs **offline with zero infrastructure** (synthetic data + SQLite + a local
Parquet lake), and swaps to real sources (NSE/BSE bhavcopy, Kite, paid vendors)
and TimescaleDB by configuration only.

## Why this exists (the one idea that matters)

Indian index-derivative rules — weekly availability, expiry weekdays, lot sizes,
fees — have changed repeatedly (e.g. **FinNifty weekly options were
discontinued in late 2024**; expiry weekdays shifted several times in 2025–26).
Hard-coding any of it silently corrupts a 15–20-year backtest. So everything is
**effective-dated reference data resolved *as of* the simulated date**. A rule
change is a *data edit*, never a code change.

## Layout

```
dataplatform/
├── config.py            # settings (paths, DB DSN, universe) — env-overridable
├── marketcalendar/      # trading-day/holiday utils + point-in-time EXPIRY ENGINE
├── contracts/           # effective-dated contract-spec resolver (lot/tick/weekly)
├── vendors/             # pluggable adapters: bhavcopy NSE/BSE, Kite, synthetic
├── storage/             # Parquet research lake (DuckDB) + operational store
│   └── schema.sql       # TimescaleDB DDL (SQLite fallback for dev)
├── quality/             # data-quality checks (quarantine, don't drop)
├── ingestion/           # EOD pipeline: fetch → quality → store → manifest
├── cli.py               # python -m dataplatform.cli ...
└── tests/               # 27 tests, all offline
```

## Quick start (offline, no setup)

```bash
pip install -r dataplatform/requirements.txt
PYTHONPATH=. python -m pytest                       # 27 passed

# ingest synthetic EOD data end-to-end (writes lake + SQLite + manifest)
PYTHONPATH=. python -m dataplatform.cli ingest --source synthetic \
    --start 2026-06-01 --end 2026-06-05

# list reference data that still needs verification against official circulars
PYTHONPATH=. python -m dataplatform.cli setup-report

# compute weekly + monthly expiries for any range (point-in-time rules)
PYTHONPATH=. python -m dataplatform.cli expiries --underlying NIFTY \
    --start 2026-06-01 --end 2026-07-31
```

In code:

```python
import datetime as dt
from dataplatform.marketcalendar import ExpiryResolver
from dataplatform.contracts import ContractSpecResolver

er, sr = ExpiryResolver(), ContractSpecResolver()
er.current_monthly_expiry("NIFTY", dt.date(2026, 6, 10))   # adjusted for holidays
er.has_weekly("FINNIFTY", dt.date(2025, 6, 1))             # -> False (discontinued 2024-11-19)
sr.lot_size("NIFTY", dt.date(2024, 1, 15))                 # -> 25 (verified)
sr.lot_size("NIFTY", dt.date(2025, 6, 15))                 # -> 75 (verified)
sr.lot_size("NIFTY", dt.date(2026, 6, 15))                 # -> 65 (verified, current)
```

## Using real data

**Free EOD spine (recommended first):**

```python
from dataplatform.vendors import NSEBhavcopyAdapter, BSEBhavcopyAdapter
from dataplatform.ingestion import EODIngestionPipeline

EODIngestionPipeline(NSEBhavcopyAdapter()).ingest_range(start, end)  # NIFTY, FINNIFTY
EODIngestionPipeline(BSEBhavcopyAdapter()).ingest_range(start, end)  # SENSEX
```

The bhavcopy parsers handle both NSE's **UDiFF** common bhavcopy and the
**legacy** format. For live runs, ensure network access and warm NSE cookies
(GET `https://www.nseindia.com` first). Verify the current BSE bhavcopy URL.

**Kite** is for live + *recent* candles (not deep option chains):
`KiteAdapter(api_key, access_token).historical_candles(token, start, end)`.

**DhanHQ** is the primary vendor: `dhan.py` (historical daily + intraday OHLC,
free) and `dhan_chain.py` (live option chain with real greeks/IV/OI/bid-ask, Data
API plan). **Global Datafeeds** remains as an alternate paid chain adapter. Adding
another vendor is just an adapter subclassing `vendors.base.VendorAdapter` (or
`bar_vendor.BarVendorAdapter`) returning the canonical schema — nothing else changes.

## Storage backends

| | Dev (default) | Production |
|---|---|---|
| Operational store | SQLite (`~/.aitrading_data/operational.db`) | TimescaleDB (set `TIMESCALE_DSN`, run `storage/schema.sql`) |
| Research lake | Parquet + DuckDB (local) | Parquet on object storage / ClickHouse |

Set `DATAPLATFORM_HOME` to control where data lives.

## Seed reference data — status

**NSE values are verified** (`verify=False`) against public circulars/reporting:

- Nifty lot: **25 → 75** (eff 2024-11-20) **→ 65** (eff 2025-12-31, current).
- FinNifty lot: 40 → 65 → **60** (current); **weekly discontinued** (last weekly 2024-11-19).
- Expiry-day **swap eff 2025-09-01**: Nifty (NSE) weekly+monthly now **Tuesday**;
  Sensex (BSE) now **Thursday**. (Both were Thursday/earlier before the swap.)

**Still flagged `verify=True`** (confirm against BSE / NSE circulars):

- SENSEX lot sizes (BSE-specific; best estimates).
- FinNifty *monthly* weekday after weekly discontinuation, and the Sensex
  Friday→Tuesday interim boundary.

Run `python -m dataplatform.cli setup-report` to list everything still pending.
The *mechanism* (point-in-time resolution, holiday roll-back, last-<weekday>
monthly) is exact and tested regardless of the literal values.

## What's next (per the plan)

This package is Phase 0 + the Pillar-1 foundation. Next: paid 1-min vendor
backfill, then **Pillar 2** (the `features/` library) computing TA + options
analytics over this data with train/serve parity, then **Pillar 3** (labelling +
CPCV/DSR/PBO validation) and **Pillar 4** (the options-aware backtester).
