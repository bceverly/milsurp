#!/usr/bin/env bash
#
# Capture the README screenshots.
#
#   make screenshots
#
# Runs against a **disposable database seeded with sample listings**, not your
# development database. Three reasons that matters:
#
#   * the images are reproducible — the same listings every time, so a diff
#     between two runs reflects a UI change and nothing else;
#   * it works on a fresh checkout with no scan history;
#   * real scraped vendor content never ends up in committed marketing images.
#
# Output: marketing/images/screenshot-*.png
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV_PY=".venv/bin/python"
WORK_DIR="$(mktemp -d -t milsurp-shots-XXXXXX)"
DEMO_PASSWORD="screenshot-demo-passphrase"
APP_PID=""

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

printf '\n\033[1mCapturing screenshots\033[0m\n\n'

cat > "$WORK_DIR/config.yaml" <<CONFIG
database:
  path: $WORK_DIR/demo.db
images:
  path: $WORK_DIR/images
security:
  password_pepper: "screenshot-pepper-0123456789abcdef0123456789abcd"
  jwt_secret: "screenshot-jwt-secret-0123456789abcdef0123456789ab"
  argon2_time_cost: 1
  argon2_memory_cost: 8
  argon2_parallelism: 1
admin:
  username: admin
  email: admin@milsurpmonitor.com
  password: "$DEMO_PASSWORD"
email:
  enabled: false
scheduler:
  # Otherwise opening the app would start real scans against vendor sites.
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
"$VENV_PY" scripts/seed_demo_data.py --quiet || die "Could not load sample data."
ok "Sample listings loaded."

info "Building the frontend…"
(cd frontend && npm run build --silent) || die "Frontend build failed."

info "Starting the app…"
setsid env MILSURP_ENV=dev MILSURP_CONFIG="$MILSURP_CONFIG" \
  MILSURP_ENABLE_DEMO_SITE=1 \
  "$VENV_PY" backend/run.py --port 0 > "$WORK_DIR/server.log" 2>&1 &
APP_PID=$!

PORT=""
for _ in $(seq 1 60); do
  # `|| true`: until the banner is written the greps find nothing and exit 1,
  # which under `set -e` would abort the script on the very first poll.
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
  || { tail -20 "$WORK_DIR/server.log"; die "The app is not responding."; }
ok "App on http://127.0.0.1:$PORT"

printf '\n'
export MILSURP_URL="http://127.0.0.1:$PORT"
export MILSURP_USER="admin"
export MILSURP_PASSWORD="$DEMO_PASSWORD"
export MILSURP_SHOTS="$REPO_ROOT/marketing/images"

(cd frontend && node tests/screenshots.mjs)

printf '\n'
ok "Screenshots written to marketing/images/"
ls -1 marketing/images/screenshot-*.png 2>/dev/null | sed 's|^|    |'
printf '\n'
