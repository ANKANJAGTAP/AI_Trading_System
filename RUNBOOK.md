# Operations Runbook

Operational procedures for the live AWS deployment (`ubuntu@43.205.112.232`,
stack under `~/ai-trading`). Two machines: you run `git`/`deploy` from the **Mac**;
`docker compose` runs on the **server**. The system trades **paper** mode today;
the live path is gated (see Go-live).

---

## Deploy

From the Mac (syncs source, excludes junk, never touches server `.env`/`.secrets`):

```bash
cd ~/Downloads/"Algo Trading Platform"
git add -A && git commit -m "..." && git push   # source of truth
./scripts/deploy.sh                              # rsync + rebuild on the server
./scripts/deploy.sh --dry-run                    # preview the file transfer only
```

Migrations auto-apply on container start (`ops/entrypoint.sh` → `scripts/migrate.py`,
under `set -euo pipefail`). **api reaching Healthy = migrations applied + app imports cleanly.**
Verify: `ssh -i ~/.ssh/ats-key ubuntu@43.205.112.232 'cd ai-trading && sudo docker compose ps'`.

## Rollback

No image registry yet, so roll back by source + rebuild:

```bash
cd ~/Downloads/"Algo Trading Platform"
git log --oneline -10          # find the last-good commit
git checkout <good-sha> -- .   # or: git revert <bad-sha>
./scripts/deploy.sh
```
Migrations are forward-only — a rollback of code does **not** roll back schema. If a
migration is the problem, fix forward with a new migration rather than reverting `0022`+.

## Backup & restore

On the server. Schedule the backup via cron (`0 1 * * *`):

```bash
cd ~/ai-trading
./scripts/backup_db.sh                                   # -> ~/ats-backups/ats-<ts>.sql.gz (14-day retention)
./scripts/restore_db.sh ~/ats-backups/ats-<ts>.sql.gz    # restore into the live DB
```

**Restore drill** (do periodically — an untested backup isn't a backup): restore into a
scratch DB and sanity-check instead of over the live one:

```bash
sudo docker compose exec timescaledb psql -U ats -c "CREATE DATABASE ats_restore_test;"
./scripts/restore_db.sh ~/ats-backups/ats-<ts>.sql.gz ats_restore_test
sudo docker compose exec timescaledb psql -U ats -d ats_restore_test -c "\dt" | head
sudo docker compose exec timescaledb psql -U ats -c "DROP DATABASE ats_restore_test;"
```

## Kill switch / pause (stop trading now)

Kill-switch is global and survives restart (`config_state.kill_switch_active`). Exits/cancels
are always allowed; only new entries are blocked (P1#14).

```bash
# Flatten everything (TRADER scope), then it stays flat while kill-switch is active:
curl -XPOST $API/api/controls/flatten   -H "Authorization: Bearer $TOKEN" -d '{"confirm":"<token>"}'
curl -XPOST $API/api/controls/pause     -H "Authorization: Bearer $TOKEN" -d '{"paused":true}'
# Reset the kill switch once safe (ADMIN scope):
curl -XPOST $API/api/controls/killswitch/reset -H "Authorization: Bearer $TOKEN" -d '{"confirm":"<token>"}'
```
Or use the dashboard Controls / Risk screens.

## Health & triage

- `GET /health` → `{status, db, redis, mode}`; engine liveness is the `aegis:engine:liveness` beacon (P1#13), surfaced as ok/degraded/down.
- Containers: `sudo docker compose ps` / `logs -f api` / `logs -f engine`.
- Broker vs book divergence: the reconciliation loop (P1#11) grades + persists mismatches and blocks/alerts; check the Pre-Live Readiness screen.

## Secret rotation

Secrets live in the server `~/ai-trading/.env` (gitignored, never deployed over). Rotate:

- **Kite key/secret/TOTP:** rotate in the Kite developer console → update `.env` → `docker compose up -d api engine`.
- **DB password:** changing `.env` alone breaks the connection (the volume keeps the old password). Rotate in-place:
  ```sql
  -- sudo docker compose exec timescaledb psql -U ats
  ALTER USER ats WITH PASSWORD '<new>';
  ```
  then set `POSTGRES_PASSWORD` (and `TIMESCALE_DSN`) in `.env` to match → restart api/engine.
- **Redis:** set `REDIS_PASSWORD` in `.env` → `docker compose up -d` (volume persists; opt-in auth, #22).
- **Token encryption:** set `TOKEN_ENCRYPTION_KEY` (Fernet) so the broker token is encrypted at rest; the pre-live `token_security` probe (#21) then passes outside dev.
- **API tokens:** set `API_TOKEN_READONLY/OPERATOR/TRADER/ADMIN` (#19) and distribute per role; the legacy single `API_AUTH_TOKEN` acts as admin.

## Broker adapter validation (the live gate)

Before the go-live flip, prove the real Kite adapter places, polls, and reports orders
the way the contract test-suite assumes. **All read-only — you place any test order
yourself in Kite; no script here initiates a trade.**

1. **Connectivity + permissions:** `python scripts/diag_kite_endpoints.py` — profile,
   ltp, margins, positions, holdings, orders should all print `[OK]`. A `[FAIL]` here is
   an account / subscription / permission issue, not a code one.
2. **Adapter read path:** `python scripts/verify_broker_adapter.py` — confirms the
   adapter wrapper (not just raw Kite) returns usable margins/positions/quotes/orders.
3. **Live order → fill → book path:** place a **1-lot** order in the Kite app (or a tiny
   LIMIT far from the market that you then cancel). Copy its order_id and run
   `python scripts/verify_broker_adapter.py <ORDER_ID>`. The printed
   `reduce → normalize → close_books_fully` verdict must match what you see in Kite
   (COMPLETE + full qty → books a close; partial / cancelled → does **not** book). This
   is the same pure reduction the executor uses and that `tests/test_broker_contract.py`
   pins, so a match means the live fill-truth path is trustworthy.
4. Only once 1–3 are green is the order path proven for the flip below.

## Go-live checklist (when ready — no rush; paper today)

Live trading is fail-closed and gated by the pre-live readiness check. Before flipping:

1. **Validate the real Kite adapter** — run the *Broker adapter validation* steps above until green. The adapter methods are thin Kite SDK pass-throughs; this proves they place/poll/report correctly live (and exercises the path the #28 streaming ticker will reuse).
2. Set `compliance.algo_id`, `compliance.static_ip`, `exchange_registered` in `config/system.yaml`; whitelist the static IP at Kite (SEBI-2026, P9).
3. Rotate the previously-leaked secrets; set `TOKEN_ENCRYPTION_KEY`, a real `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`.
4. Reset the kill switch; ensure no stale open positions.
5. `GET /api/prelive-checklist` must be **all-pass** (it blocks the flip otherwise).
6. Flip with `POST /api/controls/mode` (ADMIN scope + confirm token). Start tiny: one index, one strategy; scale only on evidence.

> Not legal/financial advice. Validate SEBI obligations with your broker before live capital.
