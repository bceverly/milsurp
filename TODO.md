# TODO — Milsurp Monitor build

Working checklist of everything requested, with what is done and what is left.
**This file is the resume point.** If the session is interrupted, read this
first, then the "Context for whoever picks this up" section at the bottom.

Last updated: 2026-09-06 — lint clean, 577 backend tests green (75.4% coverage)

---

## Ground rules (standing instructions)

- [x] **The project is BSD 3-Clause, not MIT.** I initially wrote MIT into the
      README and `pyproject.toml` without reading `LICENSE`; corrected.

- [x] **Never run any `git` command** — not `status`, `diff`, `log`, `add`,
      anything. Also never `gh`. Surface the command for the user to run.
      Enforced by `permissions.deny` in `~/.claude/settings.json`
      (`Bash(git)` / `Bash(git:*)` / `Bash(gh)` / `Bash(gh:*)`), documented in
      `~/.claude/CLAUDE.md`, and saved as a memory
      (`no-git-commands.md`).
- [x] American spelling everywhere (from `~/.claude/CLAUDE.md`).

---

## 1. Core application — **DONE**

- [x] Single app: crawls vendor sites, stores listings, emails digests.
- [x] Python backend (FastAPI + SQLAlchemy 2.0 + Alembic + uvicorn).
- [x] React frontend (Vite, react-router), fully responsive (phone + desktop).
- [x] SQLite for all structured data; photos on disk in a secure directory.
- [x] Price stored in a **related `price_history` table**, not a flat column
      (a row is written only when the price actually changes).
- [x] Two user classes: `admin` (everything, incl. user management) and
      `normal` (view only). Enforced server-side on every route.
- [x] Passwords hashed with **Argon2id** (per-password random salt) plus a
      server-side pepper from the config file.
- [x] Config YAML at `/etc/milsurp/config.yaml`, with a repo-root
      `config.yaml` taking precedence in dev. `config.yaml.sample` provided
      and fully commented. Repo-root `config.yaml` is gitignored.
- [x] Configurable: database path, image path, default admin id/password,
      salt/pepper, JWT secret, SMTP, ports, scheduler, scraping behavior.
- [x] All datetimes stored **UTC**; API emits ISO-8601 with `Z`; browser
      converts to local time (`frontend/src/format.js`).
- [x] Reviewed `../rtiscan` and `../empire_arms` and combined the feature set.

## 2. Scraping — **DONE**

- [x] Pluggable scraper registry (`backend/app/scrapers/__init__.py`); adding
      a vendor is one class + one list entry.
- [x] Royal Tiger Imports scraper — handles infinite scroll, "Load More"
      buttons, and classic pagination (the hard cases from `rtiscan`).
- [x] Empire Arms scraper — static HTML block parsing.
- [x] **RTI now captures the full photo gallery** (Elementor
      `a.e-gallery-item`), not just the grid thumbnail. Verified: 5 photos on a
      listing that previously yielded 1. WordPress `-scaled`/size-suffix
      duplicates are collapsed.
- [x] Detail pages are only fetched for listings not already stored
      (`ctx.needs_detail`), so re-scans stay cheap.
- [x] Periodic background scheduler; per-site enable/disable and frequency.
- [x] Caliber / country / manufacturer / rifle-vs-pistol / bore-condition
      heuristics ported and expanded from both prior apps.

## 3. Images — **DONE**

- [x] Stored on disk in a secure directory (0700), **never** served as static
      files — only through an authenticated API endpoint.
- [x] **Two resolutions**, both generated locally during the scan (Pillow):
      full-size + a 640px thumbnail. Verified ~10x size reduction
      (264KB → 28KB). Images already small reuse the original.
- [x] List/grid view requests `?size=thumb`; detail view requests full size.
- [x] Detail view has a multi-photo gallery with thumbnail strip + lightbox.
- [x] SSRF guard on image downloads (public http/https only; private,
      loopback and link-local addresses rejected).

## 4. Admin features — **DONE**

- [x] Site list showing at-a-glance status + datetime of the most recent scan.
- [x] Drill into full scan history per site.
- [x] Scan detail page with live-tailing progress log.
- [x] Enable/disable a site; set its scan frequency; "Scan now"; cancel a scan.
- [x] User management (create, edit, reset password, deactivate, delete) with
      last-admin protection.

## 5. Email digests — **DONE**

- [x] Per-user frequency.
- [x] "New items" toggle with a **required per-site limit**.
- [x] "Price reductions" toggle with the same per-site limit + a minimum-drop
      filter.
- [x] Per-user site selection (empty = all enabled sites).
- [x] HTML email, sent from the account configured in the YAML file
      (Gmail app-password friendly).
- [x] "Skip when empty" option; delivery history; admin SMTP test button.

## 6. Search — **DONE**

- [x] Keyword search across titles **and** captured descriptions (also
      caliber, manufacturer, country, category).
- [x] Multi-term AND matching across fields; quoted phrases; LIKE
      metacharacters escaped.

## 7. Dev/prod modes — **DONE**

- [x] `make start` / `make stop`; `make start` prints the URL.
- [x] Dev port chosen dynamically (falls back through a configured range).
- [x] Dev SQLite DB in the repo root; prod configurable, defaulting to
      `/etc/milsurp/`.
- [x] Production port from YAML, default 443, with port 80 → 301 → 443.
- [x] nginx config generated (`deploy/nginx/milsurp.conf`) + an HTTP-only
      bootstrap config for the pre-certificate state.
- [x] systemd unit with extensive hardening.

## 8. Database migrations — **DONE**

- [x] Alembic used **from the very first database** — no `create_all()`
      anywhere; a fresh install runs the same migration chain as an upgrade.
- [x] All migrations written to be **idempotent**
      (`backend/app/migration_utils.py`).
- [x] `scripts/dbupdate.py` resolves the correct DB path for dev vs prod and
      creates the empty DB file + parent directory when needed (with correct
      permissions).
- [x] `make migrate` runs that script; production runs the bare script.
- [x] Verified: migration schema matches the ORM models exactly.

## 9. Branding — **DONE**

- [x] Logo + favicon: US Air Force **Senior Airman** insignia. Took several
      wrong turns before getting the construction right; the correct one is:
      a **dark circular hub sitting on top of the z-order**, two
      **constant-width striped wings** whose center lines pass through the hub
      center (so the three stripes are centered on the hub and the band is
      slightly narrower than its diameter), wing tips cut **vertically,
      parallel to the frame** — which makes the three stripes different
      lengths — and a **star at the hub center, blue on blue with a metallic
      blue outline**, never white. Signed off by the user.
- [x] Site color scheme from the dress insignia: Air Force blue, silver-white,
      black.
- [x] Appropriate iconography — inline SVG icon set
      (`frontend/src/components/Icons.jsx`).
- [x] Brand assets generated by `scripts/brand.py` from one geometry
      definition: `marketing/images/{logo,favicon}.svg`,
      `frontend/public/favicon.svg`, and
      **`frontend/src/components/Insignia.jsx`** — the in-app mark is generated
      too, so it cannot drift from the SVGs. That JSX file is committed (the
      build imports it) even though it is generated.
- [x] Dropped an unused `insignia.svg` outline variant that nothing referenced.
- [x] Domain `milsurpmonitor.com` wired through nginx, sample config, email
      branding and docs.

## 10. Tooling — **DONE**

- [x] `Makefile` with a self-documenting default `help` target listing every
      target with a description.
- [x] `make install-dev` — creates `.venv` in the repo root, installs system
      packages via `sudo` (prompts for password), Python + npm deps, and the
      Playwright browser.
- [x] `make migrate`, `make migrate-status`, `make migration`.
- [x] `make screenshots` — Playwright, writes to `marketing/images/`.
- [x] `.gitignore` appropriate to the stack; repo-root SQLite DB explicitly
      ignored; `images/` ignored (screenshots live in `marketing/images/`).
- [x] `ROADMAP.md` — includes the 16 future vendor sites, deb/PPA →
      Launchpad on `v1.2.3` tags, and the Electron/snap plan.
- [x] `scripts/install-production.sh` — Ubuntu 26.04 server setup.
- [x] `scripts/setup-letsencrypt.sh` — certificate for milsurpmonitor.com.
- [x] **`make lint`** — `scripts/lint.sh` written. Runs **black first**, then
      ruff, mypy, bandit, prettier, eslint, shellcheck and a YAML parse check.
      Any finding exits 1. `make lint-fix` auto-fixes then re-checks.
- [x] Lint configuration: `pyproject.toml` (ruff with a deliberately broad rule
      selection, black line-length 100, mypy, bandit),
      `frontend/.eslintrc.cjs` (`--max-warnings 0`), `.prettierrc.json`,
      `.prettierignore`, `.nycrc.json`.
- [x] **`make security`** — `scripts/security.sh` written. Runs bandit,
      semgrep, Snyk, pip-audit, npm audit, gitleaks, plus local checks
      (config.yaml is mode 600, is gitignored, has no placeholder secrets).
      Missing tools are reported as skipped rather than failing.
- [x] `.gitleaks.toml` — secret-detection rules with allowances for the
      documented sample placeholders and test fixtures.
- [x] **`make dev`** — `scripts/dev.sh` written: runs the API with `--reload`
      and Vite together, exporting `MILSURP_API_PORT` so Vite's proxy follows
      the dynamically chosen backend port. Ctrl-C stops both.
- [x] **`make install-hooks`** — `scripts/install-hooks.sh` + `.githooks/`
      written and installed. Verified: the hook exits 1 and prints PUSH BLOCKED
      when lint reports anything. Existing non-ours hooks are backed up rather
      than overwritten. Installs by file copy — no git command.
