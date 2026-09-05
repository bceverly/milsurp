#!/usr/bin/env bash
#
# Production installation for Ubuntu 26.04 LTS.
#
#   sudo scripts/install-production.sh
#
# Installs every system dependency, creates a dedicated service account, lays
# out /etc/milsurp, installs the application into /opt/milsurp, builds the
# frontend, configures nginx and registers a systemd unit.
#
# It does NOT obtain a TLS certificate — run scripts/setup-letsencrypt.sh after
# this, once DNS for the domain points at this machine.
#
# Safe to re-run: every step checks for what it is about to create.
set -euo pipefail

APP_NAME="milsurp"
APP_USER="milsurp"
APP_GROUP="milsurp"
INSTALL_DIR="/opt/milsurp"
CONFIG_DIR="/etc/milsurp"
DOMAIN="${DOMAIN:-milsurpmonitor.com}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[93m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo: sudo scripts/install-production.sh"

bold "Milsurp Monitor — production install (Ubuntu 26.04)"
echo "  Domain:      $DOMAIN"
echo "  Install dir: $INSTALL_DIR"
echo "  Config dir:  $CONFIG_DIR"
echo "  Service user: $APP_USER"

# ---------------------------------------------------------------------------
bold "1. System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 python3-venv python3-dev \
  build-essential pkg-config libffi-dev libjpeg-dev zlib1g-dev \
  nginx \
  sqlite3 \
  curl ca-certificates gnupg git \
  ufw
ok "Base packages installed."

# Node is only needed to build the frontend bundle; it is not needed at runtime.
if ! command -v node >/dev/null 2>&1; then
  info "Installing Node.js 22 from NodeSource…"
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list
  apt-get update -qq
  apt-get install -y -qq nodejs
fi
ok "node $(node --version)"

# Chrome drives the scrapers whose catalogs only render in JavaScript.
if ! command -v google-chrome >/dev/null 2>&1; then
  info "Installing Google Chrome (needed by browser-driven scrapers)…"
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list
  apt-get update -qq
  apt-get install -y -qq google-chrome-stable \
    || warn "Chrome install failed; browser-driven sites will need to stay disabled."
fi
command -v google-chrome >/dev/null 2>&1 && ok "$(google-chrome --version)"

# ---------------------------------------------------------------------------
bold "2. Service account"
if id "$APP_USER" >/dev/null 2>&1; then
  ok "User $APP_USER already exists."
else
  # A system account with no login shell: the service never needs one, and it
  # limits what an attacker gains from compromising the app.
  adduser --system --group --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$APP_USER"
  ok "Created system user $APP_USER."
fi

# ---------------------------------------------------------------------------
bold "3. Directories"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$CONFIG_DIR"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0700 "$CONFIG_DIR/images"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0755 "$INSTALL_DIR"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0755 /var/log/milsurp
ok "$CONFIG_DIR (0750), $CONFIG_DIR/images (0700), $INSTALL_DIR"

# ---------------------------------------------------------------------------
bold "4. Application files"
info "Copying the application to $INSTALL_DIR…"
# --delete keeps the target a clean mirror; excludes stop dev state leaking in.
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude 'node_modules' \
  --exclude '*.db' --exclude '*.db-*' --exclude 'data' \
  --exclude 'config.yaml' --exclude '.server.pid' --exclude '*.log' \
  "$REPO_ROOT/" "$INSTALL_DIR/"
chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"
ok "Application copied."

# ---------------------------------------------------------------------------
bold "5. Python environment"
if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
  sudo -u "$APP_USER" python3 -m venv "$INSTALL_DIR/.venv"
fi
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/backend/requirements.txt"
ok "Python dependencies installed."

# ---------------------------------------------------------------------------
bold "6. Frontend build"
info "Building the production bundle…"
(cd "$INSTALL_DIR/frontend" && npm install --no-audit --no-fund --silent && npm run build)
chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR/frontend"
ok "Frontend built to $INSTALL_DIR/frontend/dist."

