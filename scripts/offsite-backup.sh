#!/bin/sh
# =============================================================================
# Milsurp Monitor — copy a database snapshot and the config off this machine.
#
# The application already takes a daily snapshot and keeps ten of them. Ten
# backups on the same disk as the database survive a bad UPDATE, which is what
# they were written for, and not a lost disk — which is what this is for.
#
# **The configuration goes with the snapshot, and that is the point.**
# config.yaml holds `security.password_pepper`, which is HMAC'd into every
# password before Argon2 and is stored nowhere else. A database restored onto a
# rebuilt machine without that exact string has no working logins — not the
# admin's, not anybody's. A database-only backup looks complete and is not.
#
# Runs under cron as root, because the snapshot directory is 0700 milsurp and
# config.yaml is 0600. Safe to run repeatedly: it takes a fresh snapshot,
# copies, and prunes, and any step failing stops it with a non-zero exit.
#
#   sudo install -m 0755 offsite-backup.sh /usr/local/sbin/milsurp-offsite
#
# =============================================================================
set -eu

# --- what you must set -------------------------------------------------------
# user@host and the directory on the far side. No trailing slash.
NAS_TARGET="${NAS_TARGET:-}"
NAS_PATH="${NAS_PATH:-/volume1/backups/milsurp}"
# The key root uses to get there. See the setup notes at the bottom.
SSH_KEY="${SSH_KEY:-/root/.ssh/id_milsurp_backup}"
SSH_PORT="${SSH_PORT:-22}"
# How many bundles to keep on the far side.
KEEP="${KEEP:-30}"
# Optional. With a passphrase set the bundle is encrypted before it leaves,
# which matters because it carries the pepper, the JWT secret and the database
# password in clear text otherwise. scp protects it in flight and nothing
# protects it at rest on the NAS.
GPG_PASSPHRASE_FILE="${GPG_PASSPHRASE_FILE:-}"

# --- where things are --------------------------------------------------------
APP_USER=milsurp
CONFIG=/etc/milsurp/config.yaml
SNAPSHOTS=/etc/milsurp/backups
VENV_PY=/opt/milsurp/.venv/bin/python
CLI=/opt/milsurp/backend/cli.py

log() { printf '%s milsurp-offsite: %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[ -n "$NAS_TARGET" ] || die "NAS_TARGET is not set. Edit this script, or export it."
[ -r "$CONFIG" ] || die "$CONFIG is not readable. Run this as root."
[ -x "$VENV_PY" ] || die "$VENV_PY is missing. Is the package installed?"
[ -r "$SSH_KEY" ] || die "$SSH_KEY is not readable; see the setup notes in this script."

SSH_OPTS="-i $SSH_KEY -p $SSH_PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

# --- a fresh snapshot --------------------------------------------------------
# Rather than copying whatever is newest in the directory: if the scheduler's
# own backup has been failing, the newest file is stale and copying it off
# would be a backup of a backup that did not happen.
log "taking a snapshot"
runuser -u "$APP_USER" -- env MILSURP_ENV=production MILSURP_CONFIG="$CONFIG" \
  "$VENV_PY" "$CLI" backup --force >/dev/null || die "the snapshot failed"

NEWEST="$(ls -1t "$SNAPSHOTS"/milsurp-*.dump "$SNAPSHOTS"/milsurp-*.db 2>/dev/null | head -1 || true)"
[ -n "$NEWEST" ] || die "no snapshot found in $SNAPSHOTS"

# Refuse a snapshot that is not from this run. A stale file here means the
# backup above reported success and wrote nothing, which is worth stopping for.
case "$(find "$NEWEST" -mmin -10 2>/dev/null)" in
  "") die "$NEWEST is older than ten minutes; the snapshot did not run" ;;
esac
log "snapshot $(basename "$NEWEST") ($(du -h "$NEWEST" | cut -f1))"

# --- bundle it ---------------------------------------------------------------
STAMP="$(date -u +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
# The bundle carries secrets; nobody else on this machine needs to read it.
chmod 0700 "$WORK"
trap 'rm -rf "$WORK"' EXIT INT TERM

BUNDLE="$WORK/milsurp-$STAMP.tar.gz"
tar -czf "$BUNDLE" \
  -C "$SNAPSHOTS" "$(basename "$NEWEST")" \
  -C /etc/milsurp config.yaml
chmod 0600 "$BUNDLE"

if [ -n "$GPG_PASSPHRASE_FILE" ]; then
  [ -r "$GPG_PASSPHRASE_FILE" ] || die "GPG_PASSPHRASE_FILE is set but unreadable"
  log "encrypting"
  gpg --batch --yes --quiet --symmetric --cipher-algo AES256 \
      --passphrase-file "$GPG_PASSPHRASE_FILE" --output "$BUNDLE.gpg" "$BUNDLE" \
    || die "encryption failed"
  rm -f "$BUNDLE"
  BUNDLE="$BUNDLE.gpg"
fi

# --- send it -----------------------------------------------------------------
log "sending $(basename "$BUNDLE") ($(du -h "$BUNDLE" | cut -f1)) to $NAS_TARGET:$NAS_PATH"
# shellcheck disable=SC2086 # SSH_OPTS is a deliberate word list
ssh $SSH_OPTS "$NAS_TARGET" "mkdir -p '$NAS_PATH'" || die "cannot reach $NAS_TARGET"
# shellcheck disable=SC2086
scp $SSH_OPTS -q "$BUNDLE" "$NAS_TARGET:$NAS_PATH/" || die "the copy failed"

# Read it back. A copy that reported success and wrote a truncated file is the
# failure a backup script exists to not have, and comparing sizes costs one
# round trip.
LOCAL_BYTES="$(wc -c < "$BUNDLE")"
# shellcheck disable=SC2086
REMOTE_BYTES="$(ssh $SSH_OPTS "$NAS_TARGET" "wc -c < '$NAS_PATH/$(basename "$BUNDLE")'" 2>/dev/null | tr -d ' ')"
[ "$LOCAL_BYTES" = "$REMOTE_BYTES" ] \
  || die "copied $LOCAL_BYTES bytes and the far side has ${REMOTE_BYTES:-none}"
log "verified $LOCAL_BYTES bytes on the far side"

# --- prune the far side ------------------------------------------------------
# shellcheck disable=SC2086
ssh $SSH_OPTS "$NAS_TARGET" \
  "cd '$NAS_PATH' && ls -1t milsurp-*.tar.gz* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f" \
  || log "WARNING: could not prune old bundles (the new one is safely there)"

log "done"
