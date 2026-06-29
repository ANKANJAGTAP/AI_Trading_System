#!/usr/bin/env bash
# Open an SSH tunnel to the operator dashboard (paper). The dashboard publishes on
# the server's localhost:5173 and its nginx proxies /api + /ws to the api container,
# so this single local->remote forward carries the whole app (UI, API, websocket).
# Private + encrypted; nothing is exposed publicly. Leave it running; Ctrl-C closes it.
# Override with ATS_HOST / ATS_KEY / ATS_LOCAL_PORT / ATS_REMOTE_PORT.
#
#   ./scripts/tunnel.sh         # then open http://localhost:5173 in your browser
set -euo pipefail

KEY="${ATS_KEY:-$HOME/.ssh/ats-key}"
HOST="${ATS_HOST:-ubuntu@43.205.112.232}"
LPORT="${ATS_LOCAL_PORT:-5173}"
RPORT="${ATS_REMOTE_PORT:-5173}"

echo "dashboard tunnel:  http://localhost:${LPORT}  ->  ${HOST}  (server localhost:${RPORT})"
echo "open that URL in your browser. leave this terminal open; Ctrl-C to close the tunnel."
echo "(if you see 'Address already in use', another app holds ${LPORT}:"
echo "    ATS_LOCAL_PORT=5180 ./scripts/tunnel.sh  ->  then open http://localhost:5180 )"
echo
# Bare invocation — matches what works by hand. (ServerAlive/ExitOnForwardFailure
# were added for robustness but triggered an immediate "Can't assign requested
# address" disconnect on this network; dropped them. Re-add -o ServerAliveInterval=60
# later only if an idle tunnel gets dropped by NAT.)
exec ssh -i "$KEY" -N -L "${LPORT}:127.0.0.1:${RPORT}" "$HOST"
