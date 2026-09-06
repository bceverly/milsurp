#!/usr/bin/env bash
#
# Aggressive linting. Black runs FIRST (it reformats), then every checker.
#
#   make lint        check everything; any finding is a failure
#   make lint-fix    auto-fix what can be fixed, then re-check
#
# Exit codes: 0 clean, 1 findings. The pre-commit hook depends on that, and on
# black reporting whether it changed anything.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV="$REPO_ROOT/.venv"
FIX=0
[ "${1:-}" = "--fix" ] && FIX=1

FAILURES=()
CHANGED_BY_BLACK=0

section() { printf '\n\033[1;94m▸ %s\033[0m\n' "$*"; }
ok()      { printf '  \033[92m✓\033[0m %s\n' "$*"; }
bad()     { printf '  \033[91m✗\033[0m %s\n' "$*"; }
skip()    { printf '  \033[93m-\033[0m %s\n' "$*"; }

have() { [ -x "$VENV/bin/$1" ]; }

run() {
  # run <label> <command...>
  local label="$1"; shift
  if "$@"; then
    ok "$label"
  else
    bad "$label"
    FAILURES+=("$label")
  fi
}

printf '\n\033[1mLinting Milsurp Monitor\033[0m'
[ "$FIX" = "1" ] && printf ' \033[2m(fix mode)\033[0m'
printf '\n'

if [ ! -d "$VENV" ]; then
  echo "No virtualenv — run 'make install-dev' first." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. black — always first, because it rewrites files the other tools then read.
# ---------------------------------------------------------------------------
section "black (formatting)"
if have black; then
  if [ "$FIX" = "1" ]; then
    "$VENV/bin/black" --line-length 100 backend scripts 2>&1 | sed 's/^/  /'
    ok "formatted"
  else
    # --check --diff reports without writing. A non-zero exit means files are
    # not formatted; the pre-commit hook treats that as a blocking failure.
    if "$VENV/bin/black" --line-length 100 --check --quiet backend scripts 2>/dev/null; then
      ok "all files already formatted"
    else
      CHANGED_BY_BLACK=1
      bad "files are not black-formatted"
      "$VENV/bin/black" --line-length 100 --check --diff backend scripts 2>/dev/null \
        | head -60 | sed 's/^/  /'
      FAILURES+=("black")
    fi
  fi
else
  skip "black not installed (pip install -r backend/requirements-dev.txt)"
fi

# ---------------------------------------------------------------------------
# 2. ruff — the broad Python linter.
# ---------------------------------------------------------------------------
section "ruff (Python lint)"
if have ruff; then
  if [ "$FIX" = "1" ]; then
    "$VENV/bin/ruff" check --fix backend scripts 2>&1 | tail -20 | sed 's/^/  /'
  fi
  run "ruff check" "$VENV/bin/ruff" check backend scripts
else
  skip "ruff not installed"
fi

# ---------------------------------------------------------------------------
# 3. mypy — type checking.
# ---------------------------------------------------------------------------
section "mypy (types)"
if have mypy; then
  run "mypy" "$VENV/bin/mypy" --config-file pyproject.toml backend/app
else
  skip "mypy not installed"
fi

# ---------------------------------------------------------------------------
# 4. bandit — Python security lint. Also part of `make security`; it runs here
#    too so a problem is caught before the commit rather than in CI.
# ---------------------------------------------------------------------------
section "bandit (Python security)"
if have bandit; then
  run "bandit" "$VENV/bin/bandit" -q -c pyproject.toml -r backend/app scripts
else
  skip "bandit not installed"
fi

# ---------------------------------------------------------------------------
# 5. Frontend.
# ---------------------------------------------------------------------------
section "prettier (frontend formatting)"
if [ -d frontend/node_modules ]; then
  if [ "$FIX" = "1" ]; then
    (cd frontend && npm run --silent format) >/dev/null 2>&1
    ok "formatted"
  else
    if (cd frontend && npm run --silent format:check) >/dev/null 2>&1; then
      ok "all files already formatted"
    else
      bad "files are not prettier-formatted"
      (cd frontend && npx --no-install prettier --list-different "src/**/*.{js,jsx,css}" 2>/dev/null) \
        | sed 's/^/    /'
      FAILURES+=("prettier")
    fi
  fi
else
  skip "frontend/node_modules missing — run 'make install-dev'"
fi

section "eslint (frontend lint)"
if [ -d frontend/node_modules ]; then
  if [ "$FIX" = "1" ]; then
    (cd frontend && npm run --silent lint:fix) >/dev/null 2>&1 || true
  fi
  # --max-warnings 0 is what makes this aggressive: a warning fails the build.
  if (cd frontend && npm run --silent lint) 2>&1 | tee /tmp/milsurp-eslint.log | tail -30 | sed 's/^/  /'; then
    ok "eslint"
  else
    bad "eslint"
    FAILURES+=("eslint")
  fi
else
  skip "frontend/node_modules missing"
fi

# ---------------------------------------------------------------------------
# 6. Shell scripts.
# ---------------------------------------------------------------------------
section "shellcheck (shell scripts)"
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck -S warning scripts/*.sh .githooks/*; then
    ok "shellcheck"
  else
    bad "shellcheck"
    FAILURES+=("shellcheck")
  fi
else
  skip "shellcheck not installed (sudo apt-get install shellcheck)"
fi

# ---------------------------------------------------------------------------
# 7. YAML.
# ---------------------------------------------------------------------------
section "YAML syntax"
if "$VENV/bin/python" - <<'PY'; then
import sys, pathlib, yaml
bad = []
for path in list(pathlib.Path(".").glob("*.yaml")) + \
            list(pathlib.Path(".").glob("*.yml")) + \
            list(pathlib.Path(".github").rglob("*.yml")):
    try:
        yaml.safe_load(path.read_text())
    except Exception as exc:
        bad.append(f"{path}: {exc}")
for line in bad:
    print(f"    {line}")
sys.exit(1 if bad else 0)
PY
  ok "YAML files parse"
else
  bad "YAML syntax"
  FAILURES+=("yaml")
fi

# ---------------------------------------------------------------------------
printf '\n'
if [ ${#FAILURES[@]} -eq 0 ]; then
  printf '\033[1;92m✓ Lint clean.\033[0m\n\n'
  exit 0
fi

printf '\033[1;91m✗ Lint failed: %s\033[0m\n' "$(IFS=', '; echo "${FAILURES[*]}")"
if [ "$CHANGED_BY_BLACK" = "1" ]; then
  printf '\n  Run \033[96mmake lint-fix\033[0m to reformat, then review and re-stage.\n'
fi
printf '\n'
exit 1