- [x] `shellcheck` added to `install-dev.sh`'s package list. Once installed it
      found 4 real issues, all fixed: three `cd "$REPO_ROOT"` calls without
      `|| exit` in scripts that do not use `set -e`, and one dead variable.
- [x] **Scanning is off by default** in `config.yaml.sample`
      (`scheduler.enabled: false`), so a fresh install does not start crawling
      vendor sites the moment it boots. `install-dev.sh` says so on completion.
- [x] **`make lint` is now clean end to end.** With the linters actually
      installed it initially reported 326 ruff + 36 mypy + 5 bandit findings.
      All resolved: ruff config tuned to drop rules that fought deliberate
      design (TID252 relative imports, PLC0415 lazy imports, PLW0603 singletons,
      UP037 SQLAlchemy forward refs, UP042 str-Enum, N818), and every genuine
      finding fixed rather than suppressed. Notable real fixes:
      `contextlib.suppress` throughout (clears bandit B110/B112 too),
      `os.chmod` → `Path.chmod`, `classify.enrich()` now returns a
      **TypedDict** so scrapers get real field types, `None` guards on the
      digest price arithmetic, and BeautifulSoup multi-valued-attribute
      narrowing in the RTI scraper.

## 11. Testing — **DONE**

- [x] `make test` target wired (backend + frontend).
- [x] pytest suite: **288 tests passing at 69.5% coverage — the 65% gate is
      cleared** and `make test-backend` exits 0.
- [x] **Warnings are errors** (`filterwarnings = error` in pytest.ini). The one
      warning this surfaced was real: migration 0002 used the deprecated
      `Column.copy()`; it now builds fresh Column objects. A single narrow
      `ignore::` remains for Starlette's use of a deprecated anyio alias, with
      a comment saying to remove it when Starlette updates.
- [x] Another **real bug** found by the Playwright suite and fixed in the
      backend with regression tests: the last-admin guard counted *all* admins,
      not active ones, so an already-disabled admin could not be deleted or
      demoted. `POST /users/{id}` delete and PATCH now both check
      `user.is_active` as well. Added since the pause:
      `test_netutil.py` (12), `test_image_store.py` (30, incl. the SSRF and
      path-traversal guards), `test_mailer.py` (16), `test_api_sites.py` (30),
      `test_api_preferences.py` (28).
- [x] The mailer tests caught a **real bug**: `send_html` wrapped
      `SMTPAuthenticationError` in a generic "could not connect", hiding the
      Gmail App Password guidance. Fixed.
- [x] `scripts/test-backend.sh` with a `--cov-fail-under=65` gate.
- [x] `scripts/coverage_badges.py` — generates local SVG badges into
      `marketing/images/`, red < 65% / amber < 80% / green ≥ 80%.
- [x] **Playwright suite written and running**: `playwright.config.js`
      (desktop + mobile projects), `tests/fixtures.js` (signed-in page +
      istanbul coverage harvesting), and specs `auth`, `inventory`, `admin`,
      `responsive`, `workflows`.
- [x] **`scripts/test-frontend.sh`** — builds with `COVERAGE=1`, seeds a
      disposable database via the new `scripts/seed_demo_data.py`, starts the
      app on an ephemeral port (`run.py --port 0`), runs Playwright, then
      reports through nyc with the 65% floor.
- [x] Frontend coverage now **70.6% statements / 72.5% lines**, over the gate.
- [x] **All 67 Playwright tests pass**, frontend coverage **72.7% statements /
      74.5% lines**, over the 65% gate.
- [x] The suite found **two real bugs**, both fixed at the source rather than
      worked around in the test:
      1. *Accessibility*: field hints were nested inside `<label>`, so the
         control's accessible name became "Password At least 12 characters…".
         A screen reader announced the whole hint as the field's name. Added
         `components/Field.jsx`, which puts hints in `aria-describedby`, and a
         regression test that asserts the attribute is present.
      2. *Duplicate control*: the user form carried a `visually-hidden` submit
         button while the dialog footer had the real one — two buttons named
         "Save" in one dialog, announced twice. Removed; the footer button is
         already associated via `form="user-form"`, which is what makes
         Enter-to-submit work.
- [x] **`scripts/test-frontend.sh`** — written and working (see above).
- [x] Badges generated and referenced from the README
      (backend 69.5%, frontend 79.3%).

## 12. CI / security — **DONE**

- [x] `.github/workflows/ci.yml` — lint, backend tests, frontend tests, and a
      **migrations job** that builds the database from scratch, re-runs the
      migrations to prove idempotency, and asserts the models and migrations
      have not drifted apart.
- [x] `.github/workflows/security.yml` — **bandit**, **semgrep**, **Snyk**
      (skipped with a warning when `SNYK_TOKEN` is absent), **pip-audit** and
      **npm audit** as the no-account fallback, **gitleaks** *and*
      **TruffleHog** for secrets, **CodeQL**, plus a job asserting the sample
      config holds only placeholders and `config.yaml` is gitignored. Also runs
      weekly so a new CVE in unchanged dependencies is still caught.
- [x] `.github/dependabot.yml` — pip, npm and github-actions, grouped weekly,
      majors split out for review.
- [x] **One hook, at pre-push, running `make lint` and nothing else.** Per the
      user, twice over: not `make test` (the suites take minutes, would run
      again for every tag push, and CI runs them on every push anyway), and not
      at pre-commit (a work-in-progress commit is nobody else's problem; a push
      is). `.githooks/pre-commit` was deleted, and `install-hooks.sh` now
      *removes* a previously-installed one — otherwise the old copy would keep
      firing from `.git/hooks/` forever with nothing in the repository to
      explain it. Runs in ~2 s, and prints the full lint output when it blocks.
      Both paths verified: clean exit 0, unformatted file exit 1 with the diff.
- [x] **CI restructured into one job per concern**, per the user: `ci.yml` has
      `lint`, `test` (a backend step followed by a frontend step, the frontend
      one `if: always()` so a single push reports both), `migrations` and
      `build`; `security.yml` has `security` (installs every scanner, then runs
      `make security`) and `codeql`.

## 13. Production login extras — **BACKEND DONE, UI DONE, UNTESTED**

- [x] "Request access" button on the login screen, **production only**
      (hidden in dev; the server reports whether it is enabled).
- [x] Login is the first screen on launch.
- [x] reCAPTCHA (v2/v3) verification server-side.
- [x] Emails first name, last name, email address (+ optional note) to a
      `email.support_email` address added to the YAML config.
- [x] Per-IP rate limiting; all fields HTML-escaped; nothing written to the DB.
- [ ] Not yet exercised by a test. Needs a fixture that builds a
      production-mode config (`MILSURP_ENV=production` + `email.enabled`), since
      the endpoint deliberately 404s in dev. A Playwright test already asserts
      the button is correctly **hidden** in dev.

## 14. OWASP Top 10 — **DONE**

Implemented so far:
- A01 Broken Access Control — server-side RBAC on every route; photo endpoint
  checks the photo belongs to the item; path-traversal guard in the image store.
- A02 Cryptographic Failures — Argon2id + pepper; JWT with a token-version
  revocation counter; TLS 1.2/1.3 only; HSTS.
- A03 Injection — SQLAlchemy parameter binding throughout; LIKE metacharacters
  escaped; all email HTML escaped.
- A04 Insecure Design — per-site scan locking; per-user digest caps; login
  throttling; single unauthenticated write path, captcha-gated.
- A05 Security Misconfiguration — security headers in app + nginx; CSP; API
  docs disabled in production; systemd hardening; 0600/0700 file modes.
- A07 Auth Failures — throttle + lockout; uniform failure messages; timing
  equalization; 12-char minimum; password change revokes all sessions.
- A08 Data Integrity — pinned dependency floors; Dependabot on pip, npm and
  Actions; CodeQL, semgrep and bandit in CI.
- A09 Logging Failures — every attacker-supplied value passes through
  `app/logsafe.scrub()` before it reaches a log record.
- A10 SSRF — image-download URL validation against private/loopback ranges.

- [x] OWASP Top 10 written up in the README as a table, one row per risk with
      what actually addresses it.

## 15a. Later additions

- [x] **`make release`** (`scripts/release.sh`) — reads the highest `vX.Y.Z.W`
      tag, bumps the last digit, confirms yes/no (answering no changes
      nothing), then writes the version into `backend/app/__init__.py`,
      `pyproject.toml` and `frontend/package.json`, commits, pushes, tags and
      pushes the tag. `make release VERSION=1.2.3.4` sets an explicit version;
      with no tags at all it starts at `v1.0.0.0`. npm needs 3-part semver, so
      package.json gets the first three components.
      **NOTE: never run by me — it invokes git. Untested end to end; the
      version-arithmetic was verified in isolation.**
- [x] **Scan-now UI** — the site list, per-site "Scan now", out-of-band
      execution and countdown reset already existed. Added the two missing
      pieces: an **indeterminate progress bar + "Scanning…" spinner** while a
      run is in flight, and a **success/partial/failure banner** afterwards
      carrying the counts or the error, dismissible and auto-clearing.
- [x] Fixed a **race** in that tracking: an in-flight poll landing just after
      the operator clicked could wipe the watch set, so the outcome banner
      never appeared. The watch set is now only cleared once an outcome has
      been recorded, and polling continues while anything is still watched.
- [x] **`DemoScraper`** — a network-free fixture vendor, registered only when
      `MILSURP_ENABLE_DEMO_SITE=1` (set by the e2e and screenshot runners), so
      the scan pipeline can be exercised end to end without hitting a real
      shop. Also useful for verifying a fresh install.
