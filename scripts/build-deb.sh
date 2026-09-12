#!/usr/bin/env bash
#
# Build the Milsurp Monitor .deb.
#
#   scripts/build-deb.sh              binary package, signed if a key is set
#   scripts/build-deb.sh --source     source package, for a Launchpad upload
#   scripts/build-deb.sh --sbuild     build in a clean offline chroot
#
# The generated debian/changelog is written from the project version rather
# than maintained by hand: the version lives in pyproject.toml and
# backend/app/__init__.py already, and a third copy would be a third thing to
# forget during a release.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE=binary
case "${1:-}" in
  --source) MODE=source ;;
  --sbuild) MODE=sbuild ;;
  "")       ;;
  *)        echo "Unknown option: $1" >&2; exit 2 ;;
esac

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[93m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
[ -n "$VERSION" ] || die "Could not read the version from pyproject.toml"

# Launchpad builds per-series and rejects an upload whose changelog names a
# series it does not know. The local release is the right default because the
# whole point of strategy B -- vendored wheels -- is that the build machine and
# the target run the same Python ABI.
SERIES="${SERIES:-$(. /etc/os-release && echo "${VERSION_CODENAME:-}")}"
[ -n "$SERIES" ] || die "Could not determine the Ubuntu series; set SERIES=<codename>"

bold "Milsurp Monitor — Debian package"
info "Version: $VERSION"
info "Series:  $SERIES"
info "Mode:    $MODE"

# ---------------------------------------------------------------------------
# The two things a Launchpad builder cannot produce for itself
# ---------------------------------------------------------------------------
[ -d vendor/wheels ] || die "vendor/wheels is missing. Run: make vendor"
[ -f frontend/dist/index.html ] || die "frontend/dist is missing. Run: make build-frontend"
ok "$(find vendor/wheels -name '*.whl' | wc -l) vendored wheels, frontend bundle present"

# ---------------------------------------------------------------------------
# debian/changelog, generated
# ---------------------------------------------------------------------------
: "${DEBFULLNAME:?set DEBFULLNAME in your shell (must match the signing key UID)}"
: "${DEBEMAIL:?set DEBEMAIL in your shell (must match the signing key UID)}"

# ~ sorts *before* everything, so a rebuild for a newer series always upgrades
# cleanly over the same version built for an older one.
DEB_VERSION="${VERSION}~${SERIES}1"

cat > debian/changelog <<CHANGELOG
milsurp ($DEB_VERSION) $SERIES; urgency=medium

  * Release $VERSION.

 -- $DEBFULLNAME <$DEBEMAIL>  $(date -R)
CHANGELOG
ok "debian/changelog -> $DEB_VERSION"

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
SIGN=()
if [ -n "${DEBSIGN_KEYID:-}" ]; then
  # Explicit rather than letting debsign match on DEBEMAIL: this machine has
  # two secret keys carrying the same address, and picking the wrong one
  # produces an upload Launchpad rejects for reasons it does not explain.
  SIGN=("-k${DEBSIGN_KEYID}")
  info "Signing with ${DEBSIGN_KEYID}"
else
  SIGN=("-us" "-uc")
  warn "DEBSIGN_KEYID is not set — building unsigned (fine locally, not for Launchpad)"
fi

case "$MODE" in
  binary)
    bold "dpkg-buildpackage -b"
    dpkg-buildpackage -b "${SIGN[@]}"
    ;;
  source)
    bold "dpkg-buildpackage -S"
    # -sa forces the full source into the upload. Launchpad needs it for the
    # first upload of a version, and the vendored wheels live in it.
    dpkg-buildpackage -S -sa "${SIGN[@]}"
    ;;
  sbuild)
    bold "sbuild — clean chroot, no network"
    command -v sbuild >/dev/null || die "sbuild is not installed"
    # The unshare backend rather than schroot: it needs no root, no sbuild
    # group membership (which only takes effect after a re-login) and no
    # /etc/schroot entry. It is sbuild's modern default and the least
    # machinery for the same answer.
    IMAGE="$HOME/.cache/sbuild/${SERIES}-amd64.tar.zst"
    if [ ! -f "$IMAGE" ]; then
      warn "No unshare image at $IMAGE"
      printf '\n  Create it once with:\n\n'
      printf '    sudo apt install mmdebstrap uidmap\n'
      printf '    mkdir -p ~/.cache/sbuild\n'
      printf '    mmdebstrap --variant=buildd --arch=amd64 \\\n'
      printf '      --components=main,universe %s \\\n' "$SERIES"
      printf '      %s \\\n' "$IMAGE"
      printf '      http://archive.ubuntu.com/ubuntu\n\n'
      die "sbuild image missing"
    fi
    # This is the real test of strategy B. sbuild installs only Build-Depends
    # into a clean chroot and builds with no network, which is exactly what a
    # Launchpad builder does -- so a green run here means a green run there,
    # and a red one is three minutes rather than a failed upload.
    sbuild --chroot-mode=unshare --dist="$SERIES" --no-run-lintian --build-dir=..
    ;;
esac

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
bold "Built"
for f in ../milsurp_*"${DEB_VERSION}"*; do
  [ -e "$f" ] || continue
  printf '    %-58s %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done

if [ "$MODE" = binary ] && command -v lintian >/dev/null; then
  bold "lintian"
  # The venv is third-party code with its own conventions; lintian's Python
  # and shebang checks have nothing useful to say about it and would drown
  # anything that matters.
  # Suppressions are all consequences of shipping a virtualenv, which lintian
  # has no concept of: every wheel is an "embedded library" and the .dist-info
  # directories look like stray licence files. dir-or-file-in-opt is the one
  # deliberate policy departure -- /opt is reserved for software that does not
  # come from the distribution, which is exactly what a PPA is, and it is where
  # install-production.sh and the systemd unit have always put this. It would
  # have to move to /usr/lib/milsurp before this could go to Debian proper.
  # unusual-interpreter is the venv working as intended: every console script
  # names /opt/milsurp/.venv/bin/python, which is the whole point of the
  # shebang rewrite in debian/rules. Anything outside the venv is still
  # unstripped-binary-or-object is likewise inherent: dh_strip is excluded
  # from the venv, so the wheels' extensions keep whatever the wheel builders
  # shipped. reported.
  lintian --tag-display-limit 0 \
    --suppress-tags embedded-library,extra-license-file,national-encoding,\
embedded-javascript-library,package-contains-documentation-outside-usr-share-doc,\
dir-or-file-in-opt,unusual-interpreter,unstripped-binary-or-object,\
script-not-executable,shared-library-lacks-prerequisites \
    ../milsurp_"${DEB_VERSION}"_*.deb || warn "lintian reported issues (see above)"
fi

printf '\n'
info "Install it locally with:   sudo apt install ../milsurp_${DEB_VERSION}_amd64.deb"
info "Upload to Launchpad with:  dput ppa:<user>/<ppa> ../milsurp_${DEB_VERSION}_source.changes"
printf '\n'
