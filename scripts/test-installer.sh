#!/usr/bin/env bash
#
# Install the built .deb in a throwaway container and check it actually works.
#
#   scripts/test-installer.sh            (or: make installer-test)
#
# This is the first thing that runs the postinst for real: creating the service
# account, generating config.yaml with fresh secrets, and building the database
# schema from the Alembic chain. None of that is exercised by building the
# package, and all of it is what an administrator meets first.
#
# A container rather than this machine, because installing here would pull in
# nginx, start it, and take port 80 from whatever is already using it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

IMAGE="${IMAGE:-ubuntu:26.04}"
NAME="milsurp-installer-test-$$"

bold()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
info()  { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()    { printf '  \033[92m✓\033[0m %s\n' "$*"; }
fail()  { printf '  \033[91m✗\033[0m %s\n' "$*"; FAILED=$((FAILED + 1)); }
die()   { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

RUNTIME="$(command -v podman || command -v docker)" || die "neither podman nor docker is installed"
DEB="$(ls -t ../milsurp_*_amd64.deb 2>/dev/null | head -1)" || true
[ -n "${DEB:-}" ] || die "No .deb found. Run: make installer"

bold "Milsurp Monitor — installer test"
info "Runtime: $(basename "$RUNTIME")"
info "Image:   $IMAGE"
info "Package: $(basename "$DEB") ($(du -h "$DEB" | cut -f1))"

cleanup() { "$RUNTIME" rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

FAILED=0

bold "Installing in a clean $IMAGE container"
# --privileged is NOT used: the point is to prove this installs as an ordinary
# package would, not that it can be made to work with extra rights.
"$RUNTIME" run -d --name "$NAME" "$IMAGE" sleep 900 >/dev/null
"$RUNTIME" cp "$DEB" "$NAME:/tmp/milsurp.deb"

# `apt install ./file.deb` resolves the dependencies from the archive, which is
# what a PPA install does too -- so this exercises the real dependency set
# rather than a --force-depends shortcut.
"$RUNTIME" exec "$NAME" sh -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq /tmp/milsurp.deb 2>&1 | tail -30
' || die "apt install failed"

bold "Checking what the postinst actually did"

check() { # description, command
  if "$RUNTIME" exec "$NAME" sh -c "$2" >/dev/null 2>&1; then ok "$1"; else fail "$1"; fi
}

check "service account exists"            'getent passwd milsurp'
check "account has no login shell"        'getent passwd milsurp | grep -q nologin'
check "/etc/milsurp is 0750"              '[ "$(stat -c %a /etc/milsurp)" = 750 ]'
check "/etc/milsurp/images is 0700"       '[ "$(stat -c %a /etc/milsurp/images)" = 700 ]'
check "config.yaml created"               '[ -f /etc/milsurp/config.yaml ]'
check "config.yaml is 0600"               '[ "$(stat -c %a /etc/milsurp/config.yaml)" = 600 ]'
check "config.yaml owned by milsurp"      '[ "$(stat -c %U /etc/milsurp/config.yaml)" = milsurp ]'
check "jwt_secret was generated"          'grep -q "jwt_secret: \"[A-Za-z0-9_-]\{40,\}\"" /etc/milsurp/config.yaml'
check "password_pepper was generated"     'grep -q "password_pepper: \"[A-Za-z0-9_-]\{40,\}\"" /etc/milsurp/config.yaml'
check "no sample placeholder survived"    '! grep -qi "change-me\|replace-me\|CHANGEME" /etc/milsurp/config.yaml'
check "app tree NOT owned by milsurp"     '[ "$(stat -c %U /opt/milsurp/backend/run.py)" = root ]'
check "systemd unit installed"            '[ -f /usr/lib/systemd/system/milsurp.service ]'
check "nginx templates installed"         '[ -f /usr/share/milsurp/nginx/milsurp.conf ]'
check "venv python runs"                  '/opt/milsurp/.venv/bin/python -c "import sys; sys.exit(0)"'

bold "Checking the application actually imports and the schema was built"

check "fastapi imports"                   '/opt/milsurp/.venv/bin/python -c "import fastapi, sqlalchemy, alembic, psycopg, PIL, lxml, yaml, jwt, argon2"'
check "the app package imports"           'cd /opt/milsurp/backend && /opt/milsurp/.venv/bin/python -c "import app"'
check "database file was created"         '[ -f /etc/milsurp/milsurp.db ]'
check "database owned by milsurp"         '[ "$(stat -c %U /etc/milsurp/milsurp.db)" = milsurp ]'
check "schema is at the Alembic head" \
  'su -s /bin/sh milsurp -c "MILSURP_ENV=production /opt/milsurp/.venv/bin/python /opt/milsurp/scripts/dbupdate.py --check"'

bold "Checking an upgrade is safe"
# The property that matters on every `apt upgrade`: a second configure must not
# regenerate the secrets, or every upgrade would invalidate every session and
# every stored password hash.
BEFORE="$("$RUNTIME" exec "$NAME" sh -c 'grep jwt_secret /etc/milsurp/config.yaml')"
"$RUNTIME" exec "$NAME" sh -c 'DEBIAN_FRONTEND=noninteractive dpkg-reconfigure milsurp >/dev/null 2>&1 || dpkg --configure milsurp' >/dev/null 2>&1 || true
AFTER="$("$RUNTIME" exec "$NAME" sh -c 'grep jwt_secret /etc/milsurp/config.yaml')"
if [ "$BEFORE" = "$AFTER" ]; then ok "re-running postinst left the secrets alone"
else fail "re-running postinst CHANGED the secrets"; fi

bold "Checking removal"
"$RUNTIME" exec "$NAME" sh -c 'DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq milsurp' >/dev/null 2>&1 \
  && ok "apt remove succeeds" || fail "apt remove failed"
check "database survives a plain remove"  '[ -f /etc/milsurp/milsurp.db ]'

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  printf '  \033[1;92mAll installer checks passed.\033[0m\n\n'
else
  printf '  \033[1;91m%s check(s) failed.\033[0m\n\n' "$FAILED"
  exit 1
fi