# ---------------------------------------------------------------------------
bold "7. Configuration"
if [ -f "$CONFIG_DIR/config.yaml" ]; then
  ok "$CONFIG_DIR/config.yaml already exists — left untouched."
else
  install -o "$APP_USER" -g "$APP_GROUP" -m 0600 \
    "$INSTALL_DIR/config.yaml.sample" "$CONFIG_DIR/config.yaml"
  # Generate the secrets in place so the file is never deployed with the
  # sample placeholders still in it.
  "$INSTALL_DIR/.venv/bin/python" - "$CONFIG_DIR/config.yaml" <<'PY'
import re, secrets, sys, pathlib
path = pathlib.Path(sys.argv[1])
text = path.read_text()
for key in ("password_pepper", "jwt_secret"):
    text = re.sub(rf'(^\s*{key}:\s*).*$',
                  lambda m: f'{m.group(1)}"{secrets.token_urlsafe(48)}"',
                  text, count=1, flags=re.MULTILINE)
path.write_text(text)
PY
  chmod 600 "$CONFIG_DIR/config.yaml"
  chown "$APP_USER:$APP_GROUP" "$CONFIG_DIR/config.yaml"
  ok "Created $CONFIG_DIR/config.yaml (mode 600) with generated secrets."
  warn "EDIT IT before starting: set admin.password, email.*, and server.production.public_url."
fi

# ---------------------------------------------------------------------------
bold "8. Database"
sudo -u "$APP_USER" env MILSURP_ENV=production \
  "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/dbupdate.py" --quiet
ok "Database created/migrated at $CONFIG_DIR/milsurp.db"

# ---------------------------------------------------------------------------
bold "9. systemd service"
install -m 0644 "$INSTALL_DIR/deploy/systemd/milsurp.service" /etc/systemd/system/milsurp.service
systemctl daemon-reload
systemctl enable milsurp >/dev/null 2>&1
ok "Service registered and enabled at boot."

# ---------------------------------------------------------------------------
bold "10. nginx"
# Substitute the domain into the shipped template.
sed "s/milsurpmonitor\.com/$DOMAIN/g" \
  "$INSTALL_DIR/deploy/nginx/milsurp.conf" > "/etc/nginx/sites-available/$APP_NAME"
ln -sf "/etc/nginx/sites-available/$APP_NAME" "/etc/nginx/sites-enabled/$APP_NAME"
rm -f /etc/nginx/sites-enabled/default

# The TLS block cannot pass a config test before a certificate exists, so serve
# plain HTTP until setup-letsencrypt.sh has run.
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  warn "No TLS certificate yet — installing the HTTP-only bootstrap config."
  sed "s/milsurpmonitor\.com/$DOMAIN/g" \
    "$INSTALL_DIR/deploy/nginx/milsurp-bootstrap.conf" > "/etc/nginx/sites-available/$APP_NAME"
fi

nginx -t && systemctl reload nginx
ok "nginx configured for $DOMAIN."

# ---------------------------------------------------------------------------
bold "11. Firewall"
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow 'Nginx Full' >/dev/null 2>&1 || true
if ! ufw status | grep -q "Status: active"; then
  warn "ufw is installed but inactive. Enable it with: sudo ufw enable"
else
  ok "Firewall allows SSH, HTTP and HTTPS."
fi

# ---------------------------------------------------------------------------
bold "Installation complete."
cat <<NEXT

  Next steps:

    1. Edit the configuration and set admin.password plus your SMTP details:
         sudo -e $CONFIG_DIR/config.yaml

    2. Seed the database (sites + the initial admin account):
         sudo -u $APP_USER env MILSURP_ENV=production \\
           $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/backend/cli.py init

    3. Point DNS for $DOMAIN at this machine, then get a certificate:
         sudo scripts/setup-letsencrypt.sh

    4. Start the service:
         sudo systemctl start milsurp
         sudo systemctl status milsurp
         sudo journalctl -u milsurp -f

  The app listens on 127.0.0.1 only; nginx terminates TLS on 443 and
  301-redirects port 80.

NEXT
