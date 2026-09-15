#!/usr/bin/env bash
#
# Run the same security scanners CI runs, locally.
#
#   make security
#
# Covers: bandit (Python security lint), semgrep (rule-based SAST), Snyk
# (dependency CVEs), pip-audit / npm audit (dependency CVEs without a Snyk
# account), and gitleaks (committed secrets).
#
# Anything not installed is reported as skipped rather than failing the run, so
# this is useful before every one of them is set up. CI installs them all.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV="$REPO_ROOT/.venv"
REPORTS="$REPO_ROOT/.security-reports"
mkdir -p "$REPORTS"

FAILURES=()
SKIPPED=()

section() { printf '\n\033[1;94m▸ %s\033[0m\n' "$*"; }
ok()      { printf '  \033[92m✓\033[0m %s\n' "$*"; }
bad()     { printf '  \033[91m✗\033[0m %s\n' "$*"; }
skip()    { printf '  \033[93m-\033[0m %s\n' "$*"; SKIPPED+=("$1"); }
note()    { printf '    \033[2m%s\033[0m\n' "$*"; }

have_venv() { [ -x "$VENV/bin/$1" ]; }

# Used to summarize JSON reports. The virtualenv's interpreter when there is
# one, because that is the copy this project is built against, but any python3
# will do -- nothing here imports from the project.
if have_venv python; then PY="$VENV/bin/python"; else PY="$(command -v python3 || true)"; fi

printf '\n\033[1mSecurity scan\033[0m \033[2m(same tools as CI)\033[0m\n'

# ---------------------------------------------------------------------------
section "bandit — Python security lint"
if have_venv bandit; then
  if "$VENV/bin/bandit" -q -c pyproject.toml -r backend/app scripts \
       -f json -o "$REPORTS/bandit.json" 2>/dev/null; then
    ok "no issues"
  else
    # Bandit exits non-zero on any finding; show the high/medium ones.
    bad "findings — see $REPORTS/bandit.json"
    "$VENV/bin/bandit" -q -c pyproject.toml -r backend/app scripts 2>/dev/null \
      | grep -E "^>>|Issue:|Severity:|Location:" | head -40 | sed 's/^/    /'
    FAILURES+=("bandit")
  fi
else
  skip "bandit not installed — pip install -r backend/requirements-dev.txt"
fi

# ---------------------------------------------------------------------------
section "semgrep — rule-based static analysis"
# Looked up in the virtualenv first, like the other Python tools: semgrep is
# installed by `make install-dev` into .venv/bin, which is not on PATH, so
# `command -v semgrep` said "not installed" about a scanner that was sitting
# right there. It had been skipping silently for that reason, which is the
# thing this file's own header promises it does not do.
SEMGREP=""
if have_venv semgrep; then
  SEMGREP="$VENV/bin/semgrep"
elif command -v semgrep >/dev/null 2>&1; then
  SEMGREP="semgrep"
fi

if [ -n "$SEMGREP" ]; then
  # p/security-audit and p/secrets are the registry rulesets CI uses; the
  # language packs catch framework-specific issues.
  if "$SEMGREP" --config=p/security-audit --config=p/secrets \
             --config=p/python --config=p/javascript \
             --error --quiet --metrics=off \
             --exclude=node_modules --exclude=.venv --exclude=dist \
             --json --output="$REPORTS/semgrep.json" . >/dev/null 2>&1; then
    ok "no issues"
  else
    bad "findings — see $REPORTS/semgrep.json"
    # Read the report back rather than scanning a second time. The old line
    # re-ran bare `semgrep` — not "$SEMGREP" — and the lookup above exists
    # precisely because the scanner is normally in .venv/bin and not on PATH,
    # so in CI it printed nothing at all under the word "findings". A failure
    # you cannot act on without checking the branch out yourself is barely a
    # failure report. The re-run also dropped p/python and p/javascript, so a
    # finding from either pack would have printed an empty list.
    if [ -n "$PY" ]; then
      "$PY" - "$REPORTS/semgrep.json" <<'PYEOF' | head -40
import json, sys
try:
    results = json.load(open(sys.argv[1]))["results"]
except (OSError, ValueError, KeyError):
    print("    (report unreadable)")
    raise SystemExit
