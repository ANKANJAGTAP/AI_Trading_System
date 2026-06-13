# Using your Zerodha Kite Connect API

You already have the paid Kite Connect plan (₹500/mo, live + historical bundled).
This is how the platform uses it for all four jobs.

## 1. Install + credentials

```bash
pip install kiteconnect pyotp cryptography requests
cp .env.example .env          # then fill .env with YOUR values (never commit it)
```

Fill these in `.env` (the daily access token is minted for you in step 2, so you
don't set it by hand):

```
KITE_API_KEY=...           KITE_API_SECRET=...
KITE_USER_ID=...           KITE_PASSWORD=...
KITE_TOTP_SECRET=...       KITE_REDIRECT_URL=https://127.0.0.1
TOKEN_STORE_PATH=.secrets/kite_token.json
TOKEN_ENCRYPTION_KEY=      # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

Run everything from your whitelisted static IP (SEBI-2026).

## 2. Mint today's access token (run each morning, before pre-open)

The access token expires daily. This helper logs in with your env creds + TOTP,
encrypts the token, and stores it at `TOKEN_STORE_PATH`:

```bash
set -a; source .env; set +a          # load your .env into the environment
python -m dataplatform.kite_auth     # -> "Access token refreshed and stored ... "
```

Then build the adapter from the stored token (no token handling in your code):

```python
from dataplatform.vendors import KiteHistoricalAdapter
kite = KiteHistoricalAdapter.from_token_store()
kite.load_instruments(("NFO", "BFO"))
```

> The login flow uses Zerodha's web endpoints (which can change) — if the
> token mint fails, fall back to Kite's standard browser login + paste the
> `request_token`, then `save_token(...)`. Tip: automate the morning run with
> cron once it works.

## 3. Historical candles → research / backtesting

```python
from dataplatform.vendors import KiteHistoricalAdapter
from dataplatform.backfill import run_backfill
import datetime as dt

kite = KiteHistoricalAdapter.from_token_store()   # uses today's stored token
kite.load_instruments(("NFO", "BFO"))             # pulls the active-contract master once

# canonical EOD chain for the active expiries, ingested into the lake + store:
run_backfill(kite, dt.date(2026, 1, 1), dt.date.today())
```

`KiteHistoricalAdapter` resolves each option/future to its `instrument_token`
from Kite's instruments dump, fetches daily candles (OHLCV + OI) via
`historical_data`, and normalises to the canonical schema — so the feature/ML/
backtest pillars read it exactly like any other source. For deep intraday on one
instrument: `kite.historical_candles(token, start, end, "minute")`.

> **Active contracts only.** Kite's dump lists currently-active contracts, so
> this backfills the underlying/futures deep history and the *current* expiries'
> option chains — not years of *expired* weeklies. For long options history,
> capture forward (below) or use a bulk vendor; the schema is identical so
> nothing downstream changes.

## 4. Live ticks → forward capture (history compounds)

```python
kws = kite.ticker()                 # configured KiteTicker
# attach on_ticks/on_connect callbacks that persist ticks via the ingestion
# layer, then kws.connect(). Each captured day becomes tomorrow's history.
```

## 5. Orders & account

Read-only account state:

```python
kite.positions(); kite.holdings(); kite.margins()
```

Turn an accepted signal into Kite orders (build-only — it never fires them):

```python
from fno_signals import to_kite_orders, place_orders

orders = to_kite_orders(decision, expiry, kite.instruments)   # list of order dicts
# Review them. Placing is your explicit, irreversible step:
# place_orders(kite._client(), orders, confirm=True)   # guarded; needs confirm=True
```

`place_orders` refuses to run without `confirm=True` by design — execution must
be a deliberate, reviewed action with the SEBI-2026 controls (Algo-ID, static
IP, OPS limits) in place. Keep a human in the loop until the `upgrade.md` live
P0s are closed.
