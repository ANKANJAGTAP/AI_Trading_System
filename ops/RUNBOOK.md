# Operations Runbook

> Phase 0 stub. Expanded into the full ops runbook in Phase 7 (Go-Live).

## Daily startup
1. Confirm the VPS is up and `ai-trading.service` is active: `systemctl status ai-trading`.
2. Token refresh runs automatically at `system.token_refresh_time` (default 08:00 IST).
   Verify in logs: look for `scheduled_token_refresh_ok` / `token_refreshed`.
3. Check `/health` returns `status: ok` (db + redis true).
4. Confirm mode indicator: must read **SIMULATED** until the operator deliberately flips to live.

## Daily shutdown
- The engine is always-on. To halt: `docker compose stop engine` (positions are managed
  per the fail-safe handler in later phases). Do not kill -9 during market hours.

## Token-refresh verification
- Manual refresh check: `docker compose run --rm engine migrate` is NOT a token op;
  to force a login test run the Phase 0 verifier: `python scripts/verify_phase0.py`.
- On auth failure the operator receives an email alert ("Kite auth FAILED").

## Disaster recovery (cold start)
- The broker is the source of truth. On restart, the engine adopts open positions and
  pending orders from Kite and re-arms guards (Phase 3). Until then, verify no live
  exposure before restarting in `live` mode.

## Database backup
- Postgres/TimescaleDB data lives in the `tsdb_data` volume.
- Backup: `docker compose exec timescaledb pg_dump -U ats ats | gzip > backup_$(date +%F).sql.gz`

## Restart procedure
- `systemctl restart ai-trading` (systemd) or `docker compose restart`.
- Restart policy is `unless-stopped` / `always` so crashes self-heal.
