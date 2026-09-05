<div align="center">

<img src="marketing/images/logo.svg" alt="Milsurp Monitor" width="88" height="88">

# Milsurp Monitor

**Track military surplus firearm listings and price history across every vendor
site, from one place.**

[![Backend coverage](marketing/images/coverage-backend.svg)](#testing)
[![Frontend coverage](marketing/images/coverage-frontend.svg)](#testing)
[![License: BSD 3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-1B4B8F.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-0A2240.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-0A2240.svg)](https://react.dev/)

</div>

---

Collector-grade surplus turns up on a dozen different dealer sites, each with
its own layout, its own idea of pagination, and no notification when something
new appears or a price drops. Milsurp Monitor crawls them all on a schedule,
keeps a full price history for every listing, and emails you a digest of what
changed — filtered to the sites you care about and capped so it stays readable.

## Contents

- [What it does](#what-it-does)
- [Screenshots](#screenshots)
- [How it works](#how-it-works)
- [Quick start (development)](#quick-start-development)
- [Production install](#production-install)
- [Configuration](#configuration)
- [Make targets](#make-targets)
- [Adding a vendor site](#adding-a-vendor-site)
- [Testing](#testing)
- [Security](#security)
- [Project layout](#project-layout)
- [Roadmap](#roadmap)

---

## What it does

### Crawling

- **Pluggable scrapers.** Each vendor is one class; scheduling, admin controls,
  price history, images and digests are all site-agnostic.
- **Handles hostile pagination.** The Royal Tiger scraper copes with infinite
  scroll, "Load More" buttons that are absent from the DOM until scrolled near,
  and classic `page/2/` URLs — sometimes three of them on the same site.
- **A background scheduler** runs each site on its own cadence. An admin can
  disable a site, change its frequency, start a scan immediately, or cancel one
  mid-flight.
- **Idempotent by design.** A re-scrape updates rows in place rather than
  duplicating them, keyed on a stable per-site identifier.

### Data

- **Price history in its own table.** Prices are not a column that gets
  overwritten — every change is an observation, so you can see a listing's whole
  price arc. A row is written only when the price actually moves, so the table
  stays proportional to real changes rather than to scan count.
- **Structured fields inferred from prose.** Caliber, country of origin,
  manufacturer, bore condition and rifle-vs-handgun are derived from listing
  text with rules built by watching real vendor listings.
- **De-listing is tracked**, not deleted: an item that disappears is marked
  inactive with a timestamp, and reappears with its original "first seen" date
  intact.

### Photos

- **Two resolutions, generated locally** during the scan: the original plus a
  640px thumbnail (typically a 10x size reduction). Grids request the thumbnail,
  the detail view requests the full image.
- **Full galleries**, not just the grid thumbnail — a firearm usually has
  several photos and they only exist on the product page.
- **Stored outside the web root**, mode 0700, served only through an
  authenticated endpoint.

### People

- **Two roles.** *Admin* can do everything including managing accounts; *normal*
  can browse listings and configure their own digest.
- **Argon2id password hashing** with a server-side pepper; a password change
  revokes every issued session token.
- **Per-user email digests**: choose the frequency, which sites, whether to
  include new listings and/or price reductions, and a **required per-site cap**
  so one big scan cannot produce a hundred-item email.

### Browsing

- Keyword search across titles **and** captured descriptions, with multi-term
  matching and quoted phrases.
- Faceted filters: site, category, caliber, country, manufacturer, type,
  availability, price range, "reduced only".
- Filter state lives in the URL, so a view can be bookmarked and shared.
- **Responsive**: a two-column grid and a slide-in drawer on a phone, a fixed
  sidebar and multi-column grid on a desktop.
- **All times stored UTC**, rendered in the viewer's own timezone.

## Screenshots

> Regenerate these at any time with `make screenshots`.

| | |
|---|---|
| ![Inventory](marketing/images/screenshot-inventory.png) | ![Item detail](marketing/images/screenshot-item-detail.png) |
| **Inventory** — faceted search across every site | **Item detail** — gallery, structured facts, price history |
| ![Sites](marketing/images/screenshot-sites.png) | ![Mobile](marketing/images/screenshot-mobile.png) |
| **Sites** — status, cadence, scan-now, drill-down | **Mobile** — the same app on a phone |

## How it works

```
          ┌──────────────┐   scheduler tick        ┌──────────────────┐
          │  Scheduler   │────────────────────────▶│  Scraper (per    │
          │  (thread)    │                         │  vendor site)    │
          └──────┬───────┘                         └────────┬─────────┘
                 │ digests due                              │ listings
                 ▼                                          ▼
          ┌──────────────┐                          ┌──────────────────┐
          │  Digest      │                          │  Scan service    │
          │  (SMTP)      │                          │  upsert · prices │
          └──────────────┘                          │  de-list · photos│
                                                    └────────┬─────────┘
                                                             ▼
   React SPA  ◀──── FastAPI (JWT) ◀────────────────  SQLite + image store
```

- **Backend** — FastAPI, SQLAlchemy 2.0, Alembic, uvicorn. One process: the
  scheduler runs on a background thread, scans on a small worker pool.
- **Frontend** — React 18 + Vite, no UI framework. Served by the Python app in
  production; Vite's dev server proxies to it in development.
- **Database** — SQLite in WAL mode. Right for one machine and a dozen sites;
  PostgreSQL is on the roadmap for when that stops being true.
- **Schema** — created and evolved **only** by Alembic, including on a brand new
  install, so a fresh database and an upgraded one are built by the same steps.

## Quick start (development)

**Requirements:** Ubuntu/Debian (or macOS), Python 3.11+, Node 20+, and Google
Chrome or Chromium if you want the browser-driven scrapers.

```bash
git clone https://github.com/bceverly/milsurp.git
cd milsurp

# Installs system packages (prompts for sudo), creates .venv, installs Python
# and npm dependencies, downloads the Playwright browser, generates config.yaml
# with fresh secrets, and installs the git hooks.
make install-dev
```

Then set an admin password and start it:

```bash
$EDITOR config.yaml        # set admin.password (12+ characters)
make init                  # create the database, seed sites and the admin account
make start                 # builds the UI and prints the URL
```

`make start` prints something like:

```
  ▲ Milsurp Monitor is running
    http://localhost:8730
    PID 12345 · logs: server.log · stop: make stop
```

The port is chosen dynamically — if 8730 is busy it takes the next free one in
the configured range, so a busy port never blocks a start.

```bash
make start         # also stops a running instance first, so it is a restart
make stop          # stop it
make status        # is it running, and where
make logs          # follow the log
```

`make start` rebuilds the frontend when its sources have changed, and only
prints the URL once `/api/health` actually answers — so a successful line means
the app is genuinely ready, not merely launched.

### Getting some data

**Scanning is off by default** so a fresh install does not start crawling vendor
sites the moment it boots. Run one by hand:

```bash
make scan site=empire-arms     # a fast, HTTP-only site — good first run
make scan                      # every enabled site
make sites                     # what is registered, and when it last ran
```

Turn the scheduler on in `config.yaml` (`scheduler.enabled: true`) when you are
ready for it to run on its own.

### Hot reload

```bash
make dev     # API with --reload plus the Vite dev server; open :5173
```

## Production install

Tested on **Ubuntu 26.04 LTS**. The installer creates a dedicated service
account, lays out `/etc/milsurp`, installs to `/opt/milsurp`, builds the
frontend, and registers an nginx site and a systemd unit.

```bash
git clone https://github.com/bceverly/milsurp.git
cd milsurp
sudo scripts/install-production.sh
```

Then:

```bash
# 1. Set admin.password, your SMTP details and public_url.
sudo -e /etc/milsurp/config.yaml

# 2. Seed the database.
sudo -u milsurp env MILSURP_ENV=production \
  /opt/milsurp/.venv/bin/python /opt/milsurp/backend/cli.py init

# 3. Point DNS at the machine, then get a certificate.
sudo scripts/setup-letsencrypt.sh

# 4. Start it.
sudo systemctl start milsurp
sudo systemctl status milsurp
sudo journalctl -u milsurp -f
```

**What you end up with**

| | |
|---|---|
| App | `127.0.0.1:8730`, loopback only |
| nginx | TLS on **443**, port **80** → 301 → 443 |
| TLS | Let's Encrypt, auto-renewing via `certbot.timer` |
| Database | `/etc/milsurp/milsurp.db` (mode 0640) |
| Photos | `/etc/milsurp/images` (mode 0700) |
| Service | `milsurp`, hardened systemd unit, restarts on failure |
| Logs | `journalctl -u milsurp` |

The nginx config ships with TLS 1.2/1.3 only, HSTS, a strict CSP, OCSP stapling
and rate limits on the sign-in and access-request endpoints. Upgrades re-run
`scripts/install-production.sh`, which is safe to run repeatedly; migrations are
applied by `scripts/dbupdate.py`.

### Database migrations

One script, used identically in both environments:

```bash
make migrate                  # development
scripts/dbupdate.py           # production (run it directly)
scripts/dbupdate.py --status  # current vs head revision
scripts/dbupdate.py --check   # exit 1 if anything is outstanding (for CI)
```

It resolves the database path exactly as the app does, creates the file and its
parent directory with correct permissions if needed, and applies the Alembic
chain. Every migration is written to be idempotent, so re-running is a no-op.

## Configuration

Searched for in this order; first hit wins:

1. `$MILSURP_CONFIG` — explicit override
2. `<repo root>/config.yaml` — development
3. `/etc/milsurp/config.yaml` — production

`config.yaml.sample` is fully commented; copy it with `make config`. The file
holds SMTP credentials and signing secrets, so keep it mode 600. The repo-root
copy is gitignored.

Everything is optional — anything omitted falls back to a documented default.

| Section | What it controls |
|---|---|
| `database.path` | Dev: `<repo>/milsurp.db`. Production: `/etc/milsurp/milsurp.db` |
| `images.path` | Photo store. Dev: `<repo>/data/images`. Production: `/etc/milsurp/images` |
| `security` | `password_pepper`, `jwt_secret`, token lifetime, Argon2 cost, password policy |
| `admin` | The initial account, created once on first start |
| `email` | SMTP host/port/security, credentials, `support_email` |
| `server.dev` | Bind address, preferred port, port range |
| `server.production` | App port, public TLS port, HTTP redirect port, `public_url` |
| `scheduler` | On/off, tick interval, concurrency, scan timeout |
| `scraping` | User agent, timeouts, politeness delay, page ceilings, Selenium |
| `recaptcha` | Site/secret keys for the public access-request form |

Generate real secrets with:

```bash
make secrets
```

### Password policy

The rules are configuration, not code. Each character-class requirement applies
only when switched on, and the complexity rules in force are **derived** from
whichever are true — including the guidance shown in the UI, which the server
sends, so the message and the enforcement can never disagree.

```yaml
security:
  min_password_length: 12    # length is the main lever
  require_uppercase: true
  require_lowercase: true
  require_numeric: true
  require_special: true      # anything that is not a letter or a digit
```

Read fresh at every start, so changing a rule and restarting takes effect
without a rebuild. Existing passwords are not re-checked; the policy applies
when a password is set or changed.

### Email

Digests are sent over SMTP from the account in the config file. **For Gmail this
must be an App Password**, not the account password — Google blocks plain
password SMTP on accounts with 2-Step Verification, and an app password can be
revoked on its own.

```yaml
email:
  enabled: true
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_security: starttls
  username: you@gmail.com
  password: "abcd efgh ijkl mnop"   # the 16-character app password
  from_address: you@gmail.com
  from_name: "Milsurp Monitor"
  support_email: you@gmail.com      # where access requests are delivered
```

Verify it without sending anything from **Admin → test connection**, or send
yourself a digest immediately from **Email digest → Send one now**.

## Make targets

Run `make` on its own for the full list with descriptions.

| | |
|---|---|
| **Setup** | `install-dev` · `install` · `secrets` · `config` |
| **Database** | `migrate` · `migrate-status` · `migration` · `init` · `passwd` |
| **Run** | `start` · `stop` · `restart` · `status` · `logs` · `dev` · `build-frontend` |
| **Scraping** | `scan` · `sites` · `digest` |
| **Quality** | `lint` · `lint-fix` · `test` · `test-backend` · `test-frontend` · `coverage` · `security` · `install-hooks` |
| **Docs** | `screenshots` |
| **Release** | `release` |
| **Housekeeping** | `clean` · `clean-data` |

## Adding a vendor site

Two steps. Everything else — scheduling, admin controls, price history, images,
de-listing, digests — is site-agnostic and needs no change.

**1.** Write the scraper in `backend/app/scrapers/`:

```python
from .base import ScrapeContext, ScrapedItem, SiteScraper

class MyVendorScraper(SiteScraper):
    slug = "my-vendor"                 # stable; binds the DB row to this class
    name = "My Vendor"
    base_url = "https://myvendor.example/"
    description = "What this site sells."
    requires_browser = False           # True if the catalog needs JavaScript
    default_interval_minutes = 720

    def scrape(self, ctx: ScrapeContext) -> list[ScrapedItem]:
        html = ctx.get_text(f"{self.base_url}surplus")
        return [
            ScrapedItem(
                external_key=...,      # stable per-site id; drives upserts
                url=...,
                title=...,
                price=...,
                image_urls=[...],
            )
        ]
```

**2.** Register it in `backend/app/scrapers/__init__.py`:

```python
SCRAPER_CLASSES = (RoyalTigerScraper, EmpireArmsScraper, MyVendorScraper)
```

Restart; the site row is seeded automatically. Then `make scan site=my-vendor`.

A few things worth knowing:

- `scrape()` must return the **complete** current inventory — anything omitted
  is treated as de-listed.
- Raise `ScrapeError` to fail the run; call `ctx.warn()` for problems that
  should downgrade it to PARTIAL instead.
- `ctx.needs_detail(key)` tells you whether a listing has already been fully
  fetched, so detail-page requests are paid for once rather than every scan.
- For a JavaScript catalog, set `requires_browser = True` and use the helpers in
  `scrapers/browser.py` (`scroll_until_stable`, `load_more_until_stable`).
- `services/classify.enrich()` derives caliber, country, manufacturer, condition
  and the rifle/pistol split from the title and description.

Sixteen sites are queued in [ROADMAP.md](ROADMAP.md).

## Testing

```bash
make test            # both suites, both coverage gates
make test-backend    # pytest
make test-frontend   # Playwright
```

| Suite | Tool | Tests | Coverage | Gate |
|---|---|---|---|---|
| Backend | pytest | 313 | 69.7% | 65% |
| Frontend | Playwright | 69 | 81.6% lines | 65% |

- **Warnings are errors.** A warning is a library telling you something is
  wrong; letting them scroll past defeats the point.
- The backend suite builds a throwaway database **through the real migration
  chain**, so it exercises the production schema rather than an approximation.
- The frontend suite drives the real application — instrumented build, real API,
  a disposable database seeded with sample listings — and collects coverage from
  the running app via `vite-plugin-istanbul` and nyc.
- Both desktop and mobile viewports are tested; the responsive layout is a
  first-class target, not a spot check.
- `make coverage` regenerates the README badges: red below 65%, amber below 80%,
  green above.

## Security

The application is built against the [OWASP Top 10](https://owasp.org/Top10/).

| Risk | How it is addressed |
|---|---|
| **A01 Broken Access Control** | Every route is authorization-checked server-side; the UI only hides controls. Photo requests verify the photo belongs to the item. The image store resolves paths against its root and rejects traversal. The last-admin guard cannot be used to lock everyone out. |
| **A02 Cryptographic Failures** | Argon2id (OWASP parameters) with a per-password random salt plus a server-side pepper kept out of the database. JWTs carry a `token_version` so a password change revokes every issued token. TLS 1.2/1.3 only, HSTS, OCSP stapling. |
| **A03 Injection** | All database access goes through SQLAlchemy parameter binding. LIKE metacharacters in search terms are escaped. Every value in an outbound email is HTML-escaped. |
| **A04 Insecure Design** | Per-site scan locking; per-user digest caps; login throttling with lockout; exactly one unauthenticated write path, and it is captcha-gated, rate-limited and writes nothing to the database. |
| **A05 Security Misconfiguration** | Security headers from both the app and nginx, including a strict CSP. API docs disabled in production. Hardened systemd unit (`ProtectSystem=strict`, `NoNewPrivileges`, syscall filter). Config 0600, photo store 0700, database 0640. Startup warns about short or placeholder secrets. |
| **A06 Vulnerable Components** | Dependabot on pip, npm and Actions. `pip-audit`, `npm audit` and Snyk in CI and in `make security`. |
| **A07 Authentication Failures** | Per-(username, IP) throttling with lockout; uniform failure messages and timing equalization so usernames cannot be enumerated; 12-character minimum with a common-password check; password change ends all sessions. |
| **A08 Integrity Failures** | Pinned dependency floors with lockfiles; CodeQL, semgrep and bandit in CI; git hooks that block a commit on any lint finding. |
| **A09 Logging Failures** | Failed sign-ins, access requests, scan outcomes and every digest attempt are logged; scan history and email delivery history are queryable in the UI. |
| **A10 SSRF** | Image URLs come from third-party markup, so every download validates the URL first: http/https only, and DNS resolution must not land on a private, loopback, link-local or reserved address. Cloud metadata endpoints are unreachable. |

Run the same scanners CI runs, locally:

```bash
make security     # bandit · semgrep · Snyk · pip-audit · npm audit · gitleaks
```

CI additionally runs CodeQL and TruffleHog, and re-runs everything weekly so a
newly-disclosed CVE in an unchanged dependency is still caught.

**Reporting a vulnerability** — please open a private security advisory on the
repository rather than a public issue.

## Project layout

```
backend/
  app/
    api/            HTTP routers (auth, users, sites, scans, items, …)
    scrapers/       registry, base class, browser helper, one file per vendor
    services/       scan engine, image store, classification, digests, mail
    models.py       ORM — every datetime is UTC
    config.py       YAML loading and defaults
    security.py     Argon2id hashing and JWTs
  alembic/          migrations (idempotent)
  tests/            pytest suite
  cli.py            administration CLI
  run.py            server entry point
frontend/
  src/              React app: pages, components, API client
  tests/            Playwright suite
deploy/
  nginx/            production and bootstrap site configs
  systemd/          hardened service unit
scripts/            install, migrate, lint, test, security, screenshots, brand
marketing/images/   logo, favicon, coverage badges, screenshots
```

### CLI

```bash
backend/cli.py init             # schema + seed sites and admin
backend/cli.py secrets          # generate config secrets
backend/cli.py sites            # list sites and schedules
backend/cli.py scan --site X    # scan one site
backend/cli.py users            # list accounts
backend/cli.py adduser NAME EMAIL [--admin]
backend/cli.py passwd NAME
backend/cli.py digest [--user NAME]
backend/cli.py prune-images     # delete image files nothing references
```

## Roadmap

[ROADMAP.md](ROADMAP.md) tracks planned work, including the sixteen vendor sites
queued for support, Debian packages and a Launchpad PPA driven by `v1.2.3.4` git
tags, and an Electron desktop app published to the Snap Store.

[TODO.md](TODO.md) is the working checklist for the current build.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
