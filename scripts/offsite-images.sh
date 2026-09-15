#!/bin/sh
# =============================================================================
# Milsurp Monitor — mirror the photo store to the NAS.
#
# Separate from offsite-backup.sh, and on a slower clock, because this is a
# different kind of thing. The database and the config are small, irreplaceable
# and needed nightly; the images are forty gigabytes and **re-downloadable** --
# `milsurp fetch-photos` rebuilds the store from the URLs the database already
# holds, given time and the vendors' patience.
#
# So this is a convenience rather than a safety net: it turns "a week of
# re-fetching forty thousand photographs from twenty-eight shops" into a
# restore. Worth having, not worth running hourly.
#
# rsync rather than a tarball: after the first pass it sends only what changed,
# which on a store that grows by a few hundred files a day is seconds.
#
#   sudo install -m 0755 offsite-images.sh /usr/local/sbin/milsurp-offsite-images
#
# =============================================================================
set -eu

NAS_TARGET="${NAS_TARGET:-}"
NAS_PATH="${NAS_PATH:-/volume1/backups/milsurp-images}"
SSH_KEY="${SSH_KEY:-/root/.ssh/id_milsurp_backup}"
SSH_PORT="${SSH_PORT:-22}"
IMAGES="${IMAGES:-/etc/milsurp/images}"

log() { printf '%s milsurp-offsite-images: %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[ -n "$NAS_TARGET" ] || die "NAS_TARGET is not set."
[ -d "$IMAGES" ] || die "$IMAGES is not a directory."
[ -r "$SSH_KEY" ] || die "$SSH_KEY is not readable; run as root."

log "mirroring $(du -sh "$IMAGES" | cut -f1) from $IMAGES"
# --delete so a pruned image goes from the mirror too: the point is a copy of
# the store as it is, not an archive of everything it has ever held.
# --partial so an interrupted forty-gigabyte first pass resumes rather than
# starting over, which on a home connection is the difference between finishing
# and not.
rsync -a --delete --partial --human-readable \
  -e "ssh -i $SSH_KEY -p $SSH_PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$IMAGES/" "$NAS_TARGET:$NAS_PATH/" \
  || die "rsync failed"

log "done"
