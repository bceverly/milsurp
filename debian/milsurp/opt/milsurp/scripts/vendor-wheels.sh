#!/usr/bin/env bash
#
# Download every runtime dependency as a wheel into vendor/wheels/.
#
# This is the step that lets the Debian package build on a Launchpad builder,
# which has no network access: whatever is not in the source package cannot be
# fetched, so it all has to be here first.
#
#   scripts/vendor-wheels.sh          (or: make vendor)
#
# Run it on the SAME Ubuntu release you are building for. Wheels carry the
# Python ABI and the platform in their filenames -- cp314-cp314-manylinux...
# -- and a wheel built for another interpreter will not install. Ubuntu 26.04
# ships Python 3.14, which is what the package depends on.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/vendor/wheels"
REQ="$ROOT/backend/requirements.txt"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$REQ" ] || die "No $REQ"

bold "Vendoring runtime dependencies for offline build"
info "Python:  $(python3 -V)"
info "Target:  $DEST"

rm -rf "$DEST"
mkdir -p "$DEST"

# --only-binary=:all: is the point of the exercise. Without it pip happily
# downloads an sdist for anything with no wheel, and the builder would then
# need a compiler, the headers and -- for some packages -- the network again.
# If this fails, the named package has no wheel for this platform and wants
# solving here, where there is a network, rather than on the builder.
python3 -m pip download \
  --requirement "$REQ" \
  --dest "$DEST" \
  --only-binary=:all: \
  --quiet

COUNT=$(find "$DEST" -name '*.whl' | wc -l)
SIZE=$(du -sh "$DEST" | cut -f1)
ok "$COUNT wheels, $SIZE"

# A source distribution in here means --only-binary let something through, or
# somebody added one by hand. Either way the builder cannot use it.
if find "$DEST" -name '*.tar.gz' -o -name '*.zip' | grep -q .; then
  die "vendor/wheels contains a source distribution; the offline build will fail"
fi

printf '\n'
info "Committed? No -- vendor/ is gitignored. These are rebuilt by 'make vendor'"
info "and packed into the source package by 'make deb'."
