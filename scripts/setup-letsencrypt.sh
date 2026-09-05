#!/usr/bin/env bash
#
# Obtain and install a Let's Encrypt TLS certificate for milsurpmonitor.com.
#
#   sudo scripts/setup-letsencrypt.sh
#   sudo DOMAIN=example.com EMAIL=you@example.com scripts/setup-letsencrypt.sh
#
# Run this AFTER scripts/install-production.sh, and only once DNS for the domain
# resolves to this machine — the HTTP-01 challenge needs Let's Encrypt to reach
# http://<domain>/.well-known/acme-challenge/ from the public internet.
#
# Safe to re-run: certbot renews or reinstalls rather than duplicating.
set -euo pipefail

DOMAIN="${DOMAIN:-milsurpmonitor.com}"
WWW_DOMAIN="${WWW_DOMAIN:-www.$DOMAIN}"
EMAIL="${EMAIL:-}"
APP_NAME="milsurp"
WEBROOT="/var/www/certbot"
STAGING="${STAGING:-0}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[93m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo: sudo scripts/setup-letsencrypt.sh"

bold "Let's Encrypt certificate for $DOMAIN"

if [ -z "$EMAIL" ]; then
  # Let's Encrypt uses this only for expiry warnings and urgent notices.
  read -rp "  Email address for expiry notices: " EMAIL
  [ -n "$EMAIL" ] || die "An email address is required."
fi

# ---------------------------------------------------------------------------
bold "1. certbot"
if command -v certbot >/dev/null 2>&1; then
  ok "certbot $(certbot --version 2>&1 | awk '{print $2}') already installed."
else
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq certbot python3-certbot-nginx
  ok "certbot installed."
fi

# ---------------------------------------------------------------------------
bold "2. DNS check"
SERVER_IP="$(curl -fsS --max-time 10 https://api.ipify.org || echo '')"
RESOLVED="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || echo '')"
if [ -z "$RESOLVED" ]; then
  die "$DOMAIN does not resolve. Point an A record at this machine, wait for
       propagation, and re-run."
elif [ -n "$SERVER_IP" ] && [ "$RESOLVED" != "$SERVER_IP" ]; then
  warn "$DOMAIN resolves to $RESOLVED but this machine appears to be $SERVER_IP."
  warn "If that is a proxy (Cloudflare), disable proxying for the challenge."
  read -rp "  Continue anyway? [y/N] " reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "Aborted."
else
  ok "$DOMAIN resolves to $RESOLVED."
fi

# ---------------------------------------------------------------------------
bold "3. ACME challenge webroot"
install -d -m 0755 "$WEBROOT/.well-known/acme-challenge"
chown -R www-data:www-data "$WEBROOT"
ok "$WEBROOT ready."

# nginx must be serving plain HTTP for the domain, with the challenge path
# exempt from the HTTPS redirect. The bootstrap config does exactly that.
if [ ! -f "/etc/nginx/sites-available/$APP_NAME" ]; then
  die "nginx is not configured for this app. Run scripts/install-production.sh first."
fi

if ! nginx -t >/dev/null 2>&1; then
  warn "The current nginx config does not pass a test; installing the HTTP-only
       bootstrap config so the challenge can be served."
  sed "s/milsurpmonitor\.com/$DOMAIN/g" \
    "$REPO_ROOT/deploy/nginx/milsurp-bootstrap.conf" > "/etc/nginx/sites-available/$APP_NAME"
  nginx -t || die "nginx config is still invalid."
fi
systemctl reload nginx
ok "nginx is serving HTTP for the challenge."

# ---------------------------------------------------------------------------
bold "4. Requesting the certificate"
CERTBOT_ARGS=(
  certonly --webroot -w "$WEBROOT"
  -d "$DOMAIN"
  --email "$EMAIL"
  --agree-tos --no-eff-email
  --non-interactive
  --keep-until-expiring
)

# Include www only when it actually resolves; a non-resolving name in the same
# request fails the whole certificate.
if getent hosts "$WWW_DOMAIN" >/dev/null 2>&1; then
  CERTBOT_ARGS+=(-d "$WWW_DOMAIN")
  info "Including $WWW_DOMAIN."
else
  warn "$WWW_DOMAIN does not resolve — requesting $DOMAIN only."
fi

if [ "$STAGING" = "1" ]; then
  # Let's Encrypt rate-limits real certificates hard (5 failures per hour).
  warn "STAGING=1 — issuing an untrusted test certificate."
  CERTBOT_ARGS+=(--staging)
fi

certbot "${CERTBOT_ARGS[@]}"
ok "Certificate issued for $DOMAIN."

# ---------------------------------------------------------------------------
bold "5. Diffie-Hellman parameters"
if [ -f /etc/nginx/dhparam.pem ]; then
  ok "dhparam already present."
else
  info "Generating 2048-bit DH parameters (this takes a minute)…"
  openssl dhparam -out /etc/nginx/dhparam.pem 2048 2>/dev/null
  chmod 644 /etc/nginx/dhparam.pem
  ok "Generated /etc/nginx/dhparam.pem."
fi

# ---------------------------------------------------------------------------
bold "6. Installing the TLS nginx config"
sed "s/milsurpmonitor\.com/$DOMAIN/g" \
  "$REPO_ROOT/deploy/nginx/milsurp.conf" > "/etc/nginx/sites-available/$APP_NAME"
ln -sf "/etc/nginx/sites-available/$APP_NAME" "/etc/nginx/sites-enabled/$APP_NAME"
nginx -t || die "nginx rejected the TLS config; the previous config is still active."
systemctl reload nginx
ok "TLS is live: https://$DOMAIN"

# ---------------------------------------------------------------------------
bold "7. Automatic renewal"
# The certbot package ships a systemd timer that runs twice daily. It only needs
# a deploy hook so nginx picks up the renewed certificate.
install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK'
#!/bin/sh
# Reload nginx after a successful renewal so the new certificate takes effect.
systemctl reload nginx
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

systemctl enable --now certbot.timer >/dev/null 2>&1 || true
if systemctl is-active --quiet certbot.timer; then
  ok "certbot.timer is active — renewal runs automatically."
else
  warn "certbot.timer is not active. Add a cron entry:"
  warn "  0 3 * * * certbot renew --quiet"
fi

info "Testing renewal (dry run)…"
certbot renew --dry-run --quiet && ok "Renewal dry run passed."

# ---------------------------------------------------------------------------
bold "Done."
cat <<NEXT

  https://$DOMAIN is live. Port 80 now 301-redirects to 443.

  Update the public URL used in digest emails:
    sudo -e /etc/milsurp/config.yaml
      server:
        production:
          public_url: https://$DOMAIN

  Then restart:
    sudo systemctl restart milsurp

  Certificate details:  certbot certificates
  Renewal is automatic via certbot.timer.

NEXT