for f in results:
    rule = f["check_id"].rsplit(".", 1)[-1]
    print(f"    {f['path']}:{f['start']['line']}  {rule}")
    print("      " + " ".join(f["extra"]["message"].split())[:150])
PYEOF
    else
      note "no python3 to summarize the report with; read the JSON directly."
    fi
    FAILURES+=("semgrep")
  fi
else
  skip "semgrep not installed"
  note "pip install semgrep   (or: brew install semgrep)"
fi

# ---------------------------------------------------------------------------
section "Snyk — dependency vulnerabilities"
if command -v snyk >/dev/null 2>&1; then
  if [ -z "${SNYK_TOKEN:-}" ] && [ ! -f "$HOME/.config/configstore/snyk.json" ]; then
    skip "snyk installed but not authenticated"
    note "run 'snyk auth', or export SNYK_TOKEN"
  else
    # Snyk's exit codes carry three different meanings and they must not be
    # collapsed: 0 is clean, 1 is "vulnerabilities found", anything else is
    # "the scan did not run". Treating them all as failure reported
    # "vulnerabilities found" while the report beside it said ok:true with
    # none — which is worse than no scan, because it teaches you to ignore it.
    SNYK_VULNS=0
    SNYK_BROKEN=0

    # --command points Snyk at this project's interpreter. Without it the pip
    # scanner cannot resolve our unpinned ranges and exits 2 with
    # SNYK-OS-PYTHON-0013, "Missing required packages".
    # Each ecosystem says how it did on its own line. These used to print
    # "Python:" and "Node:" with the result discarded to /dev/null and nothing
    # after the colon, which was invisible while the whole section was being
    # skipped for want of a token. With two scans behind one summary, "found
    # vulnerabilities" that does not say which half found them is a report you
    # have to go and re-run to act on.
    snyk_verdict() {
      case "$1" in
        0) printf 'clean\n' ;;
        1) printf 'vulnerabilities\n'; SNYK_VULNS=1 ;;
        *) printf 'did not run\n';    SNYK_BROKEN=1 ;;
      esac
    }

    printf '  Python: '
    snyk test --file=backend/requirements.txt --package-manager=pip \
      --command="$VENV/bin/python" \
      --severity-threshold=high --json-file-output="$REPORTS/snyk-python.json" \
      >/dev/null 2>&1
    snyk_verdict $?

    printf '  Node:   '
    (cd frontend && snyk test --severity-threshold=high \
      --json-file-output="$REPORTS/snyk-node.json" >/dev/null 2>&1)
    snyk_verdict $?

    if [ "$SNYK_VULNS" = "1" ]; then
      bad "vulnerabilities found — see $REPORTS/snyk-*.json"
      FAILURES+=("snyk")
    elif [ "$SNYK_BROKEN" = "1" ]; then
      skip "snyk could not complete — see $REPORTS/snyk-*.json"
      note "this is a scan that did not run, not a clean result"
    else
      ok "no high-severity vulnerabilities"
    fi
  fi
else
  skip "snyk not installed"
  note "npm install -g snyk && snyk auth"
fi

# ---------------------------------------------------------------------------
section "pip-audit / npm audit — dependency CVEs"
# These need no account, so they are the fallback when Snyk is unavailable.
AUDIT_FAILED=0
if have_venv pip-audit; then
  if "$VENV/bin/pip-audit" -r backend/requirements.txt --desc off 2>/dev/null; then
    ok "pip-audit: no known vulnerabilities"
  else
    bad "pip-audit found vulnerable Python packages"
    AUDIT_FAILED=1
  fi
else
  skip "pip-audit not installed (pip install pip-audit)"
fi

if [ -d frontend/node_modules ]; then
  if (cd frontend && npm audit --audit-level=high) >"$REPORTS/npm-audit.txt" 2>&1; then
    ok "npm audit: no high-severity vulnerabilities"
  else
    bad "npm audit found vulnerable packages — see $REPORTS/npm-audit.txt"
    tail -20 "$REPORTS/npm-audit.txt" | sed 's/^/    /'
    AUDIT_FAILED=1
  fi
else
  skip "frontend/node_modules missing"
fi
[ "$AUDIT_FAILED" = "1" ] && FAILURES+=("dependency-audit")

