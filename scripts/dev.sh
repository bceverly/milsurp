#!/usr/bin/env bash
#
# Development mode with hot reload.
#
#   make dev
#
# Runs two processes in the foreground:
#
#   * the Python API with --reload, on a dynamically chosen port
#   * the Vite dev server on :5173, proxying /api to that port
#
# Open the Vite URL, not the API one — that is the one with hot module
# replacement. Ctrl-C stops both.
#
# For a single-process setup that serves the built bundle from Python instead,
# use `make start`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export MILSURP_ENV=dev
VENV_PY=".venv/bin/python"
PORT_FILE=".milsurp-dev-port"

info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$VENV_PY" ] || die "No virtualenv — run 'make install-dev' first."
[ -d frontend/node_modules ] || die "Frontend deps missing — run 'make install-dev'."

API_PID=""
VITE_PID=""

cleanup() {
  printf '\n'
  info "Shutting down…"
  # Kill the process groups: uvicorn --reload and vite both spawn children that
  # would otherwise survive and hold their ports.
  [ -n "$VITE_PID" ] && kill -- "-$VITE_PID" 2>/dev/null || true
  [ -n "$API_PID" ] && kill -- "-$API_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -f "$PORT_FILE"
  ok "Stopped."
}
trap cleanup EXIT INT TERM

printf '\n\033[1mMilsurp Monitor — development mode\033[0m\n\n'

# Make sure the schema is current before anything tries to query it.
info "Applying migrations…"
"$VENV_PY" scripts/dbupdate.py --quiet

info "Starting the API (auto-reload)…"
rm -f "$PORT_FILE"
setsid "$VENV_PY" backend/run.py --reload &
API_PID=$!

# run.py writes the port it chose; Vite's proxy needs to know it.
for _ in $(seq 1 60); do
  [ -s "$PORT_FILE" ] && break
  sleep 0.25
done
API_PORT="$(cat "$PORT_FILE" 2>/dev/null || echo 8730)"

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1 \
  || die "The API did not come up on port $API_PORT. Check the output above."
ok "API on http://127.0.0.1:$API_PORT"

info "Starting Vite…"
# vite.config.js reads MILSURP_API_PORT to point its /api proxy at the port the
# API actually chose, rather than assuming the default.
export MILSURP_API_PORT="$API_PORT"
cd frontend
setsid npm run dev &
VITE_PID=$!
cd "$REPO_ROOT"

sleep 2
cat <<BANNER

  ────────────────────────────────────────────────────────────
   \033[1;92m▲ Development mode\033[0m

     UI  (hot reload)   \033[1;96mhttp://localhost:5173\033[0m   ← open this
     API                http://127.0.0.1:$API_PORT
     API docs           http://127.0.0.1:$API_PORT/api/docs

     Ctrl-C stops both.
  ────────────────────────────────────────────────────────────

BANNER

# Wait on either child; if one dies, cleanup takes the other down with it.
wait -n "$API_PID" "$VITE_PID" 2>/dev/null || wait
