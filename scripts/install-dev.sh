#!/usr/bin/env bash
#
# Development environment setup.
#
# Creates .venv in the repository root, installs the Python and Node
# dependencies, the linters, the security scanners and the Playwright browser.
# System packages are installed with sudo, so you will be prompted for your
# password once.
#
#   make install-dev
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
PYTHON="${PYTHON:-python3}"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()    { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[93m!\033[0m %s\n' "$*"; }

bold ""
bold "Milsurp Monitor — development setup"
bold "───────────────────────────────────"

# --- System packages -------------------------------------------------------
# Everything the app needs that pip cannot provide: the Python venv module,
# a compiler for argon2-cffi's C extension, and Chrome for the browser-driven
# scrapers.
APT_PACKAGES=(
  python3-venv python3-dev build-essential pkg-config
  libffi-dev libjpeg-dev zlib1g-dev
  curl git make
  # Linters that are not pip-installable; `make lint` skips them when absent.
  shellcheck
)

if command -v apt-get >/dev/null 2>&1; then
  bold ""
  bold "1. System packages"
  info "Installing: ${APT_PACKAGES[*]}"
  warn "sudo will prompt for your password."
  sudo apt-get update -qq
  sudo apt-get install -y -qq "${APT_PACKAGES[@]}"
  ok "System packages installed."

  # Google Chrome drives the Royal Tiger scraper (infinite scroll / Load More).
  if command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
    ok "Chrome/Chromium already present ($(command -v google-chrome || command -v chromium))."
  else
    info "Installing Chromium for the browser-driven scrapers…"
    sudo apt-get install -y -qq chromium-browser 2>/dev/null \
      || sudo apt-get install -y -qq chromium 2>/dev/null \
      || warn "Could not install Chromium automatically. Install Google Chrome by hand,
       or leave the Royal Tiger site disabled in the admin UI."
  fi
else
  bold ""
  warn "No apt-get found — skipping system packages."
  warn "On macOS: brew install python@3 node google-chrome"
fi

# --- Node ------------------------------------------------------------------
bold ""
bold "2. Node.js"
if command -v node >/dev/null 2>&1; then
  ok "node $(node --version), npm $(npm --version)"
else
  if command -v apt-get >/dev/null 2>&1; then
    info "Installing Node.js…"
    sudo apt-get install -y -qq nodejs npm
    ok "node $(node --version)"
  else
    warn "Node.js is not installed. Install Node 20+ and re-run."
    exit 1
  fi
fi

# --- Python virtualenv -----------------------------------------------------
bold ""
bold "3. Python virtualenv (.venv)"
if [ -x "$VENV/bin/python" ]; then
  ok "Reusing the existing $VENV"
else
  info "Creating $VENV"
  "$PYTHON" -m venv "$VENV"
  ok "Created."
fi

info "Upgrading pip…"
"$VENV/bin/pip" install --quiet --upgrade pip setuptools wheel

info "Installing application + development dependencies…"
"$VENV/bin/pip" install --quiet -r backend/requirements-dev.txt
ok "Python dependencies installed ($("$VENV/bin/pip" list 2>/dev/null | wc -l) packages)."

# --- Frontend --------------------------------------------------------------
bold ""
bold "4. Frontend"
info "Installing npm packages…"
(cd frontend && npm install --no-audit --no-fund --silent)
ok "npm packages installed."

info "Installing the Playwright browser (used by tests and 'make screenshots')…"
(cd frontend && npx --yes playwright install chromium >/dev/null 2>&1) \
  && ok "Playwright Chromium installed." \
  || warn "Playwright browser install failed; run 'cd frontend && npx playwright install chromium'."

if command -v apt-get >/dev/null 2>&1; then
  info "Installing Playwright's system libraries…"
  (cd frontend && sudo npx --yes playwright install-deps chromium >/dev/null 2>&1) \
    && ok "Playwright system libraries installed." \
    || warn "Could not install Playwright system deps; tests may fail to launch a browser."
fi

# --- Local configuration ---------------------------------------------------
bold ""
bold "5. Local configuration"
if [ -f config.yaml ]; then
  ok "config.yaml already exists."
else
  cp config.yaml.sample config.yaml
  chmod 600 config.yaml
  # Generate real secrets so the new checkout is usable immediately rather than
  # failing at first sign-in with a placeholder JWT key.
  "$VENV/bin/python" - <<'PY'
import re, secrets, pathlib
path = pathlib.Path("config.yaml")
text = path.read_text()
for key in ("password_pepper", "jwt_secret"):
    text = re.sub(
        rf'(^\s*{key}:\s*).*$',
        lambda m: f'{m.group(1)}"{secrets.token_urlsafe(48)}"',
        text, count=1, flags=re.MULTILINE,
    )
# Dev defaults: keep state in the repo, and leave email off until configured.
text = re.sub(r'^(database:\n)(\s*#[^\n]*\n)*\s*path:.*$', r'\1  # dev default: <repo root>/milsurp.db', text, flags=re.MULTILINE)
text = re.sub(r'^images:\n(\s*#[^\n]*\n)*\s*path:.*$', 'images:\n  # dev default: <repo root>/data/images', text, flags=re.MULTILINE)
path.write_text(text)
print("  \033[92m✓\033[0m Created config.yaml with freshly generated secrets.")
PY
  warn "Set admin.password in config.yaml before running 'make init'."
  warn "Scanning is off by default (scheduler.enabled: false). Turn it on when"
  warn "you are ready, or run a one-off scan with 'make scan site=empire-arms'."
fi

# --- Git hooks -------------------------------------------------------------
bold ""
bold "6. Git hooks"
if [ -d .git ]; then
  scripts/install-hooks.sh
else
  warn "Not a git repository — skipping hook installation."
fi

bold ""
bold "Done."
cat <<'NEXT'

  Next steps:

    1. Edit config.yaml and set admin.password (12+ characters).
    2. make init      — create the database, seed sites and the admin account
    3. make start     — build the UI and launch; prints the URL

  Other useful targets: make test, make lint, make security, make screenshots
  Run `make` on its own for the full list.

NEXT
