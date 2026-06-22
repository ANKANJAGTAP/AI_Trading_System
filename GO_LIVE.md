# Go-Live Walkthrough

The definitive, ordered procedure to take this platform from **paper on AWS** to
**transacting real capital** — safely. Every step is yours to run on your own
machines; the assistant never enters credentials, places orders, or moves money.

> Not legal/financial advice. Validate your SEBI/broker obligations before live capital.
> Live trading is fail-closed: the flip in Step 7 is *blocked* until Steps 1–6 pass.

Conventions: server = `ubuntu@43.205.112.232`, stack under `~/ai-trading`. Run server
commands from that directory. `$API=http://127.0.0.1:8000`, `$TOKEN` = your admin API
token from `.env` (`grep -E 'API_AUTH_TOKEN|API_TOKEN_ADMIN' .env`).

---

## Step 0 — Preconditions

- The platform has run in **paper mode** long enough to trust the plumbing (signals,
  fills, reconciliation, kill-switch, daily digest all behaving).
- You accept that a controlled live start risks real money. Start tiny.

## Step 1 — Rotate the previously-exposed secrets *(do first; one-time)*

The Kite key/secret and DB password were in plaintext earlier — rotate at the source:

- **Kite:** regenerate the API secret in the Kite developer console.
- **DB:** `ALTER USER ats WITH PASSWORD '<new>';` then update `POSTGRES_PASSWORD` /
  `TIMESCALE_DSN` in `~/ai-trading/.env`.
- Set `TOKEN_ENCRYPTION_KEY` (Fernet), `REDIS_PASSWORD`, and the scoped API tokens
  (`API_TOKEN_READONLY/OPERATOR/TRADER/ADMIN`). Then `sudo docker compose up -d`.

## Step 2 — Validate the adapter read path *(read-only, any time)*

```bash
sudo docker compose exec api python scripts/verify_broker_adapter.py
```
Expect `[PASS]` on margins / positions / holdings / ltp / orders. A `[FAIL]` here is an
account / subscription / token issue, not code.

## Step 3 — Validate the order → fill → book path *(you place a tiny order)*

Place a **1-lot** order yourself in the Kite app (or a tiny LIMIT far from market you
then cancel). Copy its order_id, then:

```bash
sudo docker compose exec api python scripts/verify_broker_adapter.py 250622XXXXXXXXX
```
The printed `reduce → normalize → close_books_fully` verdict must match what you see in
Kite (COMPLETE+full → books; partial/cancelled → does NOT book). This proves the live
fill-truth path matches the contract the test-suite pins.

## Step 4 — Confirm the live market-data feed *(during market hours, 09:15–15:30 IST)*

```bash
sudo docker compose logs --tail=50 engine | grep feed_     # expect feed_connected, then feed_health idle≈0
sudo docker compose exec redis redis-cli hgetall md:ltp | head   # live prices flowing
```
If it logs `feed_noreconnect` or stays idle in-session, the daily Kite token is stale —
re-run the login so `ensure_token` has today's token; the watchdog reconnects.

## Step 5 — Pre-live checklist must be ALL-PASS

```bash
curl -s $API/api/prelive-checklist -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
`overall` must be `pass`. Resolve any `fail`: set `compliance.algo_id`,
`compliance.static_ip`, `exchange_registered` in `config/system.yaml`; whitelist the
static IP at Kite; reset the kill-switch; ensure no stale open positions.

## Step 6 — Operational readiness tiles

```bash
curl -s $API/api/readiness -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
Pending commands `ok`, open positions known, unsafe-entry block clear, feed live,
backup verified. Also confirm a fresh backup + restore drill (RUNBOOK).

## Step 7 — The flip (start tiny)

Only after 1–6 are green. ADMIN scope + confirm token; the transition service re-runs
the pre-live gate and refuses if anything regressed.

```bash
curl -XPOST $API/api/controls/mode -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"mode":"live","confirm_token":"<token>"}'
```
Start with **one index, one strategy, minimum size**. Scale only on evidence.

## Step 8 — First-trade monitoring + instant rollback

Watch `logs -f engine`, the Positions/Risk screens, and the reconciliation status.
Anything looks wrong — these are always available (exits are never blocked):

```bash
curl -XPOST $API/api/controls/flatten        -H "Authorization: Bearer $TOKEN" -d '{"confirm":true}'
curl -XPOST $API/api/controls/pause          -H "Authorization: Bearer $TOKEN" -d '{"paused":true}'
curl -XPOST $API/api/controls/mode           -H "Authorization: Bearer $TOKEN" -d '{"mode":"simulated_fill"}'  # back to paper
```

---

## Safety rules (always)

- The assistant never enters credentials, places/cancels orders, or moves money — every
  irreversible action in this doc is yours.
- Exits, cancels, flatten, and the kill-switch are always permitted, even under a halt.
- Keep position sizes small until the live edge is demonstrated on real fills — a good
  paper Sharpe is necessary, not sufficient.
