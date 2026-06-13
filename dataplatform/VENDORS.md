# Wiring a paid data vendor (TrueData / Global Datafeeds)

The bhavcopy adapters give a free EOD spine; for **deep 1-min / intraday options
history** you need a paid vendor. This is how to plug one in. Credentials are
read from **environment variables only** — never put keys in the repo.

## 1. Install the vendor SDK

```bash
pip install truedata           # for TrueData
# Global Datafeeds uses a REST API (no SDK needed; uses urllib)
```

## 2. Set credentials (env vars)

```bash
# TrueData
export TRUEDATA_USERNAME="your_login"
export TRUEDATA_PASSWORD="your_password"

# Global Datafeeds
export GDFL_API_KEY="your_api_key"
# optional: export GDFL_ENDPOINT="https://history.globaldatafeeds.in/api/Data/HistoryData"
```

## 3. Verify the symbology

Vendor option/future symbols depend on your subscription's symbol master. The
defaults in `truedata_symbol` / `gdfl_symbol` (e.g. `NIFTY24JUL18000CE`,
`NIFTY24JULFUT`) are **best guesses flagged for verification**. Confirm against
your vendor's symbol list; if different, pass your own builder:

```python
from dataplatform.vendors import TrueDataAdapter

def my_symbol(underlying, expiry, strike=None, opt_type=None):
    ...   # build the exact symbol your TrueData plan expects
    return symbol

adapter = TrueDataAdapter(symbol_format=my_symbol, n_strikes=20, step=50.0)
assert adapter.available()        # True once env creds are set
```

## 4. Backfill history into the lake + operational store

```python
import datetime as dt
from dataplatform.vendors import TrueDataAdapter
from dataplatform.backfill import run_backfill

run = run_backfill(TrueDataAdapter(), dt.date(2018, 1, 1), dt.date(2026, 5, 31))
print(run.total_rows, "rows ·", "manifest:", run.manifest_path)
print("quarantined days:", run.quarantined_days)
```

`run_backfill` drives the same EOD ingestion pipeline used everywhere else:
each day is fetched, **quality-checked**, written to the Parquet lake +
operational store, and recorded in a reproducibility manifest. The option
universe per day is built from the **Pillar-1 expiry engine**, so it
automatically respects the real rules (front weekly + monthly; FinNifty
monthly-only).

## 5. Point the rest of the platform at real data

Once backfilled, the feature engine, ML/CPCV validation, backtester and the
end-to-end demo all read from the same lake — swap `SyntheticEODAdapter` for the
lake reader and the numbers start to mean something. Start with a recent slice
to validate symbology before committing to a 15–20-year pull.

> Exchange data is licensed — keep raw vendor files private and within your
> vendor's terms of use.
