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
# MILSURP_E2E_WORK_DIR keeps the disposable database and config after the run,
# for diagnosing a failure that only reproduces inside the harness.
WORK_DIR="${MILSURP_E2E_WORK_DIR:-$(mktemp -d -t milsurp-e2e-XXXXXX)}"
mkdir -p "$WORK_DIR"
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
  [ -n "${MILSURP_E2E_WORK_DIR:-}" ] || rm -rf "$WORK_DIR"
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
backups:
  # Isolated like everything else. Without this the suite falls back to the
  # dev default -- the repository's own backups/ -- and the "Back up now"
  # test writes snapshots into a real backup directory, where they count
  # towards the retention limit and can push genuine backups out of it. Which
  # is exactly what happened the first time that test ran.
  directory: $WORK_DIR/backups
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
# Built to its own directory, never over frontend/dist: that is the bundle
# `make start` serves, and overwriting it with an instrumented build left the
# running app serving coverage-instrumented code with no sign that it had.
COVERAGE_DIST="dist-coverage"
export MILSURP_FRONTEND_DIST="$REPO_ROOT/frontend/$COVERAGE_DIST"
(cd frontend && COVERAGE=1 npm run build --silent -- --outDir "$COVERAGE_DIST" --emptyOutDir) \
  || die "Frontend build failed."
# Artifacts go under this run's own work directory, not into shared paths in
# the repository. Playwright deletes and recreates its output directory as it
# starts, and nyc reads whatever it finds in .nyc_output — so two runs at once
# (a developer and an agent, or two terminals) used to delete each other's
# trace files mid-test and merge each other's coverage. That surfaced as
# "ENOENT ... .playwright-artifacts-0/traces/..." on a passing test and a
# coverage figure of about a third of the real one, neither of which says
# anything about the code under test.
#
# The database and the signing secrets were already per-run for the same
# reason; this finishes the job.
export MILSURP_E2E_OUTPUT_DIR="$WORK_DIR/test-results"
export MILSURP_E2E_NYC_DIR="$WORK_DIR/.nyc_output"
mkdir -p "$MILSURP_E2E_OUTPUT_DIR" "$MILSURP_E2E_NYC_DIR"
rm -rf frontend/coverage
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
if [ -n "$(ls -A "$MILSURP_E2E_NYC_DIR" 2>/dev/null)" ]; then
  info "Reporting coverage…"
  (cd frontend && npx --no-install nyc --temp-dir "$MILSURP_E2E_NYC_DIR" report) || STATUS=1
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
