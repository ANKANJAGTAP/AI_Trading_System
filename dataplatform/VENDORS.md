# Wiring a data vendor (DhanHQ / Global Datafeeds)

The bhavcopy adapters give a free EOD spine. For **intraday/minute bars** and
**option chains with greeks**, the platform uses **DhanHQ**; **Global Datafeeds**
remains as an alternate paid option-chain vendor. Credentials are read from
**environment variables only** — never put keys in the repo.

## DhanHQ (primary)

No SDK to install — the adapters use `requests`. Set creds in `.env`:

```bash
export DHAN_CLIENT_ID="your_dhan_id"
export DHAN_ACCESS_TOKEN="your_jwt"        # from the Dhan developer portal
```

### Historical bars (free)

`dataplatform/vendors/dhan.py` pulls daily history (to inception) + 1/5/15/30/60-min
intraday (~5 yrs). Backfill the minute data the bhavcopy lake lacks:

```bash
python scripts/dhan_backfill.py \
  --symbols NSE:RELIANCE NSE:TCS NSE:INFY --interval 5m \
  --from 2025-01-01 --to 2026-06-22 \
  --scrip-master https://images.dhan.co/api-data/api-scrip-master-detailed.csv
```

Long ranges auto-chunk (`--chunk-days`) and throttle (`--sleep`) to stay under Dhan's
per-call range + rate caps. `--scrip-master` maps each tradingsymbol → Dhan
`securityId`; for one symbol use `--security-id`.

### Option chain — real greeks (Data API plan)

`dataplatform/vendors/dhan_chain.py` wraps Dhan's **live** `/optionchain` (per-strike
CE/PE legs with delta/theta/gamma/vega, IV, OI, volume, LTP, best bid/ask) and
`/optionchain/expirylist`. It's a snapshot, so it forward-records the chain:

```bash
python scripts/dhan_chain_snapshot.py --underlyings NIFTY FINNIFTY SENSEX --expiries 2
```

Writes greeks/IV/OI/bid-ask per leg to a timestamped CSV under `data/option_chains/`;
`--lake` also pushes canonical EOD rows through the ingestion pipeline. Dhan caps the
chain to **one request / 3 s** — the script throttles. Index security ids default to
Dhan's annexure (override with `--scrip NIFTY=13:IDX_I`). The chain needs the paid Data
API (a `DH-806` / `DH-902` error means it isn't subscribed on the token).

Programmatic use:

```python
import datetime as dt
from dataplatform.vendors import DhanChainAdapter

ad = DhanChainAdapter(underlyings=("NIFTY",))
assert ad.available()                       # True once env creds are set
rows = ad.fetch_chain_rows("NIFTY")         # nearest expiry, full greeks per leg
df = ad.fetch_eod_fno(dt.date.today())      # canonical EOD frame for the lake
```

## Global Datafeeds (alternate paid chain)

REST API (no SDK). Set `GDFL_API_KEY` (optional `GDFL_ENDPOINT`). The symbology
defaults in `gdfl_symbol` (e.g. `NIFTY24JUL18000CE`) are best guesses **flagged for
verification** — confirm against your GDFL symbol master and pass a custom builder if
they differ:

```python
from dataplatform.vendors import GlobalDatafeedsAdapter
adapter = GlobalDatafeedsAdapter(n_strikes=20, step=50.0)
assert adapter.available()                  # True once GDFL_API_KEY is set
```

## Backfilling history into the lake

```python
import datetime as dt
from dataplatform.vendors import DhanChainAdapter
from dataplatform.backfill import run_backfill

run = run_backfill(DhanChainAdapter(), dt.date.today(), dt.date.today())
print(run.total_rows, "rows ·", "manifest:", run.manifest_path)
```

`run_backfill` drives the same EOD ingestion pipeline used everywhere else: each day
is fetched, **quality-checked**, written to the Parquet lake + operational store, and
recorded in a reproducibility manifest. The option universe per day is built from the
**Pillar-1 expiry engine**, so it respects the real expiry rules (front weekly +
monthly; FinNifty monthly-only).

## Point the rest of the platform at real data

Once backfilled, the feature engine, ML/CPCV validation, backtester and the
end-to-end demo all read from the same lake — swap `SyntheticEODAdapter` for the lake
reader and the numbers start to mean something. Start with a recent slice to validate
symbology/securityids before committing to a long pull.

> Exchange data is licensed — keep raw vendor files private and within your vendor's
> terms of use.
