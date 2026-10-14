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

printf '\n\033[1mBackend tests\033[0m (pytest, minimum 83%% coverage)\n\n'

# Six of these tests need a real PostgreSQL and skip without one. If this
# machine has the test database, use it rather than making somebody remember a
# separate command -- derived from config.yaml, so it is the same role and
# password, and always <name>_test rather than the configured database itself.
#
# Only when it answers. An unreachable URL is a hard error by design (a wrong
# password should not print six tracebacks), and that would be the wrong
# outcome for a machine that simply has no PostgreSQL.
export MILSURP_ENV=dev
if [ -z "${MILSURP_TEST_POSTGRES_URL:-}" ]; then
  MILSURP_TEST_POSTGRES_URL="$("$VENV_PY" scripts/test-postgres-url.py --if-reachable 2>/dev/null || true)"
  export MILSURP_TEST_POSTGRES_URL
fi
if [ -n "${MILSURP_TEST_POSTGRES_URL:-}" ]; then
  printf '  PostgreSQL: %s\n\n' "$(echo "$MILSURP_TEST_POSTGRES_URL" | sed 's,//[^@]*@,//,')"
else
  printf '  PostgreSQL: none reachable — the six schema tests will skip (make test-postgres)\n\n'
fi

# The suite builds its own throwaway database from a temp config; MILSURP_CONFIG
# is unset so a developer's real config.yaml can never be picked up and, worse,
# written to.
unset MILSURP_CONFIG || true

# One worker per core (pytest-xdist), as the sysmanage projects run theirs:
# about 4m40s on eight cores where one ran the same 5,672 tests on about 16
# minutes of CPU (2026-10-14). Each worker builds its own temporary database
# (conftest's session fixtures are per worker), and --dist=loadfile keeps a
# file's tests on one worker -- the six PostgreSQL schema tests share a real
# database and live in one file. MILSURP_TEST_WORKERS sets the count (0 runs
# in this process, as before); an -n of your own wins. A run of named files
# stays in one process: eight workers starting cost more than they save on a
# file or two (8.5s against 3.9s for one).
WORKERS="${MILSURP_TEST_WORKERS:-auto}"
for arg in "$@"; do
  case "$arg" in
    *.py | *.py::* | tests/* | */tests/*) WORKERS="${MILSURP_TEST_WORKERS:-0}" ;;
  esac
done
PARALLEL=()
case " $* " in
  *" -n "* | *" -n="* | *" --numprocesses"* | *" -p no:xdist "*) ;;
  *)
    if [ "$WORKERS" != "0" ] && [ "$WORKERS" != "1" ]; then
      PARALLEL=(-n "$WORKERS" --dist=loadfile)
      printf '  Workers: %s\n\n' "$([ "$WORKERS" = auto ] && nproc || echo "$WORKERS")"
    fi
    ;;
esac

cd backend
"$REPO_ROOT/$VENV_PY" -m pytest "${PARALLEL[@]}" "$@"
STATUS=$?
cd "$REPO_ROOT"

if [ "$STATUS" -eq 0 ]; then
  printf '\n\033[92m✓ Backend tests passed.\033[0m\n'
  # Refresh the README badge from the run that just finished.
  "$VENV_PY" scripts/coverage_badges.py --backend-only --quiet || true
fi
exit "$STATUS"
