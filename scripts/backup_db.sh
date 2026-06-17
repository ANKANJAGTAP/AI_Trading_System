#!/usr/bin/env bash
# #35 TimescaleDB backup — timestamped, gzipped pg_dump with retention.
# Run ON THE SERVER (it talks to the compose `timescaledb` service). Schedule via
# cron, e.g.  0 1 * * *  cd ~/ai-trading && ./scripts/backup_db.sh >> ~/ats-backups/backup.log 2>&1
set -euo pipefail

DIR="${ATS_BACKUP_DIR:-$HOME/ats-backups}"
RETAIN_DAYS="${ATS_BACKUP_RETAIN_DAYS:-14}"
DB="${POSTGRES_DB:-ats}"
USER="${POSTGRES_USER:-ats}"
mkdir -p "$DIR"
ts=$(date +%Y%m%d-%H%M%S)
out="$DIR/ats-${ts}.sql.gz"

cd "$(dirname "$0")/.."
sudo docker compose exec -T timescaledb pg_dump -U "$USER" "$DB" | gzip > "$out"
find "$DIR" -name 'ats-*.sql.gz' -mtime +"$RETAIN_DAYS" -delete
echo "[backup] wrote $out ($(du -h "$out" | cut -f1)); retention ${RETAIN_DAYS}d"
