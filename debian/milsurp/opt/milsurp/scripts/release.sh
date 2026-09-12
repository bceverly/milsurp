#!/usr/bin/env bash
#
# Cut a release version.
#
#   make release                      bump the last digit of the highest tag
#   make release VERSION=1.2.3.4      set an explicit version
#
# Versions are four-part and tags are prefixed with a lowercase "v", e.g.
# v1.2.3.4. With no tags in the repository at all, the first release is
# v1.0.0.0 rather than a bump of nothing.
#
# What it does, in order, after a single confirmation:
#   1. Works out the next version and asks you to confirm it.
#   2. Writes that version into the project's version files.
#   3. Commits and pushes that change.
#   4. Creates an annotated tag and pushes the tag.
#
# Pushing the tag is what triggers the release build, so the confirmation in
# step 1 is the point of no return — answer "n" and nothing at all happens.
#
# Commit and tag signing follow your git config (commit.gpgsign / tag.gpgsign);
# this script does not override them.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

#: Used when the repository has no version tags yet.
FIRST_VERSION="1.0.0.0"
VERSION_PATTERN='^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'

# Colors as variables: a heredoc does not interpret backslash escapes, but it
# does expand variables, and $'...' yields the real escape byte.
GREEN=$'\033[1;92m'
RESET=$'\033[0m'

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  \033[96m→\033[0m %s\n' "$*"; }
ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[93m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[91m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is not installed."
[ -d .git ] || die "Not a git repository."

# ---------------------------------------------------------------------------
# Work out the version
# ---------------------------------------------------------------------------
bold "Release"

# `sort -V` orders version strings numerically, so v1.10.0.0 correctly sorts
# above v1.9.0.0 — a plain lexical sort would get that backwards.
LATEST="$(git tag -l 'v*' 2>/dev/null \
          | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' \
          | sed 's/^v//' \
          | sort -V \
          | tail -1)"

EXPLICIT="${VERSION:-}"

if [ -n "$EXPLICIT" ]; then
  # Tolerate a leading "v" even though the documented form omits it.
  EXPLICIT="${EXPLICIT#v}"
  echo "$EXPLICIT" | grep -qE "$VERSION_PATTERN" \
    || die "VERSION must look like 1.2.3.4 (four numbers), got '${VERSION}'."
  NEXT="$EXPLICIT"
  if [ -n "$LATEST" ]; then
    info "Current version:  v$LATEST"
  else
    info "Current version:  (no tags yet)"
  fi
  info "Setting version:  v$NEXT  (explicit)"
elif [ -z "$LATEST" ]; then
  NEXT="$FIRST_VERSION"
  info "No version tags found in this repository."
  info "First release:    v$NEXT"
else
  # Bump the last of the four components.
  IFS='.' read -r MAJOR MINOR PATCH BUILD <<< "$LATEST"
  NEXT="${MAJOR}.${MINOR}.${PATCH}.$((BUILD + 1))"
  info "Current version:  v$LATEST"
  info "Next version:     v$NEXT"
fi

TAG="v$NEXT"

# Re-using a tag would move a release that may already have been built and
# published, so say so plainly rather than silently overwriting.
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  warn "Tag $TAG already exists."
  warn "Delete it first if you really mean to move it:"
  warn "    git tag -d $TAG && git push --delete origin $TAG"
fi

# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------
printf '\n'
printf '  Release as \033[1;96m%s\033[0m? [y/N] ' "$TAG"
read -r REPLY
case "$REPLY" in
  y | Y | yes | YES | Yes) ;;
  *)
    printf '\n'
    info "Stopped. Nothing was changed."
    exit 0
    ;;
esac

# ---------------------------------------------------------------------------
# Write the version into the project
# ---------------------------------------------------------------------------
bold "Updating version files"

# npm requires a three-part semver, so package.json gets the first three
# components. Everything else carries the full four-part version.
NPM_VERSION="${NEXT%.*}"

python3 - "$NEXT" "$NPM_VERSION" <<'PY'
import pathlib
import re
import sys

version, npm_version = sys.argv[1], sys.argv[2]
# The surrounding script cd's to the repository root before running this.
root = pathlib.Path.cwd()

edits = [
    (
        root / "backend" / "app" / "__init__.py",
        r'(^__version__\s*=\s*)"[^"]*"',
        rf'\g<1>"{version}"',
        version,
    ),
    (
        root / "pyproject.toml",
        r'(^version\s*=\s*)"[^"]*"',
        rf'\g<1>"{version}"',
        version,
    ),
    (
        root / "frontend" / "package.json",
        r'(^\s*"version":\s*)"[^"]*"',
        rf'\g<1>"{npm_version}"',
        npm_version,
    ),
]

problems = []
for path, pattern, replacement, shown in edits:
    if not path.is_file():
        problems.append(f"missing file: {path}")
        continue
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count == 0:
        problems.append(f"no version field found in {path}")
        continue
    if updated == text:
        print(f"  = already {shown}: {path.name}")
        continue
    path.write_text(updated, encoding="utf-8")
    print(f"  \033[92m\u2713\033[0m {path.name} -> {shown}")

if problems:
    for line in problems:
        print(f"  \033[91m\u2717\033[0m {line}")
    sys.exit(1)
PY
# shellcheck disable=SC2181  # the heredoc above is the command being checked
if [ $? -ne 0 ]; then
  die "Could not write the version into every file; nothing was committed."
fi

# ---------------------------------------------------------------------------
# Commit, push, tag, push the tag
# ---------------------------------------------------------------------------
bold "Publishing"

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
[ -n "$BRANCH" ] && [ "$BRANCH" != "HEAD" ] \
  || die "Not on a branch (detached HEAD?); cannot push."

git remote get-url origin >/dev/null 2>&1 \
  || die "No 'origin' remote configured; nothing to push to."

git add backend/app/__init__.py pyproject.toml frontend/package.json \
  || die "Could not stage the version files."

# An empty diff means the files already carried this version, which is fine on
# a re-run; skip the commit rather than failing on "nothing to commit".
if git diff --cached --quiet; then
  warn "Version files already at $NEXT — nothing to commit."
else
  git commit -m "Release $TAG" || die "Commit failed."
  ok "Committed the version bump."
fi

info "Pushing $BRANCH to origin…"
git push origin "$BRANCH" || die "Push failed; the tag was not created."
ok "Pushed $BRANCH."

info "Tagging $TAG…"
git tag -a "$TAG" -m "Release $TAG" || die "Could not create tag $TAG."
ok "Created tag $TAG."

info "Pushing tag $TAG…"
if ! git push origin "$TAG"; then
  # Leave the local tag in place so it can be retried or inspected.
  die "Could not push the tag. The local tag $TAG still exists; delete it with
       'git tag -d $TAG' if you want to start over."
fi
ok "Pushed tag $TAG."

cat <<NEXT_STEPS

  ────────────────────────────────────────────────────────────────
   ${GREEN}Released ${TAG}${RESET}

   Pushing the tag triggers the Release workflow, which builds the Debian
   package, installs it in a clean container to prove it works, and only
   then uploads it to the Launchpad PPA. Watch it with:

       gh run watch

   Launchpad builds asynchronously after the upload, so a green workflow
   means "accepted", not "published". The PPA's own page is the last word:

       https://launchpad.net/~bceverly/+archive/ubuntu/milsurp

   To undo, before anything consumes the tag:

       git push --delete origin ${TAG}
       git tag -d ${TAG}
  ────────────────────────────────────────────────────────────────

NEXT_STEPS
