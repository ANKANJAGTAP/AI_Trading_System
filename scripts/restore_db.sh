#!/usr/bin/env bash
# #35 Restore a TimescaleDB backup produced by backup_db.sh. Run ON THE SERVER.
#
#   ./scripts/restore_db.sh ~/ats-backups/ats-20260617-010000.sql.gz
#
# Restore drill (do this periodically — a backup you've never restored isn't a
# backup): restore into a scratch DB and sanity-check, rather than over the live
# one. See RUNBOOK.md "Backup & restore".
set -euo pipefail

FILE="${1:?usage: restore_db.sh <backup.sql.gz> [target_db]}"
DB="${2:-${POSTGRES_DB:-ats}}"
USER="${POSTGRES_USER:-ats}"
[ -f "$FILE" ] || { echo "no such file: $FILE" >&2; exit 1; }

cd "$(dirname "$0")/.."
echo "[restore] restoring $FILE -> database '$DB' ..."
gunzip -c "$FILE" | sudo docker compose exec -T timescaledb psql -U "$USER" "$DB"
echo "[restore] done."
