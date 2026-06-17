#!/usr/bin/env bash
# #36 One-command deploy: sync source to the server and rebuild.
#
# Replaces ad-hoc `scp -r ... dashboard ...` which copied node_modules + .pyc and
# produced thousand-line transfer logs. rsync sends only changed source files and
# excludes junk. It NEVER touches the server's .env, .secrets, or data lake, so
# secrets/credentials on the server are safe.
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
  -e "ssh -i ${KEY}" ./ "${HOST}:${DEST}/"

if [ -n "${DRY}" ]; then
  echo "[deploy] dry run complete — nothing changed."
  exit 0
fi

echo "[deploy] rebuilding api/engine/dashboard on the server ..."
ssh -i "${KEY}" "${HOST}" "cd ${DEST} && sudo docker compose up -d --build api engine dashboard"
echo "[deploy] done. Verify: ssh ${HOST} 'cd ${DEST} && sudo docker compose ps'"