- [x] **Configurable password policy.** `security.min_password_length`
      (default 12) plus `require_uppercase` / `require_lowercase` /
      `require_numeric` / `require_special`. The rules in force are *derived*
      from whichever toggles are true, the Pydantic bound was relaxed so the
      config is authoritative, and `GET /api/policy` serves the derived rules
      to the UI so the on-screen guidance can never drift from enforcement.
      All four default to true in `config.yaml.sample` and the local config.
- [x] Diagnosed the user's 401: the repo-root `milsurp.db` was **my** test
      artifact, seeded with my scratchpad password. `ensure_admin` only seeds
      when no admin exists, so their configured password was never applied —
      and nothing said so. `make init` now reports this explicitly, and
      `make passwd` was added.
- [x] Ten more vendor sites added to the roadmap (17–26), plus Hunter's Lodge
      as its own OCR milestone.
- [x] **`make start` is now a restart**: it stops any running instance, waits
      for it to actually exit, rebuilds the frontend if its sources changed,
      and only prints the URL once `/api/health` answers — the port file is
      written before uvicorn binds, so waiting on it alone was reporting
      "running" too early. `make stop` is idempotent and reaps stale PID files.

## 15. Documentation — **DONE**

- [x] **README.md** written (~490 lines): features, an architecture diagram,
      screenshots, coverage badges, dev quick start, production install,
      configuration reference, make targets, a worked "adding a vendor site"
      guide, the testing summary, the OWASP table, project layout and CLI.
- [x] `make screenshots` reworked to run against a **disposable database seeded
      with sample listings**, so the images are reproducible, work on a fresh
      checkout, and never bake real scraped vendor content into committed
      marketing images. `scripts/seed_demo_data.py` also generates clearly
      synthetic placeholder photos so the grid and gallery lay out properly.
- [x] Screenshots captured into `marketing/images/`.

## 16. First CI run — every failure fixed

The `v1.0.0.0` push was the first time the workflows ran for real. Everything
below was found by that run and is now fixed and verified locally.

- [x] **gitleaks crashed on our own config.** `.gitleaks.toml` used `(?!...)`
      negative lookaheads to exempt the documented placeholders. gitleaks
      compiles with Go's RE2, which has no lookaround, so it *panicked* — no
      report, and the artifact upload then failed too. The exemptions now live
      in `[allowlist].regexes`, where they always belonged. Two related fixes
      found while verifying: the rules were missing `(?m)`, so a bare `^` only
      ever anchored to the first line of a file (they matched almost nothing),
      and the local `config.yaml` is allowlisted because it is gitignored by
      design and was a guaranteed false positive on every developer's machine.
      **This never surfaced locally because gitleaks was not installed and
      `security.sh` silently skipped it** — which is why `make install-dev` now
      installs the scanners.
- [x] **Hard-coded test secrets removed.** `scripts/test-frontend.sh` and
      `scripts/screenshots.sh` embedded fixed pepper/JWT literals in their
      disposable configs. They are now generated per run from `/dev/urandom`:
      no tracked file in the repository contains a secret-shaped literal, and
      two concurrent runs cannot share a signing key.
- [x] **Backend tests failed in CI but passed locally.** Starlette 1.x imports
      `httpx2` and emits a deprecation warning when it falls back to `httpx` —
      and `pytest.ini` sets `filterwarnings = error`, so every API test errored
      and coverage fell to 45%. `httpx2` was installed on the dev machine by
      chance and absent in CI. Now pinned in `requirements-dev.txt`.
- [x] **semgrep, two findings.** Both false positives on
      `logger-credential-disclosure`, matched for the words "secrets" and
      "admin.password" appearing in a *message template*; the only interpolated
      values are a setting name and a file path. Suppressed with `# nosemgrep`
      and the reasoning in the comment. Verified: semgrep now reports 0 findings
      across 1491 rules.
- [x] **CodeQL, ten alerts.** Eight fixed properly, two suppressed in-source:
      - *Log injection* (`api/auth.py`, `api/access.py`) — a newline in a
        submitted username or name could forge whole log records. Added
        `app/logsafe.scrub()`, which escapes CR/LF and every non-printable
        character and caps the length, plus `tests/test_logsafe.py`.
      - *Polynomial regex on uncontrolled data* (`services/mailer.py`) — the
        HTML-to-text converter used `<[^>]+>` and `<(script|style).*?</\1>`,
        both quadratic, on digest bodies that embed vendor-supplied text.
        Replaced with an `html.parser.HTMLParser` subclass: linear, handles
        entities for free, and better output (table cells no longer run
        together). Measured: 300 KB of `<` now parses in 0.08 s.
      - *Clear-text logging* (`app/main.py`) — the weak-secret warning logged
        `len(value)`, which is derived from the secret. It now names only the
        minimum, which is what the operator needs anyway.
      - *Incomplete URL substring sanitization* (`tests/test_mailer.py`) — an
        `"smtp.example.com:587" in message` assertion. Now an equality check.
      - *Clear-text logging* (`cli.py`) — `make secrets` prints freshly
        generated secrets, which is the entire purpose of the command.
        Suppressed with `# codeql[...]` and the reasoning in the docstring.
- [x] **npm audit: 7 vulnerabilities → 0.** Upgraded rather than exempted:
      - `react-router-dom` 6 → 7.18.3. This one **ships to users** — an open
        redirect via backslash in `<Link>`/`useNavigate`, and constructor
        injection via `deserializeErrors()`. All the APIs this app uses are
        unchanged in v7.
      - `vite` 5 → 8, `@vitejs/plugin-react` 4 → 6, `vite-plugin-istanbul`
        6 → 9 (the esbuild dev-server advisory). Vite 8 bundles with Rolldown,
        which needed `manualChunks` written as a function rather than an
        object.
      - `nyc` 17 → 18 (the `uuid` bounds-check advisory).
- [x] **A real UI defect surfaced by the router upgrade.** React Router 7 wraps
      every navigation in `React.startTransition`, so a filter checkbox bound to
      `useSearchParams` ticked, un-ticked, then re-ticked: the click sets the
      box natively, React resets it to match the stale props, and only then does
      the transition commit. Confirmed by driving the real app (URL updated
      immediately, `checked` was still `false`). Fixed with
      `useOptimisticSearchParams` in `hooks.js`, which holds the value just
      written until the router catches up — the controls respond instantly while
      the expensive part, re-rendering the grid, stays in the transition.
- [x] **`make install-dev` now installs the scanners**, because a missing tool
      is reported as *skipped*, so a local scan without them passes by checking
      almost nothing. semgrep and pip-audit come from the new
      `backend/requirements-security.txt`; gitleaks is pinned in the new
      `scripts/tool-versions.env`, which `security.yml` sources too so local and
      CI run the same binary; snyk via npm, with a note that `snyk auth` is
      manual. `security.sh` also accepts the **gitleaks container image** as an
      alternative to the binary.

**Verified after all of the above:** `make lint` clean across 8 tools,
`make test` 330 backend tests at 70.1% and 69 Playwright tests at 77.6%, and
`make security` clean with every scanner actually present.

### Python version coverage

CI was pinned to 3.12 while both the developer machine and the production
server (Ubuntu 26.04) run 3.14 — so CI was testing a version nobody executes,
in either direction. The `test` job now fans out over **3.12, 3.13 and 3.14**
as three separate jobs with `fail-fast: false`, and the jobs that are not
version-specific (lint, migrations, build, security) moved to 3.14.

`requires-python` came down from `>=3.11` to `>=3.12` to match: 3.11 was never
tested by anything, and ruff, black and mypy targets moved with it. Verified
before pushing rather than after — throwaway venvs built from pyenv's 3.12.7
and 3.13.0: **330 passed on each, identical 70.07% coverage**, same as 3.14.

### A flaky security test, and the two it was missing

`test_tampered_token_rejected` failed once for the user and passed everywhere
else. It was not flaky by accident — it was wrong by construction:

    decode_access_token(f"{header}.{payload}.{signature[:-2]}xx", config)

An HS256 signature is 32 bytes carried in 43 base64url characters — 258 bits of
alphabet for 256 bits of signature — so the **last character's low two bits are
ignored on decode**. A canonical encoder always emits them as zero, which means
the final character is always one of the 16 values divisible by four, and `w`
decodes to the same bytes as `x`. Rewriting the tail is therefore a no-op
whenever the signature happened to end in `xw`: the "tampered" token is the
original, and it verifies. Measured over 50,000 tokens: **51 survived, 0.102%**
— almost exactly the predicted 1/1024.

It can only ever produce a false *failure*, never a false pass, so nothing was
unguarded. But a security test that cries wolf once a week is one people learn
to re-run instead of read.

Fixed by flipping a character in the **middle** of the signature, where all six
bits are significant, to a value guaranteed to differ. Verified: 0 survivors in
50,000, and 0 in 250,000 across the five parametrised positions.

Writing it also exposed that the suite only ever tampered with the *signature*.
Added the attacks that matter and confirmed the implementation already stops
them: rewriting the `role` claim to `admin` and keeping the signature, and the
classic `alg=none` forgery with an empty signature. Backend suite is now 330.


## 17. Running it for real — five bugs the first live catalog exposed

All found by the user running the app against Royal Tiger and Empire Arms, and
all fixed with regression tests. Migration **0003** carries the two schema
changes.

- [x] **"Failed / Browser" was a misdiagnosis, not a browser problem.** The
      Browser chip was `chip--warning` with a ⚠ icon on every browser-driven
      site, permanently, whatever Chrome's state. Sitting beside a red "Failed"
      it read as the cause and sent the user off to install a browser that was
      already working — verified by driving royaltigerimports.com headless:
      Chrome 152, chromedriver auto-resolved, 5.9s round trip. Now a neutral
      chip with its own icon. The actual failure was an app restart, and the
      reap message named two possible causes without saying which; it now says
      which, with the elapsed minutes.
