#!/usr/bin/env bash
# #36 One-command deploy: sync source to the server and rebuild.
#
# Replaces ad-hoc `scp -r ... dashboard ...` which copied node_modules + .pyc and
# produced thousand-line transfer logs. rsync sends only changed source files and
# excludes junk. It NEVER touches the server's .env, .secrets, or data lake, so
# secrets/credentials on the server are safe.
#
# IMPORTANT: docker-compose.override.yml is LOCAL-ONLY (points the local stack at
# the AWS DB via an SSH tunnel). It must never reach the server — Compose would
# auto-merge it and repoint the server's api through a tunnel that only works from
# the Mac. It is excluded below, and the rebuild forces -f docker-compose.yml.
#
#   ./scripts/deploy.sh            # sync + rebuild api/engine/dashboard
#   ./scripts/deploy.sh --dry-run  # show what would transfer, change nothing
#
# Override target with env vars: ATS_HOST, ATS_KEY, ATS_DEST.
set -euo pipefail

HOST="${ATS_HOST:-ubuntu@43.205.112.232}"
KEY="${ATS_KEY:-$HOME/.ssh/ats-key}"
DEST="${ATS_DEST:-ai-trading}"
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

cd "$(dirname "$0")/.."   # repo root

echo "[deploy] syncing source -> ${HOST}:${DEST}/ ${DRY:+(dry run)}"
rsync -az ${DRY} \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='node_modules' --exclude='dist' --exclude='.venv' \
  --exclude='.pytest_cache' --exclude='.env' --exclude='.secrets' \
  --exclude='.DS_Store' --exclude='*.tsbuildinfo' \
  --exclude='docker-compose.override.yml' \
  -e "ssh -i ${KEY}" ./ "${HOST}:${DEST}/"

if [ -n "${DRY}" ]; then
  echo "[deploy] dry run complete — nothing changed."
  exit 0
fi

echo "[deploy] rebuilding api/engine/dashboard on the server ..."
# -f docker-compose.yml: ignore any stray override on the server (the override is
# local-only). --remove-orphans: drop a db-tunnel left by an earlier bad deploy.
ssh -i "${KEY}" "${HOST}" \
  "cd ${DEST} && sudo docker compose -f docker-compose.yml up -d --build --remove-orphans api engine dashboard"
echo "[deploy] done. Verify: ssh ${HOST} 'cd ${DEST} && sudo docker compose -f docker-compose.yml ps'"
