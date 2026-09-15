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
# **Runs as the milsurp account**, which already owns everything it touches:
# the snapshot directory is 0700 milsurp and config.yaml is 0600 milsurp. No
# other account can read either without loosening the permissions on the file
# holding the pepper, the JWT secret and the database password -- so this needs
# no privilege beyond the one the application already has. Root works too, and
# buys nothing.
#
# The key cannot live in milsurp's home: that is /opt/milsurp, which dpkg owns
# and an upgrade rewrites. /etc/milsurp is milsurp's own and survives upgrades,
# so the key and the known_hosts file go there.
#
#   sudo install -m 0755 offsite-backup.sh /usr/local/bin/milsurp-offsite
#
# =============================================================================
set -eu

# --- what you must set -------------------------------------------------------
# user@host and the directory on the far side. No trailing slash.
NAS_TARGET="${NAS_TARGET:-}"
# No default. A default is a guess about somebody else's filesystem, and the
# guess that was here -- a Synology-shaped /volume1/backups/milsurp -- is what
# a mistyped NAS_PATH silently fell back to: the job then reported "cannot
# reach" about a machine it had just reached. Refusing is the honest answer.
NAS_PATH="${NAS_PATH:-}"
# The key, somewhere the milsurp account can read and an upgrade will not
# touch. See deploy/cron/README.md.
SSH_KEY="${SSH_KEY:-/etc/milsurp/backup_key}"
# ssh wants somewhere to record the far side's host key, and milsurp's home is
# not writable by it. Without this the first connection fails in a way that
# reads as a network problem.
KNOWN_HOSTS="${KNOWN_HOSTS:-/etc/milsurp/known_hosts}"
SSH_PORT="${SSH_PORT:-22}"
# How many bundles to keep on the far side. Ten, matching the ten snapshots the
# application keeps locally: a fortnight of daily backups is long enough to
# notice something went wrong and still have the state from before it.
KEEP="${KEEP:-10}"
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
[ -n "$NAS_PATH" ] || die "NAS_PATH is not set (mind the leading N)."
[ -r "$CONFIG" ] || die "$CONFIG is not readable. Run as $APP_USER (or root)."
[ -x "$VENV_PY" ] || die "$VENV_PY is missing. Is the package installed?"
[ -r "$SSH_KEY" ] || die "$SSH_KEY is not readable; see deploy/cron/README.md."

touch "$KNOWN_HOSTS" 2>/dev/null || die "cannot write $KNOWN_HOSTS"
# -o Port=, not -p. The short flag means the port to ssh and "preserve times"
# to scp, whose port flag is -P -- so one option string shared between them had
# scp reading the port number as a filename: `scp: stat local "22"`.
# -o Port= means the same thing to both and cannot be got wrong again.
SSH_OPTS="-i $SSH_KEY -o Port=$SSH_PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
SSH_OPTS="$SSH_OPTS -o UserKnownHostsFile=$KNOWN_HOSTS"

# --- a fresh snapshot --------------------------------------------------------
# Rather than copying whatever is newest in the directory: if the scheduler's
# own backup has been failing, the newest file is stale and copying it off
# would be a backup of a backup that did not happen.
log "taking a snapshot"
# Already the right account under cron; runuser is only needed when something
# else (a person, root) is driving it, and runuser needs root to work at all.
if [ "$(id -un)" = "$APP_USER" ]; then
  env MILSURP_ENV=production MILSURP_CONFIG="$CONFIG" \
    "$VENV_PY" "$CLI" backup --force >/dev/null || die "the snapshot failed"
else
  runuser -u "$APP_USER" -- env MILSURP_ENV=production MILSURP_CONFIG="$CONFIG" \
    "$VENV_PY" "$CLI" backup --force >/dev/null || die "the snapshot failed"
fi

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
# Reaching the far side and being able to write there are two different
# failures and were reported as one: a mistyped NAS_PATH produced "cannot reach
# bceverly@..." about a machine that had answered perfectly well, which sends
# whoever reads it to debug the network.
# shellcheck disable=SC2086 # SSH_OPTS is a deliberate word list
ssh $SSH_OPTS "$NAS_TARGET" true >/dev/null 2>&1 || die "cannot reach $NAS_TARGET over ssh"
# shellcheck disable=SC2086
ssh $SSH_OPTS "$NAS_TARGET" "mkdir -p '$NAS_PATH'" \
  || die "reached $NAS_TARGET but cannot create $NAS_PATH there -- check the path"
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

# --- leave a record the application can see ----------------------------------
# The NAS is not visible from inside the app, so it cannot check whether these
# copies are still happening -- and a cron job that quietly stops is the whole
# reason this needs checking. What it *can* see is the local filesystem, so the
# stamp is written here, after the byte count matched, and nowhere else. Its
# age is what `milsurp canary` reports on.
#
# Written only on success, on purpose: a stamp touched at the start would age
# correctly while the copy failed every night.
STAMP="$SNAPSHOTS/.offsite-stamp"
printf '%s %s %s\n' "$(date -Is)" "$LOCAL_BYTES" "$NAS_TARGET:$NAS_PATH" > "$STAMP" \
  || log "WARNING: could not write $STAMP; the copy is safe but the age check is blind"

# --- prune the far side ------------------------------------------------------
# shellcheck disable=SC2086
ssh $SSH_OPTS "$NAS_TARGET" \
  "cd '$NAS_PATH' && ls -1t milsurp-*.tar.gz* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f" \
  || log "WARNING: could not prune old bundles (the new one is safely there)"

log "done"