- [x] **A sixteen-minute scan discarded everything on restart.** `run_scan` did
      `list(scraper.scrape(ctx))` — the whole catalog materialised before the
      first INSERT. It now consumes the scraper **lazily** and commits every
      `COMMIT_EVERY` listings, and `royal_tiger.scrape()` is a generator that
      yields each listing from the grid immediately and again once its detail
      page is folded in. De-listing still only runs when the iterable is
      exhausted, so a partial scan can never de-list what it never reached.
- [x] **A re-scan destroyed 207 galleries.** `_upsert_item` treated
      `image_urls` as authoritative and deleted anything absent — right after a
      detail fetch, catastrophic from a catalog grid that knows one thumbnail.
      Compounded by `needs_detail()` inferring completeness from "has photo
      rows", which was true of 210 listings whose photos had never been
      downloaded: the detail pass was skipped and the thumbnail pruned
      galleries of six and seven photos down to one. Royal Tiger went from
      1380 photo rows to 287 in a single scan. Fixed with
      `ScrapedItem.images_are_complete` (a preview may seed, never prune) and
      `Item.detail_fetched_at` (an explicit fact, not an inference). Every
      existing row starts NULL, so the next scan repairs the damage.
- [x] **Nothing was ever classified.** `classify.enrich()` returned
      `is_rifle`/`is_pistol` from the first commit and *nothing ever read them
      onto the row* — every listing on every site sat at the column default of
      False, so the "Rifles" filter matched nothing at all. Classification now
      happens in `_upsert_item`, where it is site-agnostic and no scraper can
      forget it. Two accuracy fixes came with it: the accessory vetoes read the
      **title only** (a real rifle's description says "the rifle bolt is
      matching", which vetoed 17 of 58 Empire and 61 of 210 Royal Tiger
      listings), and the **vendor's own category wins** when it names a type.
      Empire Arms now reads 37 rifles / 21 handguns / 0 other — exactly its own
      sections. Royal Tiger went 120/18/72 to 138/70/14. `make reclassify`
      repairs stored rows without a re-scrape; it fixed 266 of 280.
- [x] **"Times shown in" listed UTC twice** and defaulted everyone to it. The
      select hard-coded a UTC option *and* rendered one for the stored zone,
      which was UTC for everybody because that was the column default. The list
      is now built de-duplicated, and `display_timezone` is nullable so "never
      chosen" is representable and the browser's own zone can be offered.
- [x] **Traffic**: an unchanged gallery (same URLs, same order) is skipped
      outright; photo bytes are fetched once ever; detail pages once ever;
      `scraping.max_photo_downloads_per_scan` caps each run and logs the
      backlog it is carrying.
- [x] **`make stop` warns before interrupting a scan** (`make start` stops
      first, so restarting used to kill one silently). `milsurp running-scans`
      backs it; `FORCE=1` skips the prompt.

### Pagination, and why the suite never noticed

- [x] **"Next" never advanced.** `update()` exists to *clear* the page number —
      narrowing a filter renumbers the pages, so the old one means nothing —
      and the pager was routed through it, setting `page=2` and deleting it on
      the next line. Paging now has its own `goToPage()`, which is the one
      change that must not reset the page. Page 1 stays out of the URL, so
      "no page param" and "page=1" are the same place.
- [x] **The suite could not have caught it.** The demo catalog held 28
      listings against a page size of 48, so the pagination controls never
      rendered and there was nothing to click — the spec file's header comment
      claimed pagination was covered when no test existed. Seeded 40 bulk
      listings, and added four tests: next advances, previous returns and drops
      the parameter, the buttons disable at each end, and a filter change
      resets to page one.
- [x] **A test-ordering dependency, found while fixing that.** The new tests
      passed alone and failed in the full suite. `admin.spec.js` runs a real
      "scan now" against the demo vendor, and a scan correctly de-lists
      everything its scraper does not return — including hand-seeded listings.
      That silently dropped the catalog below one page before
      `inventory.spec.js` ran. Fixed at the source: the bulk filler is seeded
      only onto vendors nothing scans, so catalog size no longer depends on
      which test ran first. Out-tuning it by seeding more would have left the
      same trap for the next person.
- [x] **Paging returns you to the top.** The pager sits below 48 cards, so a
      page change always starts from the bottom; without it the new page
      arrives already scrolled past its own first rows and reads as though
      nothing happened. Instant rather than smooth — the content underneath is
      being replaced as it would animate, and on a long page the scroll is
      itself a wait. Its test scrolls to the bottom first and asserts
      `scrollY > 0` before the click, so it cannot pass by accident; verified
      by commenting the reset out and watching it fail.
- [x] `MILSURP_E2E_WORK_DIR` keeps the harness's disposable database after a
      run. Added because this failure only reproduced inside the harness, and
      guessing at it from the outside was going nowhere.

### The scheduler had silently stopped

- [x] **Scheduled scans stopped after each site's first run**, and had since
      the beginning. `due_site_ids()` compared `site.next_scan_at` — naive,
      because SQLite has no timezone type — against the aware `utcnow()`, which
      raises `TypeError`. The first scan of a site worked because
      `next_scan_at` was still NULL and never reached the comparison; every one
      after it threw.
- [x] **It was invisible.** `Scheduler._loop` isolates each tick so one bad
      tick cannot kill the thread — which meant a tick that raised every time
      looked exactly like a tick with nothing to do: a scheduler thread alive,
      ticking, and never scanning. Reported by the user noticing Empire Arms
      was 20 hours past a 12-hour interval; confirmed by calling
      `due_site_ids()` directly and getting the TypeError.
- [x] `as_utc()` is now a shared helper in models.py next to `utcnow()`, with
      the reasoning attached. digest.py had grown its own private copy, which
      is a fair sign the convention needed a home; it now uses the shared one,
      as does `reap_stale_runs`.
- [x] Regression tests in `TestDueSiteIds`. The important part is
      `session.expire_all()`: held in memory the value keeps whatever timezone
      Python assigned, and only a genuine read-back from SQLite is naive —
      without the expire the tests pass against the bug. Verified by reverting
      the fix and watching them fail with the exact TypeError.
- [x] Verified live: the first restart after the fix dispatched Empire Arms
      within seconds, `trigger=scheduled`.

### Serving, and the bundle the tests were overwriting

- [x] **Running the test suite replaced the app's bundle.** The Playwright
      harness built with `COVERAGE=1` straight over `frontend/dist` — the
      directory `make start` serves — so after `make test` the running app was
      serving coverage-instrumented code with nothing to say so. Worse, the
      fresh timestamp made `make start` consider dist up to date, so it would
      not rebuild and the swap survived a restart. The harness now builds to
      `frontend/dist-coverage` and points `MILSURP_FRONTEND_DIST` at it.
- [x] **The scheduler drains the photo queue itself.** A scan caps its own
      downloads so a first pass over a large catalog cannot run for hours,
      which is right — but it meant a backlog drained one batch per scan, and
      on a daily cadence that is days of listings with no pictures. The
      scheduler now works through the queue between scans
      (`scheduler.photo_tick_seconds`, default 180), one batch at a time, on
      its own single-worker pool so it can never occupy a slot a due scan
      needs. `make photos` / `milsurp fetch-photos` remains for doing it on
      demand, and is still worth having: a Royal Tiger scan is fifteen minutes
      of scraping to reach a download step whose URLs are already known.
- [x] **Site cards explain their scan time.** "2.2s" for Empire Arms next to
      "14m 36s" for Royal Tiger reads as a scan that did nothing. Verified it
      was real — a full Empire scrape times at 1.94s for all 58 listings, and
      the original 256s run was 244s of downloading 117 photos on airplane
      wifi. The tooltip now carries the counts, so a fast scan explains itself.
- [x] Site cards show **Scan time**: how long the last run took end to end.

### Roadmap additions

- [x] Only non-firearm category worth ingesting is **parts kits** — individual
      components are explicitly out of scope, with the reasoning recorded.
- [x] Axis Arms has two sections: `/product-category/rifles/` and
      `/product-category/handguns/`.


## 18. Hunter's Lodge — the OCR vendor, built end to end

A vendor whose entire catalog is one scanned magazine advertisement. Built as
`scrapers/hunters_lodge.py` (the vendor) plus `scrapers/flyer.py` (reusable
flyer machinery), and verified against the live site.

- [x] **Change detection first.** A scan reads the flyer's Wix media id and the
      month/year above it and stops if neither has moved: **0.19s, one request,
      0 de-listed, 22 listings left standing.** Cadence defaults to weekly.
- [x] **`ScrapeContext.report_unchanged()`** — needed because "I checked and
      there is nothing new" is not "the catalog is empty". Without the
      distinction, an unchanged flyer would have de-listed the whole site.
- [x] **Full resolution matters.** Wix serves a 600x844 resize; stripping the
      `/v1/fill/...` transform gives the 4813x6774 original, which is the
      difference between OCR that works and OCR that returns nothing.
- [x] **Generated images.** `ScrapedItem.generated_images` plus
      `ImageStore.store_bytes()`: a scraper can now hand over image *bytes*
      with a stable key instead of a URL, stored with the same layout, naming
      and thumbnailing as a download. 22 crops written and thumbnailed.
- [x] Tesseract in both installers, `pytesseract` in requirements, imported
      lazily so a machine without OCR runs everything else normally.
- [x] 48 tests: the layout, price, heading, grouping and cropping logic against
      synthetic pages; the scraper against stubbed markup. No network, and no
      checked-in copy of someone's copyrighted advertisement.

### Three things the flyer taught me, each of which cost an attempt

- **Whitespace cutting finds nothing on a ruled page.** The textbook approach
  is a recursive XY-cut on blank gutters. Of the flyer's 4813 pixel columns,
  *not one* is free of ink, because the panel borders run the full height. The
  rules that defeat the cut are themselves the layout, so the reader cuts on
  them instead.
