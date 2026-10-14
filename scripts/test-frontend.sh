#!/usr/bin/env bash
#
# Frontend test suite with a hard coverage floor.
#
#   make test-frontend
#
# Builds the bundle with istanbul instrumentation (COVERAGE=1), starts the app
# against a disposable database seeded with sample listings, runs Playwright,
# then reports coverage through nyc and fails below the floors in .nycrc.json.
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
APP_PIDS=()
STATUS=1

info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ -x "$VENV_PY" ] || die "No virtualenv — run 'make install-dev' first."
[ -d frontend/node_modules ] || die "Frontend deps missing — run 'make install-dev'."

cleanup() {
  for pid in "${APP_PIDS[@]}"; do
    kill -- "-$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  [ -n "${MILSURP_E2E_WORK_DIR:-}" ] || rm -rf "$WORK_DIR"
}
trap cleanup EXIT

printf '\n\033[1mFrontend tests\033[0m (Playwright, minimum 77%% coverage)\n\n'

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

# --- Start the apps ---------------------------------------------------------
# One per Playwright worker, each on its own copy of the database prepared
# above (2026-10-14): the suite writes as it goes -- signs in, approves rows,
# saves settings -- so workers sharing a database would race. Half the cores by
# default, since each worker is a browser and an app server; a run of named
# spec files needs no more than one per file. MILSURP_E2E_WORKERS sets it.
CORES="$(nproc 2>/dev/null || echo 2)"
WORKERS="${MILSURP_E2E_WORKERS:-$(( CORES / 2 ))}"
SPECS=0
for arg in "$@"; do
  case "$arg" in *.spec.js | *.spec.js:*) SPECS=$((SPECS + 1)) ;; esac
done
if [ "$SPECS" -gt 0 ] && [ "$SPECS" -lt "$WORKERS" ]; then WORKERS="$SPECS"; fi
[ "$WORKERS" -ge 1 ] 2>/dev/null || WORKERS=1

start_app() {
  local dir="$WORK_DIR/app-$1"
  mkdir -p "$dir/backups"
  # The writes are finished (every step above has exited), but a WAL file
  # left beside the database would hold the last of them.
  for part in e2e.db e2e.db-wal e2e.db-shm; do
    [ -f "$WORK_DIR/$part" ] && cp "$WORK_DIR/$part" "$dir/$part"
  done
  [ -d "$WORK_DIR/images" ] && cp -r "$WORK_DIR/images" "$dir/images"
  sed -e "s#$WORK_DIR/e2e.db#$dir/e2e.db#" \
      -e "s#$WORK_DIR/images#$dir/images#" \
      -e "s#$WORK_DIR/backups#$dir/backups#" \
      "$WORK_DIR/config.yaml" > "$dir/config.yaml"
  setsid env MILSURP_ENV=dev MILSURP_CONFIG="$dir/config.yaml" \
    MILSURP_ENABLE_DEMO_SITE=1 MILSURP_FRONTEND_DIST="$MILSURP_FRONTEND_DIST" \
    "$VENV_PY" backend/run.py --port 0 > "$dir/server.log" 2>&1 &
  APP_PIDS+=("$!")
}

app_url() {
  local log="$WORK_DIR/app-$1/server.log" port=""
  # --port 0 lets the OS choose; read the port back from the startup banner.
  for _ in $(seq 1 60); do
    port="$(grep -oE 'listening on http://[^:]+:([0-9]+)' "$log" \
            | grep -oE '[0-9]+$' | head -1)"
    [ -n "$port" ] && break
    sleep 0.5
  done
  [ -n "$port" ] || { cat "$log" >&2; return 1; }
  for _ in $(seq 1 40); do
    curl -sf "http://127.0.0.1:$port/api/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
  curl -sf "http://127.0.0.1:$port/api/health" >/dev/null 2>&1 \
    || { tail -30 "$log" >&2; return 1; }
  echo "http://127.0.0.1:$port"
}

info "Starting $WORKERS app(s)…"
for n in $(seq 1 "$WORKERS"); do start_app "$n"; done
URLS=()
for n in $(seq 1 "$WORKERS"); do
  url="$(app_url "$n")" || die "App $n did not start."
  URLS+=("$url")
done
ok "Apps on ${URLS[*]}"

# --- Run Playwright ---------------------------------------------------------
printf '\n'
export MILSURP_URLS="${URLS[*]}"
export MILSURP_URL="${URLS[0]}"
export MILSURP_USER="admin"
export MILSURP_PASSWORD="$TEST_PASSWORD"

(cd frontend && npx --no-install playwright test "$@")
STATUS=$?

# --- Coverage ---------------------------------------------------------------
printf '\n'
if [ -n "$(ls -A "$MILSURP_E2E_NYC_DIR" 2>/dev/null)" ]; then
  info "Reporting coverage…"
  (cd frontend && npx --no-install nyc --temp-dir "$MILSURP_E2E_NYC_DIR" report) || STATUS=1
  # The README badge only from a run that passed, thresholds included -- as
  # test-backend.sh does. A run of one or two specs measures a slice of the
  # bundle and fails the thresholds, and until 2026-10-12 it rewrote the badge
  # anyway: 51.6% went out on the README from a run of two spec files.
  if [ "$STATUS" -eq 0 ]; then
    "$VENV_PY" scripts/coverage_badges.py --frontend-only --quiet || true
  fi
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
