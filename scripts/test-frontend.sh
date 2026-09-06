#!/usr/bin/env bash
#
# Frontend test suite with a hard coverage floor.
#
#   make test-frontend
#
# Builds the bundle with istanbul instrumentation (COVERAGE=1), starts the app
# against a disposable database seeded with sample listings, runs Playwright,
# then reports coverage through nyc and fails below 65%.
#
# The database is disposable on purpose: the suite signs in, changes site
# settings and saves preferences, and must not touch a developer's real data.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV_PY=".venv/bin/python"
WORK_DIR="$(mktemp -d -t milsurp-e2e-XXXXXX)"
TEST_PASSWORD="playwright-test-passphrase"
APP_PID=""
STATUS=1

info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$VENV_PY" ] || die "No virtualenv — run 'make install-dev' first."
[ -d frontend/node_modules ] || die "Frontend deps missing — run 'make install-dev'."

cleanup() {
  if [ -n "$APP_PID" ]; then
    kill -- "-$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

printf '\n\033[1mFrontend tests\033[0m (Playwright, minimum 65%% coverage)\n\n'

# --- Disposable configuration ----------------------------------------------
# Fresh throwaway secrets per run. Generated rather than hard-coded so that no
# tracked file in this repository ever contains a secret-shaped literal for a
# scanner to flag — and so two concurrent runs cannot share a signing key.
rand_hex() { head -c 32 /dev/urandom | od -An -vtx1 | tr -d ' \n'; }
E2E_PEPPER="$(rand_hex)"
E2E_JWT_SECRET="$(rand_hex)"

cat > "$WORK_DIR/config.yaml" <<CONFIG
database:
  path: $WORK_DIR/e2e.db
images:
  path: $WORK_DIR/images
security:
  password_pepper: "$E2E_PEPPER"
  jwt_secret: "$E2E_JWT_SECRET"
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
  # Otherwise starting the app would launch real scans against vendor sites.
  enabled: false
scraping:
  download_images: false
CONFIG

export MILSURP_ENV=dev
export MILSURP_CONFIG="$WORK_DIR/config.yaml"
# Register the network-free demo vendor, so a scan can be exercised end to end
# without contacting a real shop.
export MILSURP_ENABLE_DEMO_SITE=1

info "Preparing a disposable database…"
"$VENV_PY" scripts/dbupdate.py --quiet >/dev/null 2>&1 || die "Migration failed."
"$VENV_PY" backend/cli.py init >/dev/null 2>&1 || die "Seeding failed."

# The UI is meaningless with an empty catalog, so load deterministic fixtures.
info "Loading sample listings…"
"$VENV_PY" scripts/seed_demo_data.py --quiet || die "Could not load sample data."

# --- Instrumented build -----------------------------------------------------
info "Building the instrumented bundle…"
(cd frontend && COVERAGE=1 npm run build --silent) || die "Frontend build failed."
rm -rf frontend/.nyc_output frontend/coverage
ok "Bundle instrumented."

# --- Start the app ----------------------------------------------------------
info "Starting the app…"
setsid env MILSURP_ENV=dev MILSURP_CONFIG="$MILSURP_CONFIG" \
  MILSURP_ENABLE_DEMO_SITE=1 \
  "$VENV_PY" backend/run.py --port 0 > "$WORK_DIR/server.log" 2>&1 &
APP_PID=$!

# --port 0 lets the OS choose; read the port back from the startup banner.
PORT=""
for _ in $(seq 1 60); do
  PORT="$(grep -oE 'listening on http://[^:]+:([0-9]+)' "$WORK_DIR/server.log" \
          | grep -oE '[0-9]+$' | head -1)"
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

# --- Run Playwright ---------------------------------------------------------
printf '\n'
export MILSURP_URL="http://127.0.0.1:$PORT"
export MILSURP_USER="admin"
export MILSURP_PASSWORD="$TEST_PASSWORD"

(cd frontend && npx --no-install playwright test "$@")
STATUS=$?

# --- Coverage ---------------------------------------------------------------
printf '\n'
if [ -d frontend/.nyc_output ] && [ -n "$(ls -A frontend/.nyc_output 2>/dev/null)" ]; then
  info "Reporting coverage…"
  (cd frontend && npx --no-install nyc report) || STATUS=1
  "$VENV_PY" scripts/coverage_badges.py --frontend-only --quiet || true
else
  printf '  \033[91m✗\033[0m No coverage collected. Was the bundle built with COVERAGE=1?\n'
  STATUS=1
fi

printf '\n'
if [ "$STATUS" -eq 0 ]; then
  printf '\033[1;92m✓ Frontend tests passed.\033[0m\n\n'
else
  printf '\033[1;91m✗ Frontend tests failed.\033[0m\n\n'
fi
exit "$STATUS"