- **Whole-page OCR merges columns.** Tesseract returned the line "1940'S U.S.
  MILITARY GAHENDRA MARTINI "OLE ZEKE'S" TREASURES" — three headings from three
  columns in one string. Reading a column at a time removes the ambiguity
  rather than trying to undo it. Reading *finer* regions than a column is
  worse: those cuts fall on rules that run through words, and the OCR comes
  back as "wil", "th more", "al \\".
- **Size does not identify a heading; capitals do.** An all-caps heading's
  bounding box is no taller than lowercase prose with ascenders and descenders,
  so a height rule found 5 headings where there were 30. Every product name on
  the flyer is set in capitals and no sentence of description is.

### Honest accuracy

22 listings recovered from the real July 2026 flyer with names and prices —
most of the page, not all of it, and a few take a neighbouring panel's price.
Every listing carries the crop it was read from and keeps the raw OCR as its
description. Two follow-ups are recorded unticked in ROADMAP.md: recursive
in-column splitting for the boundary errors, and using Tesseract's per-word
confidence to mark a doubtful price PARTIAL rather than writing it silently
into the price history.

## 18b. Tightening the flyer reader, from real feedback

Every one of these was reported by looking at the listings the first version
produced, and each has a test.

- [x] **Whole product names.** "S&W" / "K-FRAME," / "SNUB-NOSE" / "REVOLVER
      KITS" is one name in four lines and only the last survived. A *run* of
      heading lines is now one name, so "S&W K-FRAME SNUB-NOSE REVOLVER KITS",
      "S&W MODEL 10 PISTOLS", "CZ 50/70 PISTOL KITS" and "GAHENDRA MARTINI
      BEAUTIFUL HANDSOME WOOD STOCK SET" all come out whole.
- [x] **Panels bound a listing.** "PISTOL KITS" was one panel's name attached
      to the next panel's price: the CZ 50/70 kit read as $322.88, which is the
      Turkish Mauser below it. The page is cut recursively on its own rules and
      a panel boundary now ends a listing — except for a heading, which is
      allowed to cross exactly one, because the flyer draws a rule between a
      product's name and its description.
- [x] **Page furniture is not a product name.** The masthead and the payment
      terms box are set in capitals too, so they read as headings and drifted
      to the front of a title: "OR MONEY MAUSER C96 PISTOL KITS".

Result on the real July 2026 flyer: 26 listings, up from 22, and the four
products that were reported wrong are now right.

## 18c. Heading attachment, measured

The third pass at the flyer, and the first done with a number rather than an
opinion. The metric is "does this listing's title begin with a product name" —
crude, but consistent enough to compare two versions of the code against the
same page, which is what stopped a change that felt better from being kept when
it was not: an early variant scored 85% against 77% while getting *fewer* of
the named products right.

**60% → 88%** (23 of 26 listings), from four fixes:

- [x] A product's name is set **on** the rule beneath the panel above it, so
      assigning a line to a panel by its midpoint dropped it in the gap between
      two panels, where it belonged to neither. That read as a panel change and
      cut the name off from its own description. Panels are now assigned by
      area of overlap, falling back to the nearest panel below.
- [x] A group that ended without a price was **discarded**, and it is almost
      always a name looking for one. Its heading lines are now carried into the
      next listing. This is what fixed the listings titled "needs TLC" and
      "frame for" — the tail of a bulleted line whose beginning had gone with
      the heading.
- [x] A bulleted line is a product; anything above it is the section header the
      list sits under. "OLE ZEKE'S TREASURES" was taking the title of the first
      item beneath it.
- [x] Everything on this page is named in capitals, so lower-case words ahead
      of the first capitalised one leaked in from a neighbouring panel:
      "Swedish steel. GAHENDRA MARTINI RIFLE".

Also removed `_attach_headings`, which had become dead code when panels stopped
being the unit of grouping and was still described in a docstring as if it ran.

**Still wrong: three of twenty-six.** "1903 TURKISH CONTRACT MAUSERS", "WW2
ENFIELD NO1 MK2 PARTS KITS" and "CZ 52 SEMI AUTO ASSAULT RIFLES" take their
title from their own prose, because in each case the heading is across a
*column* boundary from its body — the one boundary nothing may cross, since
crossing it is exactly what made a product quote its neighbour's price.

## 18d. Listings shown under each other's photographs

Reported from the UI: on the Handguns filter the S&W Model 10 showed the VZ24
bayonet; on Rifles, every listing showed the *next* one's crop.

The consistent one-place shift was the clue. The data was never wrong — the
crops on disk, the thumbnails, and the item-to-photo rows all check out, and
the endpoint has no ordering logic to get wrong. The URL was the problem:

```
/api/items/<item_id>/photos/<photo_id>     Cache-Control: private, max-age=86400
```

- [x] Neither id is stable. SQLite reuses a rowid after a delete, so clearing a
      site and re-scanning it hands the same URL to a different picture — and I
      did exactly that, twice, while improving the flyer reader.
- [x] The comment justifying the 24-hour cache said the content was immutable
      "because the filename is a hash". The filename is a hash of the image's
      *source*, not of its bytes, and the URL is neither. For a generated crop
      the source key is deliberately stable while the bytes change with every
      improvement to the reader, so that reasoning was wrong twice over.
- [x] Now `private, no-cache`: stored, but revalidated before every use.
      FileResponse already sends an ETag and Last-Modified from the file, so a
      repeat view costs a 304 and no image bytes. Tested.

Anyone who looked at the old URLs still has them cached until they expire, so
one hard refresh is needed to clear what is already there.

## 18e. Bulleted lists, and where the price actually is

Reported: British No4 Mk1 rifles at $88, Spanish M43 rifles, the Jap Arisaka
barrelled receiver — all missing, and other listings holding their prices.

- [x] **OCR drops the bullet glyph, and the lines are not caps-heavy enough to
      read as headings.** A list sets each name in capitals and continues in
      sentence case: "BRITISH NO4 MK1 RIFLES as is $88.00." So those items were
      swallowed by the one above and their prices went with them — the bayonet
      grab bag was priced at the British No4's $88. A line that *opens* with a
      product name and carries its own price now starts a new item, whatever
      OCR did to the bullet. Guarded by "only once the item being assembled has
      a price", or a wrapped name splits from its own description: ".38 SNUB" /
      "NOSE HOLSTER ... $14.50." would become two listings.
- [x] **The first price, not the largest.** The page states a price once, where
      the description ends, and anything after it is terms. Taking the largest
      was defensible — a firearm costs more than its options — right up until a
      listing's text bleeds into its neighbour's, and then it reaches over and
      takes the bigger number: blankets at $99.00 instead of $36.88, a
      barrelled receiver at $47.88 instead of $45.00. Both variants were
      measured against the same page before choosing.

**26 → 30 listings, 88% → 90% with a real product name**, and the prices that
were wrong are right.

## 18g. Titles read word by word, not line by line

Two observations from reading the page, both right and both acted on:

- [x] **Names wrap mid-word.** "SWEDISH LEATHER AMMO BELT/BANDO-" on one line
      and "LIER can fit a variety of rifle" on the next. Reading line by line
      stopped at the hyphen and produced "BELT/BANDO", which is not a word.
      Titles are now built word by word with the hyphenated halves spliced back
      together, so it reads "SWEDISH LEATHER AMMO BELT/BANDOLIER".
- [x] **The name and the description meet mid-line**, so the boundary is
      between two words rather than two lines. The name is the leading run of
      capitalised words; digits and punctuation carry through, because a name
      is full of them — "6.5MM", ".303", "1940'S", "S&W", "K-FRAME,". This is
      what turned "COLT PP .38 FRAMES. Most have bbl& maybe few parts" into
      "COLT PP .38 FRAMES", and "BRITISH NO4 MK1 RIFLES as is" into the name
      alone.
- [x] Page furniture is now stripped from each line *before* the name is read
      off it, not from the finished title. Doing it afterwards emptied the CZ
      50/70 title completely: a scrap of the masthead had been carried in as
      its heading, the name was read from that, and then all of it was removed.

**The bold idea was tested and not used.** Measuring ink density per word does
separate the bold names from the body — SWEDISH 57%, BRITISH 56% against
variety 24%, cartridge 26% — but short words score high whatever their weight
("a" 54%, "can" 46%), because the measure is confounded with word shape.
Capitalisation is a cleaner separator on this page and needs no calibration.

## 18f. Listings shown under each other's photographs

Reported twice, and the second time was the useful one: on Rifles, every
listing showed the *next* one's crop — a consistent one-place shift.

The data was never wrong. The crops on disk, the thumbnails, the item-to-photo
rows and the API response all check out; I rendered the served thumbnails and
each was its own product. The URL was the problem:

```
/api/items/<item_id>/photos/<photo_id>     Cache-Control: private, max-age=86400
```

- [x] Neither id names its content. SQLite reuses a rowid after a delete, so
      clearing a site and re-scanning it — which I did repeatedly while
      improving the flyer reader — hands the very same URL to a different
      picture. Every browser that had seen the old one kept showing it for a
      day, and reloading could not help, because the URL genuinely had not
      changed.
- [x] The comment justifying the 24-hour cache said the content was immutable
      "because the filename is a hash". The filename hashes the image's
      *source*, not its bytes, and the URL is neither — and a scraper that
      generates its own images keeps the source key deliberately stable while
      the bytes change with every improvement to the reader.
- [x] Photo URLs now carry `?v=<token>` derived from the file's name, size and
      store time, so changed content is a changed URL that no cache can match.
      `Cache-Control: private, no-cache` stays as well, because a cache holding
      one of the old unversioned URLs has no other way to find out.