# ---------------------------------------------------------------------------
section "gitleaks — committed secrets"
GITLEAKS_IMAGE="ghcr.io/gitleaks/gitleaks:latest"

# gitleaks is distributed as a native binary and as a container image, and
# either is a perfectly good way to have it. Both are accepted so that `make
# security` does not silently skip the secret scan just because the tool was
# installed the other way. Paths stay repository-relative because the container
# sees the repo mounted at a different place.
gitleaks_run() {
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks "$@"
  else
    # --user keeps the report file owned by the invoking user rather than root.
    docker run --rm --user "$(id -u):$(id -g)" \
      -v "$REPO_ROOT:/repo" -w /repo "$GITLEAKS_IMAGE" "$@"
  fi
}

gitleaks_available() {
  command -v gitleaks >/dev/null 2>&1 && return 0
  command -v docker >/dev/null 2>&1 || return 1
  docker image inspect "$GITLEAKS_IMAGE" >/dev/null 2>&1
}

if gitleaks_available; then
  # --no-git scans the working tree, which is what matters before a commit and
  # avoids this script needing to invoke git. The local config.yaml is
  # allowlisted in .gitleaks.toml because it is gitignored by design; the
  # "Local checks" section below is what guards that.
  if gitleaks_run detect --no-git --source . --config .gitleaks.toml \
       --report-path ".security-reports/gitleaks.json" --redact --exit-code 1 >/dev/null 2>&1; then
    ok "no secrets detected"
  else
    bad "possible secrets found — see $REPORTS/gitleaks.json"
    note "gitleaks reads the working tree, not git — check the path before the match"
    FAILURES+=("gitleaks")
  fi
else
  skip "gitleaks not installed"
  note "run 'make install-dev', or: docker pull $GITLEAKS_IMAGE"
fi

# ---------------------------------------------------------------------------
section "Local checks"
# The one mistake that would actually leak credentials from this repo.
if [ -f config.yaml ]; then
  PERMS="$(stat -c '%a' config.yaml 2>/dev/null || stat -f '%Lp' config.yaml 2>/dev/null)"
  if [ "$PERMS" = "600" ]; then
    ok "config.yaml is mode 600"
  else
    bad "config.yaml is mode $PERMS — it holds SMTP credentials and secrets"
    note "fix with: chmod 600 config.yaml"
    FAILURES+=("config-permissions")
  fi
fi

if grep -q '^config\.yaml$' .gitignore 2>/dev/null; then
  ok "config.yaml is gitignored"
else
  bad "config.yaml is NOT gitignored"
  FAILURES+=("gitignore")
fi

if grep -rn "CHANGE-ME" config.yaml 2>/dev/null | grep -q .; then
  bad "config.yaml still contains sample placeholder secrets"
  note "run 'make secrets' and paste the values in"
  FAILURES+=("placeholder-secrets")
else
  ok "no placeholder secrets in config.yaml"
fi

# ---------------------------------------------------------------------------
printf '\n'
if [ ${#SKIPPED[@]} -gt 0 ]; then
  printf '\033[2mSkipped: %s\033[0m\n' "$(IFS=', '; echo "${SKIPPED[*]}")"
fi

if [ ${#FAILURES[@]} -eq 0 ]; then
  # "Clean" and "clean as far as it looked" are different claims, and the
  # difference is the whole value of the line. semgrep and pip-audit sat
  # uninstalled in a virtualenv for three days while this printed the first
  # one; nothing was wrong except that nothing was being checked.
  if [ ${#SKIPPED[@]} -gt 0 ]; then
    printf '\033[1;93m✓ Security scan clean — but %d of the tools did not run.\033[0m\n' \
      "${#SKIPPED[@]}"
    printf '\033[2m  A green run here only means as much as the list above allows.\033[0m\n'
    printf '\033[2m  make install-dev installs semgrep, pip-audit and gitleaks.\033[0m\n\n'
  else
    printf '\033[1;92m✓ Security scan clean — every tool ran.\033[0m\n\n'
  fi
  exit 0
fi

printf '\033[1;91m✗ Security scan failed: %s\033[0m\n' "$(IFS=', '; echo "${FAILURES[*]}")"
printf '  Reports in %s\n\n' "${REPORTS#"$REPO_ROOT"/}"
exit 1
