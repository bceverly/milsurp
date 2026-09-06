# TODO — Milsurp Monitor build

Working checklist of everything requested, with what is done and what is left.
**This file is the resume point.** If the session is interrupted, read this
first, then the "Context for whoever picks this up" section at the bottom.

Last updated: 2026-09-05 — lint clean, 313 backend + 69 e2e green, CI/README done

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
      **constant-width striped wings** whose centre lines pass through the hub
      centre (so the three stripes are centred on the hub and the band is
      slightly narrower than its diameter), wing tips cut **vertically,
      parallel to the frame** — which makes the three stripes different
      lengths — and a **star at the hub centre, blue on blue with a metallic
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
      written and installed. Verified: the pre-commit hook exits 1 and prints
      COMMIT BLOCKED when lint reports anything. Existing non-ours hooks are
      backed up rather than overwritten. Installs by file copy — no git command.
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
- [x] Pre-commit hook that **blocks** on any lint finding, including black
      reporting it would reformat. Installed by `make install-hooks`; verified
      blocking.
- [x] **Hooks are lint-only.** Per the user: `pre-push` runs `make lint` and
      *not* `make test`. The suites take minutes, would run again for every tag
      push, and CI runs them on every push anyway. Both hooks now complete in
      ~2 seconds.
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
`make test` 323 backend tests at 70.1% and 69 Playwright tests at 79.1%, and
`make security` clean with every scanner actually present.


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
   verified locally is whether GitHub's code-scanning UI honours the in-source
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
backend/app/logsafe.py                   log-injection sanitiser
backend/tests/test_logsafe.py            its tests
backend/requirements-security.txt        semgrep, pip-audit
scripts/tool-versions.env                pinned gitleaks, shared with CI
```

Everything listed under "Still to create" in earlier revisions of this file now
exists: `scripts/dev.sh`, `scripts/install-hooks.sh`, `scripts/test-frontend.sh`,
`.githooks/pre-commit`, `.githooks/pre-push`, `frontend/playwright.config.js`,
`frontend/tests/*.spec.js`, `.github/workflows/{ci,security}.yml`,
`.github/dependabot.yml` and `README.md`.