The first attempt at this was to tell the user to hard-refresh. That was a
guess dressed up as a diagnosis; the evidence for it came afterwards, and did
not support it.

## 19. A classification bug the flyer exposed

- [x] **A blanket is not a rifle, and Colt frames are pistols.** Three separate
      faults, all reported from looking at real listings:
      1. Neighbouring prose bleeds into a listing's description on an OCR'd
         page, and hand-woven Vaquero blankets were filed as a rifle. Goods
         sold beside firearms — blankets, helmets, patches, books — are now
         vetoed outright.
      2. "COLT PP" was not a pattern at all, so Police Positive frames were
         neither rifle nor pistol.
      3. Where title and description disagree, **the title wins**. The C96
         pistol kits picked up "8mm Mauser" from the column beside them and
         stopped being a handgun on the strength of it; a rifle caliber no
         longer overrules a title that names a pistol and nothing else.
- [x] **A cheap frame is still a firearm.** The $70 price floor keeps slings
      and pouches out of the firearm filters, and it should: a $25 "Mosin
      Nagant rifle" is a book or a toy. But a frame or a receiver *is* the
      firearm — it is the serialised part — so "COLT PP .38 FRAMES" at $29 is a
      handgun. "Parts kit, no frame" is still nothing, which is the whole point
      of a dealer saying so. The existing test for the floor caught the first
      attempt at this, which had simply overruled it.
- [x] **`\brifle\b` never matched "RIFLES".** The patterns were singular-only,
      so every title naming more than one firearm went unclassified — which on
      a dealer's catalog is most of them. Six of the eight plural titles in the
      stored catalog were filed as neither rifle nor pistol. Now `\brifles?\b`
      and the same for carbines, pistols, revolvers and handguns; model names
      left alone, because nobody writes "SKSs". `make reclassify` repaired the
      stored rows.

## 20. Roadmap reorganised by backend and audience

- [x] The 26 remaining vendors are grouped by **platform** — WooCommerce (10),
      BigCommerce (3), Shopify (4), Shift4Shop (2), one-offs (6) — because one
      base class unlocks a whole group, with the most popular site first inside
      each so the base class is proved against the catalog most worth having.
- [x] Traffic estimates are quoted **with their source and date** where one
      exists (Classic Firearms 1.6M/3mo, Atlantic Firearms ~837K/mo, AIM
      Surplus ~357K/mo, Collectors Firearms ~284K/mo). The rest are ordered on
      softer evidence, and the section says so rather than implying a precision
      that is not there.
- [x] Checkboxes throughout, maintained as items are finished.


---

## 21. Domain knowledge the rules could not derive

Reported from the live catalog by the site's owner, who knows the trade.

- [x] **"BBL REC" is a barreled receiver**, and a barreled receiver is a rifle.
      Added to the frame/receiver pattern, which already exempted the serialized
      part from the $70 price floor.
- [x] **"WW2 Enfield No1 Mk2 Parts Kits" is an Enfield revolver**, not the SMLE
      rifle that shares most of that designation. This is not derivable from the
      words, so it lives in `KNOWN_DESIGNATIONS`, a small table consulted before
      everything else — including the vendor's own category. The pattern is
      deliberately narrow: `No.1 Mk III` is the rifle.
      This overturned a tested rule (a kit saying "no frame" is not a firearm).
      The owner counts these kits among the handguns, so a *named* designation
      now outranks the no-frame veto; an unnamed "parts kit, no frame" still is
      not a firearm.
- [x] **A Mauser C96 is a handgun.** Mauser is a maker who built both, so the
      maker's name alone no longer outvotes a model name (`_AMBIGUOUS_MAKERS`).
- [x] **Any "parts kit" is parts and accessories**, whatever it is a kit for and
      whatever it costs — an Ethiopian Gafat AK kit at $449 is a box of parts.
      A kit named for a handgun ("Revolver Kits", "Pistol Kits") is the dealer's
      own way of selling a handgun and is deliberately not caught.
- [x] **A buttstock is not a rifle**, and neither is a **loose barrel** — but a
      *barreled action* still is. Barrels are ordered against the firearm nouns
      rather than vetoed outright, so "Berthier barreled action, shortened
      barrel" survives.
- [x] **A "pistol holster" is a holster.** English puts the head noun last, so
      an accessory word directly following a firearm noun is the product. A
      Mauser C96 holster was a handgun before this.

## 22. Cross-catalog field filling — built, and honest about being dry

The idea: a flyer read by OCR gives a title and nothing else, so borrow the
caliber from a vendor who describes the same rifle properly.

- [x] `app/services/crosscatalog.py`, `milsurp infer`, 15 tests.
- [x] **Titles only.** Matching on descriptions was tried against the live
      catalog and was not useless but *confidently wrong* — a Russian 91/30 came
      back as a 6.5x52mm Carcano made by Remington, on words two paragraphs
      happened to share. A description is prose, and on an OCR'd flyer it is
      prose about whatever was printed nearby.
- [x] Four guards: fills only blanks; scores words by rarity, normalized so a
      threshold means the same thing at any catalog size; needs two nearly
      unique words and a third of the smaller vocabulary; and donor and
      recipient must agree on rifle/handgun/neither.
- [x] Result on the current catalog: **nothing**, which is the right answer for
      two-and-a-bit vendors and what the owner expected.

**This cost real damage before the guards were in.** The first version was run
and committed against the live database, filling 238 fields with nonsense. There
was no backup. Recovery was a full re-scrape of Royal Tiger and Empire Arms with
`detail_fetched_at` cleared, because `_upsert_item` assigns those three columns
unconditionally from the scraper. Hunter's Lodge supplies none of them, so its
rows were simply nulled. Which led directly to:

## 23. Daily database backups

- [x] `app/services/backup.py` — SQLite's online backup API, not a file copy: a
      copy taken mid-write catches a torn transaction, and under WAL the file on
      disk is not the whole database.
- [x] Daily in production, ten kept, `backups/` gitignored, **off in dev**.
- [x] Dispatched from the scheduler by the age of the newest snapshot rather
      than by a timer, so restarts do not skip a day.
- [x] `milsurp backup` for taking one by hand before something risky.
- [x] 11 tests, including that the snapshot opens and that it is mode 600.

## 24. The maker list as data

- [x] `manufacturers` table (migration 0004), seeded from the built-in tuple the
      first time it is empty, and left alone thereafter — a maker deleted on
      purpose stays deleted across restarts.
- [x] Aliases are **literal text, escaped**, never patterns: they come from a
      form. Whitespace inside a name is allowed to stretch, so "Smith & Wesson"
      matches "SMITH  &  WESSON".
- [x] `position` is part of the data, because order decides ties —
      "Mosin-Nagant" has to be tried before "Nagant". Both directions are tested.
- [x] Admin-only CRUD at `/api/manufacturers`, and an admin page at
      `/manufacturers`.
- [x] **An edit re-files the catalog** and reports how many listings moved. The
      query is narrowed to rows whose text contains one of the strings involved
      — the ones being added *and* the ones being taken away, or a narrowed rule
      leaves its old answer behind.
- [x] 32 tests across the service and the API.

## 25. The Ottoman Mauser, and the rest of the titles

Reported: "the ottoman mauser got its title cut off in the image and the data."

- [x] **The heading was never read.** "1903 TURKISH CONTRACT MAUSERS" is
      underlined, set directly over the rifle's photograph with the panel rule
      beneath it, and tesseract's layout analysis called the whole thing a
      picture — the words were absent from the word table, not merely low
      confidence. The layout-free second pass (added for prices) now also
      contributes **headings standing in a band of the page where the first
      pass read nothing at all**. A band with nothing in it cannot be corrupted,
      which is what makes taking a whole line safe there when it is not safe
      anywhere else.
- [x] **The picture was cut off too**, and stayed cut off across a re-scan:
      generated crops were recognized by their key, and the key does not change
      when the *reader* changes. Now the bytes are compared, so a crop follows
      the code that cuts it. This is the general case of the reported bug — every
      listing was showing the picture it had been cut before, under its new
      title.
- [x] **A name ends where its heading ends.** Once a heading line has
      contributed, a line that is not itself a heading is description, and the
      capital it opens with is the start of a sentence: "1903 TURKISH CONTRACT
      MAUSERS" had acquired the "MFG" of "MFG by germany". A hyphenated break
      still crosses into the prose.
- [x] **Terms are not names.** Every listing says who may buy it, in the same
      capitals as its name. A line that is only terms is dropped whole rather
      than trimmed — trimming the front of "C&R or FFL" leaves "FFL", which then
      reads as the next word of the name above it.
- [x] **A section header is not a name.** "OLE ZEKE'S TREASURES" sits above an
      unbulleted list and was taking the first product's title. Dropped only in
      front of a line that names itself in capitals and then keeps talking,
      which is the shape of a section above a list and is not the shape of a
      name broken across lines.

