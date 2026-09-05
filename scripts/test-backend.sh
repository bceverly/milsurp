#!/usr/bin/env bash
#
# Backend test suite with a hard coverage floor.
#
#   make test-backend
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || { echo "No virtualenv — run 'make install-dev'." >&2; exit 1; }

printf '\n\033[1mBackend tests\033[0m (pytest, minimum 65%% coverage)\n\n'

# The suite builds its own throwaway database from a temp config; MILSURP_CONFIG
# is unset so a developer's real config.yaml can never be picked up and, worse,
# written to.
unset MILSURP_CONFIG || true
export MILSURP_ENV=dev

cd backend
"$REPO_ROOT/$VENV_PY" -m pytest "$@"
STATUS=$?
cd "$REPO_ROOT"

if [ "$STATUS" -eq 0 ]; then
  printf '\n\033[92m✓ Backend tests passed.\033[0m\n'
  # Refresh the README badge from the run that just finished.
  "$VENV_PY" scripts/coverage_badges.py --backend-only --quiet || true
fi
exit "$STATUS"
