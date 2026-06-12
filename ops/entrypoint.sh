#!/usr/bin/env bash
# Container entrypoint: wait for Postgres, run migrations, then dispatch.
#   api     -> uvicorn FastAPI control plane
#   engine  -> asyncio engine process
#   migrate -> run migrations and exit
set -euo pipefail

PGHOST="${POSTGRES_HOST:-timescaledb}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-ats}"

echo "[entrypoint] waiting for postgres at ${PGHOST}:${PGPORT} ..."
until pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" >/dev/null 2>&1; do
  sleep 1
done
echo "[entrypoint] postgres is up"

cmd="${1:-api}"

if [ "${cmd}" = "migrate" ]; then
  exec python scripts/migrate.py
fi

echo "[entrypoint] applying migrations ..."
python scripts/migrate.py

case "${cmd}" in
  api)
    exec uvicorn api.app:app --host 0.0.0.0 --port 8000
    ;;
  engine)
    exec python -m engine.main
    ;;
  *)
    exec "$@"
    ;;
esac