Titles now read correctly for **29 of the 30** listings on the flyer. What is
left: the axe/stock-set panel (#7), which is genuinely two products in one box,
and a $38.88 second-price option split off the Enfield (#12).

## 26. C&R and FFL are licenses, not products

Reported: "C&R and FFL are types of licenses from the ATF not product things
that have a price."

They are on every surplus listing, because every listing has to say which one a
buyer needs — and that makes them behave like a product name. They are set in
capitals like one and they sit next to a price like one: "Add frame for $38.88.
C&R/FFL required."

- [x] `classify.names_only_a_license()` and `LICENSE_PATTERN` — the domain fact,
      in the module where the domain facts live. A title that is *only* a
      license names nothing, and this is checked ahead of the vendor's own
      category, because no category can make a license into a rifle. A listing
      that merely *requires* one is untouched.
- [x] `is_ruled_out()` includes it, so the cross-catalog filler knows the
      silence is a decision rather than ignorance.
- [x] The flyer reader absorbs a priced group with no name of its own into the
      listing above it instead of publishing it. The $38.88 "C&R/FFL" was the
      second half of the Enfield kits, split off by a rule falling between two
      lines. Put back rather than dropped: the option belongs in the
      description and the box belongs in the crop.
- [x] `classify_firearm()` grew past the branch limit, so the rifle-versus-
      handgun tie-break came out into `_break_the_tie()`.

## 27. Listing keys follow the product, not its place on the page

Not reported — caused by the work above, and found by reading the scan summary.

The key was the ordinal, `{flyer}-{index:03d}`, which is stable only for as long
as the reader is. Removing the phantom C&R/FFL listing shifted every key after
it onto a different product, and the scan service read that as the lower half of
the flyer changing price at once: **17 price changes and 10 drops, none of which
had happened**. A price-drop email is worth nothing if it can do that.

- [x] The key is now derived from the listing's own title, so a listing keeps
      its identity and its history while it keeps its name, and one we now read
      differently is honestly a different listing. Duplicates within a flyer are
      numbered.
- [x] `ScrapeContext.already_seen(prefix)` replaces the `-001` probe, since
      there is no longer a predictable first key. Backed by an indexed LIKE on
      the site's keys.
- [x] Hunter's Lodge price history was deleted and the site re-scanned from
      scratch: every point in it had been fabricated by the key shuffle, so
      there was nothing real to keep.

## 28. `prune-images` was deleting every thumbnail

Not reported — found by checking the output of a prune I ran, which said it had
removed 1,942 files and reclaimed 81 MB when about 60 files should have gone.

A photo row names two files, the original and its thumbnail, and
`cmd_prune_images` collected only `filename` into the set of referenced files.
Every thumbnail in the store was therefore an orphan. This is the worst shape
for such a bug: the originals survive, so nothing looks broken until somebody
opens the browse grid and every card is blank.

- [x] The prune now collects both columns.
- [x] `ImageStore.write_thumbnail()` extracted from `_make_thumbnail()`, so a
      thumbnail can be rebuilt from the original already on disk. No network:
      losing a derived file is not a reason to ask a vendor for the picture
      again.
- [x] `milsurp rebuild-thumbnails` (`--all` to redo them all). Ran it: 1,482
      rebuilt, and the store is whole again — 1,586 photos, 0 missing files.
- [x] Both halves tested, including the bug itself, so the fix cannot be
      quietly undone.

## 29. robots.txt, obeyed

Built before the WooCommerce work rather than after it, because the first shop
on the list turned out to have rules that decide the design.

- [x] `app/robots.py` — RFC 9309: wildcards, `$` anchoring, longest match wins,
      ties to allow. **The standard library was not good enough**: measured
      against collectorsfirearms.com's real file, `urllib.robotparser` ignored
      `Disallow: /*?*` entirely and applied rules in file order, so
      `Allow: /wp-admin/admin-ajax.php` under `Disallow: /wp-admin/` came back
      disallowed. Both errors were in the direction of crawling more than
      permitted.
- [x] Enforced in `ScrapeContext.get()` before a request is made, with
      `ctx.allowed(url)` public so a scraper can pick another route instead of
      failing, and `Disallowed` as its own exception type.
- [x] **`Crawl-delay` is honored** and becomes the floor on the politeness
      delay. Collectors Firearms asks for ten seconds, which makes a scan of
      their catalog half an hour of wall clock. That is their call to make.
- [x] A robots.txt that cannot be read — 5xx, 403, connection failure — means
      the site is off limits, not open. Erring the other way would let a blip
      quietly switch off every restriction a vendor has.
- [x] `scraping.obey_robots`, on by default, off in the test config (the
      scraper tests mock a vendor's pages, not its robots.txt). 33 tests.

## 30. WooCommerce base class, and the first of the ten

- [x] `app/scrapers/woocommerce.py`: `li.product` cards, the WordPress post id
      as the external key (a slug can be edited, a post id cannot), sale-aware
      prices, lazy-loaded images, gallery de-duplication, and pagination by
      following the shop's own "next" link rather than computing page numbers.
- [x] `app/scrapers/collectors_firearms.py` — foreign and U.S. military rifle
      sections only. They carry ~207,000 products; their military handguns are
      not separately categorized, so handguns are left until they are.
- [x] Selector overrides go *in front of* the stock ones, so a theme reverting
      does not break the scraper.

**The Store API is a trap on this platform.** Every one of these shops publishes
`/wp-json/wc/store/v1/products`, returning exactly the structured data the HTML
parsing recovers by hand. Filtering it to a category, or reading past the first
ten products, needs a query string — and Collectors Firearms disallows `/*?*`.
Reading 207,000 products ten at a time to find the rifles is not an alternative
to reading seventeen category pages. Re-check per shop: where robots permits, a
subclass can override `scrape()`.

**Two of the ten are behind Cloudflare.** dkfirearms.com returns a 403 challenge
to plain HTTP, so it needs the browser path Royal Tiger already uses. That is a
per-site fact, not a platform one.

- [x] Sale prices: WooCommerce renders `<del>$600</del> <ins>$450</ins>`, and
      taking the first amount would report the price the shop is no longer
      asking — hiding the drop this application exists to notice.
- [x] Gallery de-duplication: WordPress stores a large upload twice, as
      `foo.jpg` and `foo-scaled.jpg`, and offers each at half a dozen generated
      sizes. Eleven photographs were coming back as twelve URLs.
- [x] 23 tests, against written markup rather than a saved copy of the shop's
      page.

## 31. Descriptive fields derived where a vendor has none

Found by reading the first Collectors Firearms rows: every rifle had "7.62x54R"
in its title and nothing in the caliber column.

`_upsert_item` was computing `classify.enrich()` and then using only the
rifle/handgun split from it. Royal Tiger publishes caliber, country and
condition as their own fields, so the gap never showed; a WooCommerce shop has
nowhere structured to put them.

- [x] The three fields fall back to what the text says, filling gaps only —
      a value the vendor stated is theirs.
- [x] `milsurp reclassify` backfills them, so an existing catalog gets them
      without asking any vendor for its pages again.

## 32. A 429 is an instruction, not a hiccup

The first live scan of Collectors Firearms failed after sixteen minutes and
ninety listings with `429 Too Many Requests` — while keeping to the ten-second
`Crawl-delay` their own robots.txt publishes. Their limiter counts over a window
that ten seconds a request eventually fills.

The retry logic treated 429 exactly like a flaky 500: back off one to four
seconds and try again, which is asking too often again. Four attempts later the
run failed. Seventy-two listings survived, because the scan commits in batches —
the interrupted-work design doing its job.

- [x] `Retry-After` is honored, in seconds or as an HTTP date.
- [x] A 429 sets a **standing** slower pace for that host for the rest of the
      scan, doubling with each further refusal, capped at 300s. It is never
      reset: a scan told twice to slow down has no business speeding up again
      before it ends.
- [x] A 500 still gets the short retry it wants. The two failures want opposite
      things and no longer share a path.
- [x] The run says it was told to slow down, so a scan that suddenly takes six
      times as long is not a mystery to whoever reads it later.
- [x] `min_request_delay` on the scraper, for a shop measured to need more than
      it asks for. Collectors Firearms is set to 20s. Obeying a stated delay and
      being refused anyway means the stated delay is not the real one.

The detail pages are fetched once per listing ever, so it is the *first* scan
that is long. Later ones only pay for what is new.

## 33. Deriving facts from prose that is not about the listing

Found by reading the rows `reclassify` had just filled in: hand-woven Vaquero
blankets in 8mm Mauser from Sweden, a Japanese Arisaka from Sweden, a Gahendra
Martini from Sweden.

Section 31 had `_upsert_item` derive caliber, country and condition from title
*and description*, which is right for a vendor whose prose is about the thing it
is attached to. It is wrong for Hunter's Lodge, whose whole catalog comes off
one scanned page and whose "description" is whatever OCR read nearby. This is
the same lesson section 22 had already learned for cross-catalog matching, and
it was not applied here.

- [x] `SiteScraper.descriptions_are_reliable`, false for Hunter's Lodge, honored
      by `classify.enrich(trust_description=...)`, `_upsert_item` and
      `reclassify`.
- [x] Only the *derived* fields honor it. The description is still stored, still
      shown, and still read by the rifle/handgun rules — a judgement about a
      whole block of text survives some contamination; a specific claim like a
      caliber does not.
- [x] Measured before choosing: a global "titles only" rule would have cost
      Royal Tiger 89 countries and Empire Arms 24 calibers. The per-source flag
      costs nothing on the sources that deserve trust.

### And two the title itself got wrong

- [x] **A maker's name is the last resort for a caliber, and never for a
      handgun.** Mauser and Enfield each made a famous rifle and a famous
      revolver; the bare name points at the rifle. "MAUSER C96 PISTOL KITS" was
      in 8mm Mauser — the 98's cartridge, not the C96's — and "ENFIELD NO1 MK2
      PARTS KITS", a .38 revolver, was in .303 British. The handgun test
      consults `KNOWN_DESIGNATIONS`, so a designation whose name says nothing
      about being a handgun is still caught.
- [x] Demoting those rules below the explicit spellings is a fix in its own
      right: "Spanish Mauser 7x57" was answered "8mm Mauser" because the maker
      rule was reached first.
- [x] Plural: "1903 TURKISH CONTRACT MAUSERS" is not `\bmauser\b`.

**A note on how this was verified.** Re-deriving the catalog meant clearing the
caliber column for every site, which would have discarded vendor-supplied values
had there been any. Empire Arms parses calibers off its pages, lost seven, and
was restored by a 3-second re-scan. Royal Tiger turned out never to have had
any — its caliber is derived by `enrich` too — so the one row that changed there
was a Mauser C96 *holster* correctly losing a caliber it should never have had.
Next time: null the site that is wrong, not the column.

## 34. Signing in returned a 500 while a scan was running

Reported: "why am i getting a 500 trying to log in while that scan is running?"

SQLite has one writer. A scan takes the write lock the moment it saves a listing
and holds it until it commits, and it was committing every twenty-five listings
— so the lock was held for however long the vendor took to hand over the next
twenty-five. At Royal Tiger's pace that is half a minute and mostly went
unnoticed. At the twenty seconds Collectors Firearms needs it is **eight
minutes**, and every write the web application attempted in that window waited
out its fifteen-second `busy_timeout` and failed. Signing in updates
`last_login_at`, so signing in was one of them.

The `min_request_delay = 20.0` added in section 32 is what turned a latent
problem into a reproducible one. A slower crawl is politer to the vendor and, as
written, ruder to everybody using the application.

- [x] `COMMIT_SECONDS = 2.0`: commit on a clock as well as on a count, so the
      lock is never held across a network wait. The count is kept, because
      batching is what makes a fast scan cheap.
- [x] Tested by comparing a slow clock against a fast one rather than against a
      fixed number — a scan commits a few times whatever happens, and what is
      under test is the commits the *listings* cause.

- [x] And the failure mode, asked for separately: a locked database is answered
      **503 with `Retry-After: 5`**, not 500. Nothing is broken, the request was
      not refused, and it will very likely work if made again in a moment —
      which is what 503 means and 500 does not. Only a lock says this; a missing
      table or a disk that has gone away keeps its 500, or a real fault would
      spend its life being politely retried. The message names the likely cause
      ("a scan is running") and the frontend already shows `detail` verbatim, so
      it reaches the person looking at the screen.

---

## Context for whoever picks this up

### Where work stopped

Everything the user has asked for is built, and the first real CI run has been
triaged end to end (section 16). The working tree is lint-clean, both suites
pass over their gates, and `make security` is clean with every scanner
installed.

### Immediate next steps, in order

1. **Commit and push.** The user commits; I never run git. The changes since
   `v1.0.0.0` are the section 16 fixes plus the dependency upgrades.
2. **Watch the next CI run.** Expected green. The one thing that cannot be
   verified locally is whether GitHub's code-scanning UI honors the in-source
   `# codeql[...]` suppressions in `cli.py`. If alerts #1 and #2 come back,
   dismiss them in the Security tab as "won't fix" — only the user can, since I
   must not run `gh`.
3. **Section 13's open item** — a test for the production-only access-request
   endpoint. Needs a fixture that builds a `MILSURP_ENV=production` config with
   `email.enabled`, since the endpoint deliberately 404s in dev.
4. **ROADMAP.md** is the backlog from here: the vendor sites, deb/PPA to
   Launchpad on version tags, and the Electron snap.

### Environment

- Repo: `/home/bceverly/dev/milsurp`. Python 3.14.4, node 22, Google Chrome at
  `/usr/bin/google-chrome`.
- `.venv` exists with runtime deps plus `pytest`, `pytest-cov`, `responses`,
  `httpx2`, `Pillow`. **Not yet installed:** `ruff`, `black`, `mypy`, `bandit`
  — they are listed in `backend/requirements-dev.txt` and installed by
  `make install-dev`. Until then `make lint` reports them as skipped rather
  than failing.
- `frontend/node_modules` installed; Playwright chromium downloaded
  (`npx playwright install chromium` was run).
- `httpx2` had to be installed for Starlette's `TestClient` on this Starlette
  version; it is a test-only dependency and is **not** in
  `requirements-dev.txt` yet — add it.

### Running it

```bash
# A dev config lives in the scratchpad, NOT in the repo:
#   /tmp/claude-1000/-home-bceverly-dev-milsurp/<session>/scratchpad/devcfg.yaml
# It sets admin password "correct-horse-battery-staple" and scheduler.enabled: false.
#
# For a clean start instead:
make config          # writes config.yaml from the sample, mode 600
$EDITOR config.yaml  # set admin.password (12+ chars)
make init            # migrate + seed sites and the admin account
make start           # prints the URL, e.g. http://localhost:8730
make stop
```

- The dev database currently holds **58 real Empire Arms listings with 117
  photos**, scraped live, with thumbnails generated. Royal Tiger has *not* been
  fully scanned (it takes several minutes and drives Chrome), though its
  gallery extraction was verified directly against live product pages.
- **Watch out:** on a fresh database every site is immediately due, so starting
  the app kicks off a real Royal Tiger scan and launches Chrome. Set
  `scheduler.enabled: false` in `config.yaml` while developing. This is also
  why the pytest config disables the scheduler.

### Verified working

Screenshotted end-to-end with Playwright, zero console errors: sign-in,
inventory grid, item detail (multi-photo gallery + price history), site admin,
email digest settings, user admin, and the mobile layout at 390x844.

### Test/lint commands

```bash
make test-backend    # pytest; currently FAILS on the 65% gate (57.4%)
make lint            # black first, then everything; skips uninstalled tools
make security        # bandit/semgrep/snyk/audits/gitleaks; skips uninstalled
make migrate-status  # shows current vs head schema revision
```

### Known rough edges

1. **Empire Arms descriptions pick up trailing page boilerplate** ("HOW TO ORDER
   FROM EMPIRE ARMS: …", and a stray `<img border="0"` fragment). Visible on the
   item detail page. Fix in `backend/app/scrapers/empire_arms.py` — truncate the
   block at the known footer markers.
2. `scripts/dbupdate.py --quiet` still prints alembic INFO lines; lower the
   `alembic.runtime.migration` logger level when `--quiet` is passed.
3. `make test` will fail until backend coverage reaches 65% and the frontend
   suite exists. That is the gate working as specified, not a bug.

### Decisions worth not re-litigating

- **Alembic is the only thing that creates schema**, including on a brand new
  database. There is no `create_all()` anywhere. Every migration is written to
  be idempotent via `backend/app/migration_utils.py`.
- **Dev state layout:** SQLite at the repo root (`milsurp.db`), scraped photos
  under `data/images/`. The repo-root `images/` directory is gitignored and
  unused; committed screenshots and brand assets live in `marketing/images/`.
- **Photos are never static files.** They are served by an authenticated
  endpoint that resolves a DB-stored relative path against the image root, with
  a traversal guard. Two resolutions are stored, both generated locally during
  the scan.
- **Session tokens** live in `sessionStorage` with a `token_version` counter on
  the user row, so a password change revokes every issued token. Moving to an
  HttpOnly cookie is captured in `ROADMAP.md` section 5 as a deliberate
  trade-off, not an oversight.
- **The insignia** is the late-1980s/early-1990s USAF Senior Airman pattern:
  three chevrons under an **outlined** (unfilled) star. Regenerate all assets
  with `python scripts/brand.py`; the React header renders it inline in
  `frontend/src/components/Icons.jsx` (`Insignia`) so it inherits theme colors,
  and that copy must be kept in step with `marketing/images/logo.svg`.

### Files that exist and should not be re-created

```
Makefile  ROADMAP.md  TODO.md  .gitignore  .gitleaks.toml
config.yaml.sample  pyproject.toml  LICENSE

backend/
  app/{__init__,config,database,models,schemas,security,deps,main,
       scheduler,netutil,migrations,migration_utils}.py
  app/api/{__init__,auth,users,sites,scans,items,preferences,system,access}.py
  app/scrapers/{__init__,base,browser,royal_tiger,empire_arms}.py
  app/services/{__init__,bootstrap,classify,scan_service,image_store,
                mailer,digest,recaptcha}.py
  alembic/{env.py,script.py.mako,README,versions/0001_initial_schema.py,
           versions/0002_photo_thumbnails.py}
  alembic.ini  pytest.ini  .coveragerc  cli.py  run.py
  requirements.txt  requirements-dev.txt
  tests/{conftest,test_security,test_classify,test_api_auth,
         test_api_items,test_scan_service,test_digest}.py

frontend/
  package.json  vite.config.js  index.html
  .eslintrc.cjs  .prettierrc.json  .prettierignore  .nycrc.json
  public/favicon.svg
  src/{main,App}.jsx  src/{api,auth.jsx,format,hooks,styles.css,layout.css}
  src/components/{Icons,Shell,AuthImage,StatusChip,Modal,RequestAccess}.jsx
  src/pages/{Login,Browse,ItemDetail,Sites,SiteDetail,ScanDetail,
             Users,Settings}.jsx
  tests/screenshots.mjs

deploy/nginx/{milsurp.conf,milsurp-bootstrap.conf}
deploy/systemd/milsurp.service

scripts/{dbupdate.py,brand.py,coverage_badges.py,install-dev.sh,
         install-production.sh,setup-letsencrypt.sh,screenshots.sh,
         test-backend.sh,lint.sh,security.sh}

marketing/images/{logo,favicon,insignia,coverage-backend,coverage-frontend}.svg
```

### Recently added

```
backend/app/logsafe.py                   log-injection sanitizer
backend/tests/test_logsafe.py            its tests
backend/requirements-security.txt        semgrep, pip-audit
scripts/tool-versions.env                pinned gitleaks, shared with CI
```

Everything listed under "Still to create" in earlier revisions of this file now
exists: `scripts/dev.sh`, `scripts/install-hooks.sh`, `scripts/test-frontend.sh`,
`.githooks/pre-commit`, `.githooks/pre-push`, `frontend/playwright.config.js`,
`frontend/tests/*.spec.js`, `.github/workflows/{ci,security}.yml`,
`.github/dependabot.yml` and `README.md`.
