#!/usr/bin/env bash
#
# Visual regression tests: each main page compared with a baseline image.
#
#   make test-visual            compare against the committed baselines
#   make test-visual-update     rewrite the baselines after an intended change
#
# Starts the app on a disposable database whose sample listings are dated from
# one fixed moment, builds the production bundle, and runs
# frontend/tests/visual/ in a browser inside the official Playwright container.
#
# The container is the point. Two machines render the same page with slightly
# different fonts, and a pixel comparison cannot tell that from a real change,
# so the browser used here is the same everywhere: on a laptop, in CI, next
# year. It needs Docker, or Podman with its Docker command.
#
# Extra arguments go to Playwright, e.g. `make test-visual ARGS="-g inventory"`.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV_PY=".venv/bin/python"
WORK_DIR="$(mktemp -d -t milsurp-visual-XXXXXX)"
TEST_PASSWORD="visual-test-passphrase"
# The moment every sample date counts back from, and the time the browser is
# told it is. In the past on purpose; see frontend/tests/visual/pages.visual.js.
export MILSURP_VISUAL_NOW="2026-09-01T15:00:00Z"
APP_PID=""
CONTAINER=""

info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$VENV_PY" ] || die "No virtualenv — run 'make install-dev' first."
[ -d frontend/node_modules ] || die "Frontend deps missing — run 'make install-dev'."
command -v docker >/dev/null 2>&1 \
  || die "Docker is needed: the browser runs in the Playwright container so every machine renders alike."

cleanup() {
  [ -n "$CONTAINER" ] && docker rm -f "$CONTAINER" >/dev/null 2>&1
  if [ -n "$APP_PID" ]; then
    kill -- "-$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

printf '\n\033[1mVisual regression tests\033[0m\n\n'

rand_hex() { head -c 32 /dev/urandom | od -An -vtx1 | tr -d ' \n'; }

cat > "$WORK_DIR/config.yaml" <<CONFIG
database:
  path: $WORK_DIR/visual.db
images:
  path: $WORK_DIR/images
backups:
  directory: $WORK_DIR/backups
security:
  password_pepper: "$(rand_hex)"
  jwt_secret: "$(rand_hex)"
  argon2_time_cost: 1
  argon2_memory_cost: 8
  argon2_parallelism: 1
admin:
  username: admin
  email: admin@example.com
  password: "$TEST_PASSWORD"
email:
  enabled: false
scheduler:
  enabled: false
scraping:
  download_images: false
CONFIG

export MILSURP_ENV=dev
export MILSURP_CONFIG="$WORK_DIR/config.yaml"
export MILSURP_ENABLE_DEMO_SITE=1

info "Preparing a disposable database…"
"$VENV_PY" scripts/dbupdate.py --quiet >/dev/null 2>&1 || die "Migration failed."
"$VENV_PY" backend/cli.py init >/dev/null 2>&1 || die "Seeding failed."
"$VENV_PY" scripts/seed_demo_data.py --quiet --now "$MILSURP_VISUAL_NOW" \
  || die "Could not load sample data."
ok "Sample listings dated from $MILSURP_VISUAL_NOW."

# The production bundle, not the instrumented one: coverage counters change
# nothing on screen, but this is what users see. Built to its own directory so
# it never replaces the frontend/dist that `make start` serves.
info "Building the frontend…"
VISUAL_DIST="dist-visual"
export MILSURP_FRONTEND_DIST="$REPO_ROOT/frontend/$VISUAL_DIST"
(cd frontend && npm run build --silent -- --outDir "$VISUAL_DIST" --emptyOutDir >/dev/null) \
  || die "Frontend build failed."
ok "Bundle built."

info "Starting the app…"
setsid env MILSURP_ENV=dev MILSURP_CONFIG="$MILSURP_CONFIG" \
  MILSURP_ENABLE_DEMO_SITE=1 MILSURP_FRONTEND_DIST="$MILSURP_FRONTEND_DIST" \
  "$VENV_PY" backend/run.py --port 0 > "$WORK_DIR/server.log" 2>&1 &
APP_PID=$!

PORT=""
for _ in $(seq 1 60); do
  PORT="$(grep -oE 'listening on http://[^:]+:([0-9]+)' "$WORK_DIR/server.log" 2>/dev/null \
          | grep -oE '[0-9]+$' | head -1 || true)"
  [ -n "$PORT" ] && break
  sleep 0.5
done
[ -n "$PORT" ] || { cat "$WORK_DIR/server.log"; die "The app did not start."; }
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 \
  || { tail -30 "$WORK_DIR/server.log"; die "The app is not responding."; }
ok "App on http://127.0.0.1:$PORT"

# --- The browser, in the container ------------------------------------------
# Pinned to the Playwright the frontend actually has installed: the client and
# the server must be the same version, and a floating tag would change the
# rendering underneath the baselines.
PW_VERSION="$(cd frontend && node -p 'require("@playwright/test/package.json").version')"
PW_PORT="$("$VENV_PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
info "Starting the Playwright $PW_VERSION browser container…"
# Host networking so the browser reaches the app on 127.0.0.1, as a local
# browser would.
CONTAINER="$(docker run -d --rm --init --network host --user pwuser --workdir /home/pwuser \
  "mcr.microsoft.com/playwright:v$PW_VERSION-noble" \
  /bin/sh -c "npx -y playwright@$PW_VERSION run-server --port $PW_PORT --host 127.0.0.1")" \
  || die "Could not start the Playwright container."
for _ in $(seq 1 120); do
  curl -s -o /dev/null "http://127.0.0.1:$PW_PORT/" 2>/dev/null && break
  sleep 0.5
done
curl -s -o /dev/null "http://127.0.0.1:$PW_PORT/" 2>/dev/null \
  || { docker logs "$CONTAINER" | tail -20; die "The browser container did not come up."; }
ok "Browser container on port $PW_PORT"

printf '\n'
export MILSURP_URL="http://127.0.0.1:$PORT"
export MILSURP_USER="admin"
export MILSURP_PASSWORD="$TEST_PASSWORD"
export MILSURP_PW_ENDPOINT="ws://127.0.0.1:$PW_PORT/"
export MILSURP_E2E_OUTPUT_DIR="$REPO_ROOT/frontend/test-results-visual"

(cd frontend && npx --no-install playwright test --config playwright.visual.config.js "$@")
STATUS=$?

printf '\n'
if [ "$STATUS" -eq 0 ]; then
  printf '\033[1;92m✓ Visual tests passed.\033[0m\n\n'
else
  printf '\033[1;91m✗ Visual tests failed.\033[0m\n'
  printf '  The expected, actual and diff images are in frontend/test-results-visual/.\n'
  printf '  If the change was intended: make test-visual-update\n\n'
fi
exit "$STATUS"
