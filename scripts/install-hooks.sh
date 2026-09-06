#!/usr/bin/env bash
#
# Install the git hooks.
#
#   make install-hooks
#
# Copies .githooks/* into .git/hooks/. A plain file copy is used rather than
# `git config core.hooksPath` so that no git command is needed to install or
# uninstall them.
#
# Existing hooks that are not ours are backed up rather than overwritten.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SOURCE_DIR=".githooks"
TARGET_DIR=".git/hooks"
# Written into each installed hook so a later run can tell ours from a
# hand-written or third-party hook.
MARKER="# Milsurp Monitor — installed by scripts/install-hooks.sh"

ok()   { printf '  \033[92m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[93m!\033[0m %s\n' "$*"; }
info() { printf '  \033[96m→\033[0m %s\n' "$*"; }

if [ ! -d .git ]; then
  warn "Not a git repository — nothing to install."
  exit 0
fi

if [ ! -d "$SOURCE_DIR" ]; then
  warn "$SOURCE_DIR is missing — nothing to install."
  exit 0
fi

mkdir -p "$TARGET_DIR"

printf '\n\033[1mInstalling git hooks\033[0m\n'

installed=0
for source in "$SOURCE_DIR"/*; do
  [ -f "$source" ] || continue
  name="$(basename "$source")"
  target="$TARGET_DIR/$name"

  if [ -f "$target" ] && ! grep -qF "$MARKER" "$target" 2>/dev/null; then
    # Someone else's hook: keep it rather than silently replacing it.
    backup="$target.backup.$(date +%Y%m%d%H%M%S)"
    mv "$target" "$backup"
    warn "existing $name backed up to $(basename "$backup")"
  fi

  # The marker goes in as a second line so the shebang stays first.
  {
    head -1 "$source"
    printf '%s\n' "$MARKER"
    tail -n +2 "$source"
  } > "$target"
  chmod +x "$target"
  ok "$name"
  installed=$((installed + 1))
done

printf '\n'
if [ "$installed" -eq 0 ]; then
  warn "No hooks found in $SOURCE_DIR."
  exit 0
fi

cat <<'SUMMARY'
  pre-commit  blocks the commit on ANY lint finding, including black
              reporting that it would reformat a file
  pre-push    the same lint gate, so a push cannot land code that a
              local commit --no-verify slipped past. It deliberately does
              NOT run the test suites: they take minutes, they would run
              again for every tag push, and CI runs them on every push.

  Bypass in an emergency:  git commit --no-verify  /  git push --no-verify
  Uninstall:               rm .git/hooks/pre-commit .git/hooks/pre-push

SUMMARY
