<div align="center">

<img src="marketing/images/logo.svg" alt="Milsurp Monitor" width="88" height="88">

# Milsurp Monitor

**Track military surplus firearm listings and price history across every vendor
site, from one place.**

[![Backend coverage](marketing/images/coverage-backend.svg)](#testing)
[![Frontend coverage](marketing/images/coverage-frontend.svg)](#testing)
[![License: BSD 3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-1B4B8F.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-0A2240.svg)](https://www.python.org/)
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
- **Reads vendors that publish no catalog at all.** Hunter's Lodge advertises
  in a magazine and posts a scan of the page; every product it sells that month
  is inside one picture. That site is read by OCR — the page is cut into panels
  along its own printed rules, each panel is read separately, and every listing
  carries a crop of the flyer it came from. It checks whether the flyer has
  changed before doing any of that, so an unchanged month costs one request.
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
  PostgreSQL is on the roadmap for when that stops being true. WAL lets readers
  work while a scan writes, but SQLite still has only one writer, so a scan
  commits at least every couple of seconds and never holds the write lock across
  a network wait. If a request loses the race anyway it is answered **503 with a
  `Retry-After`**, not 500: nothing is broken and it will work a moment later.
- **Schema** — created and evolved **only** by Alembic, including on a brand new
  install, so a fresh database and an upgraded one are built by the same steps.

## Quick start (development)

**Requirements:** Ubuntu/Debian (or macOS), Python 3.12+, Node 20+, Tesseract
(for the one vendor whose catalog is a scanned image; the rest work without
it), and Google
Chrome or Chromium if you want the browser-driven scrapers.

```bash
git clone https://github.com/bceverly/milsurp.git
cd milsurp

# Installs system packages (prompts for sudo), creates .venv, installs Python
# and npm dependencies, installs the security scanners (semgrep, pip-audit,
# gitleaks, snyk), downloads the Playwright browser, generates config.yaml with
# fresh secrets, and installs the git hooks.
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

It writes them straight into `config.yaml` and sets the file to mode 600. It
does not print them: a credential echoed to a terminal is a credential in a
scrollback buffer, a shell log, and any screenshot of either. It refuses to
overwrite secrets that are already set, because rotating them is destructive
and silently so — changing `password_pepper` stops every existing password
verifying, and changing `jwt_secret` signs everyone out. `make secrets
FORCE=1` overrides that, and says what it has just cost you.

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

### Backups

In production the scheduler snapshots the database once a day and keeps the ten
most recent, in `backups/` beside the database (`/var/lib/milsurp/backups` by
default). Nothing is written in development, where the database is a scratch
copy. `backend/cli.py backup` takes one on demand — worth doing before anything
that rewrites listings in bulk.

```yaml
backups:
  enabled: true          # production only; dev never writes one
  directory: backups     # relative to the state directory
  keep: 10
  interval_hours: 24
```

Snapshots are taken through SQLite's online backup API rather than by copying
the file: a copy taken while the application is writing can catch a transaction
halfway through, and under write-ahead logging the file on disk is not the whole
database. Each one is a complete `.db` that opens on its own, so restoring is
stopping the service and moving the file into place.

### Makers

The names the scanner looks for when it works out who made a listing live in a
table, editable from **Makers** in the admin navigation. Rules are tried in
order and the first match wins, so a name that contains another — "Mosin-Nagant"
and "Nagant" — has to come first. Alternative spellings are matched as literal
text on whole words, never as patterns. Saving re-files every listing the change
reaches and tells you how many moved.

## Make targets

Run `make` on its own for the full list with descriptions.

| | |
|---|---|
| **Setup** | `install-dev` · `install` · `secrets` · `config` |
| **Database** | `migrate` · `migrate-status` · `migration` · `init` · `passwd` |
| **Run** | `start` · `stop` · `restart` · `status` · `logs` · `dev` · `build-frontend` |
| **Scraping** | `scan` · `sites` · `digest` · `reclassify` · `photos` |
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

### If the vendor runs Shopify

The cheapest case, and worth checking for first: Shopify publishes every
collection as JSON at `/collections/<handle>/products.json`, carrying the
product id, title, price, availability, SKU, full gallery and description. A
subclass is a slug, a name and a list of collections — there is no markup to
parse and **no per-listing detail fetch**, which is where every other scraper
spends its time.

```python
from .shopify import ShopifyScraper

class MyVendorScraper(ShopifyScraper):
    slug = "my-vendor"
    name = "My Vendor"
    base_url = "https://myvendor.com/"
    sources = (
        {"category": "Curio & Relic", "url": "https://myvendor.com/collections/c-r"},
    )
```

Two things to check. Pagination is `?limit=250&page=N`, so a shop that
disallows query strings in robots.txt cannot be read this way — the walk asks
first and stops with a warning rather than failing. And **scope it to
collections**: a general retailer's top-level feed is their whole shop,
ammunition and modern rifles included.

Cookies identify the platform: `_shopify_y` or `_shopify_essential`.

### If the vendor runs Magento

`MagentoScraper` covers `li.product-item` grids and `?p=N` pagination — but
Magento is themed harder than the other platforms, and the two shops using it
here share almost no CSS class, so treat the selectors as defaults to override:

```python
class MyVendorScraper(MagentoScraper):
    slug = "my-vendor"
    name = "My Vendor"
    base_url = "https://myvendor.com/"
    card_selector = ".products-grid .item"      # theirs, not the default
    sources = ({"category": "Surplus", "url": "https://myvendor.com/surplus/"},)
```

**Read the product page's structured data before its markup.** Magento emits
schema.org `Product` JSON-LD, and where a shop has left it on it carries the
name, SKU, description, price, availability and original-resolution images —
everything the markup has, from a shape a theme cannot rearrange. The base class
prefers it and falls back to selectors, which is the opposite of the other three
and is the right way round wherever a shop publishes it.

**When a shop bars its own pagination, look at its facets.** Magento's layered
navigation is a set of facet groups — caliber, manufacturer, action — and each
group partitions the category. Where the values are rendered as *paths* rather
than query strings, they are reachable even when `?p=2` is not, so
`follow_facets = True` reads a section one facet at a time.

The group is chosen by measuring, not by name: it qualifies only when every one
of its values holds no more listings than a single page shows — otherwise
walking it hits the same wall — and among those, fewest values wins, because
each value costs a request. On the shop this was written for that picks
Caliber/Gauge (19 values, largest 19, covering all 122) over Manufacturer (38
values, same coverage), and rejects Action (largest 60) and Price (largest 48).
It is paid for only when there is a next page being refused.

Three things to check, each of which cost something here:

- **Take the category URLs from the site's own navigation.** Guessing produced
  two 404s on a shop whose real sections were one click away.
- **Not every id on a card is the product's.** One shop's only `data-product-id`
  sits on a financing widget shown for in-stock products and not for sold-out
  ones — keying on it would make a rifle selling out look like a de-listing plus
  a new arrival. Only `product-item-info_<n>` is Magento's own.
- **Cents may live in their own element.** `$1599<span
  class="decimal">99</span>` reads as "$1599 99" and parses to $1599.00, which
  then disagrees with the product page forever. Remove that element from the
  tree, not its text from the string — `"$1599 99"` minus the first `"99"` is
  `"$15 9"`.

Cookies do not identify Magento; look for `X-Magento-Vary`, `mage.` in the
markup, or a `/media/catalog/product/` image path.

**A shop can be on a supported platform and still not be worth reading.**
Century Arms is Magento, their Surplus Corner parses cleanly, and the scraper
was written, run against the live site and then removed. Their prices are
dealer-only: seventeen of the first twenty listings say "DEALER LOGIN REQUIRED
TO PURCHASE" where a price would be, and the element that would hold one is
rendered `display: none`. A price watcher gets nothing from that. The catalog
is also mostly modern commercial stock — Antonio Zoli over-unders, an Armalite
M15, a row of Arminius .38 revolvers — so the three genuinely old listings came
at the cost of importing a gun shop's shelf.

That is the third time this has come up (Arms Unlimited, Edelweiss Arms,
Century Arms), so it is worth stating as a rule: **before writing the subclass,
read twenty cards and count how many carry a price and how many are surplus.**
"It is on a platform we already support" is a statement about cost, not value.

### If the vendor runs BigCommerce

`BigCommerceScraper` is the same idea for Stencil themes: `article.card` per
product, `.card-title`, `.price--withoutTax`, a `rel="next"` link. Two things
differ from WooCommerce and are worth knowing:

- **The key.** WordPress puts a post id in every card; Stencil themes are
  inconsistent, so `data-entity-id` is used where it exists and the product's
  URL path where it does not. Prefer the id: a rename changes the URL, and a
  path key reads that as one listing de-listed and another appearing.
- **Pagination is a query string** (`?page=2`), not a path. A shop may disallow
  those in robots.txt, so the walk asks before each page and stops that section
  rather than failing the scan.

### If the vendor runs WooCommerce

Five vendors are read this way, and they render their catalogs the same way. Use
`WooCommerceScraper` instead and the whole scraper is usually a slug, a name and
a list of category URLs:

```python
from .woocommerce import WooCommerceScraper

class MyVendorScraper(WooCommerceScraper):
    slug = "my-vendor"
    name = "My Vendor"
    base_url = "https://myvendor.example/"
    description = "What this site sells."
    sources = (
        {"category": "Military Rifles",
         "url": "https://myvendor.example/product-category/military-rifles/"},
    )
```

It handles the product cards, the post id as a stable key, sale prices,
lazy-loaded images, gallery de-duplication and pagination. Where a theme renames
something, put the site's selector *in front of* the stock ones rather than
replacing them, so the defaults still answer if the theme changes back:

```python
    detail_description_selectors = (
        "div.single-product-description",
        *WooCommerceScraper.detail_description_selectors,
    )
```

`category` is the vendor's own section name and outranks the classification
heuristics, so it should say what the section actually holds. Take the firearm
categories and any parts-*kit* category; leave the rest of a parts tree alone.

Four things worth checking on a new WooCommerce shop, because each has already
caught one out:

- **Is it actually WordPress?** Two of the sites queued as WooCommerce were
  BigCommerce; their `li.product` markup looks similar and parses to nothing.
  If the cards have no `post-NNNN` class, it is not WooCommerce.
- **Does the catalog arrive in the HTML?** J&G Sales returns `li.product`
  elements that are empty placeholders filled in by JavaScript, so it needs
  `requires_browser = True` rather than this base class.
- **Is that page products or categories?** MCT Defense's firearms page is
  thirty category tiles with no price element anywhere on it.
- **Did the photographs come with it?** Count them, on a card and on a product
  page, before calling a shop done. A scraper whose titles and prices are right
  looks finished, and a missing gallery is invisible until somebody opens the
  site months later and asks why there are no pictures.

That last one is worth its own paragraph, because "no `<img>` on the page" turns
out not to mean "rendered by JavaScript". CO Gun Sales landed 116 listings with
titles, prices and descriptions and not one photograph, and it is entirely
static — the pictures are simply not in `<img>` tags:

- **The card's picture is a CSS background.** A page builder puts it in a
  `style="background-image:url(…)"` on the link, not in an image element.
  `background_images()` in `storefront.py` reads those, and the card path falls
  back to it only when there is no `<img>` at all, so a theme that has both
  keeps preferring the real one.
- **The gallery is JSON in an attribute.** Their gallery plugin puts all nine
  photographs into `data-wcsvi` on the `woocommerce-product-gallery` div and
  builds the gallery in the browser. `WooCommerceScraper.gallery()` falls back
  to `json_gallery_attributes` when the selectors find nothing, and prefers each
  entry's `large_image` — the original upload — over its `src`, which is the
  same photograph behind an image CDN with the resize in a query string.

Both are fallbacks, reached only when the ordinary path finds nothing, so
neither can change what a shop that renders normal markup already produces.

### Makers and models

Both are tables, edited together from **Makers** in the admin navigation.

A maker has **other spellings** — the same firm written differently, "S&W" for
Smith & Wesson — and **models**, which is what that firm made. They are separate
because they are different facts, and because a dealer names the model far more
often than the maker: "RUSSIAN M44 CARBINES" and "WW2 RUSSIAN 91/30 RIFLES" are
both Mosin-Nagants and neither says Mosin, or Nagant, anywhere.

Order decides ties, so a name containing another — "Mosin-Nagant" and "Nagant" —
has to come first. A model **two** makers claim identifies neither and is
dropped from matching, because picking whichever rule came first would be an
accident of ordering rather than a decision; "M38" is a Carcano as often as it
is a Mosin. Both entries are kept and the dialog says which ones cancel out.

Everything is matched as literal text on whole words, never as a pattern.
Saving re-files every listing the change reaches and reports how many moved.

**What a listing is selling is the last noun, not the first.** A dealer names
the firearm an accessory fits, first and prominently: "U.S. M1 Garand Rifle
WWII 1907 Pattern Leather Sling" is a sling. Reading whichever was mentioned
first made forty-two of IMA-USA's slings, bayonets, scabbards, handguards and
dummy cartridges into rifles — and their own sections are called "M1 Garand &
U.S. Rifles", so the vendor's category agreed.

Several rules keep that honest, and each exists because the simple version of
it broke something. Every one of them was measured against the whole stored
catalog before it was kept, which is how each of the wrong turns below was
found — a change that reads well and fixes the case in front of you will
quietly cost you thirteen listings somewhere else.

- **A part the listing comes with, or without, is removed before anything reads
  the title.** "Schmidt Rubin K31 with Matching Bayonet, Scabbard & Frog" is a
  rifle, and so is "Marlin 444S w/ Ammo". The whole chain goes, not just the
  first item: stripping only the first left ", Holster & Box" behind, and a
  holster at the end of a title looks exactly like a holster for sale.
  A *count* introduces the parts it counts and nothing further off, so "Pistol
  2 Magazines & Service Holster" is a pistol while "Mark 1 Plastic Training
  Bayonet" is a bayonet; a length is not a count, or `16" BARRELS` would read
  as a gun that comes with sixteen of them. An introducer at the very start of
  a title attaches the part to nothing — IMA-USA open every listing with
  "Original", which read the head off "Original U.S. WWII Rear Sight for the
  M1903A1" and sold a sight as a rifle.
- **Only some accessory words may be read as the head noun**, and every
  accessory word in the title is tested, not just the first. "PSYOP Chieu Hoi
  Magazine Bag" leads with "magazine", which is a specification here; testing
  only that one missed the "bag" that is the product.
- **A part word is a specification when it is describing a gun already named.**
  This is what lets barrels, stocks, grips and sights be read at all. Four
  signals say so, and a part sold on its own has none of them: a measurement
  immediately before it ("Straight Pull Rifle 30.75in Barrel"), a profile or a
  finish ("Threaded Barrel", "Fixed Stock", "Octagonal Barrel"), a dash setting
  it off from a gun already named ("Kimber Micro 9 - Laser Grips"), or simple
  distance from the firearm noun. Singular, too: a gun has one barrel, so
  `8" Barrel` is a specification and `16" Chrome Lined Barrels` is a box of
  barrels. Grips and sights accept a *model* name as the thing being described,
  because they are hardly ever sold loose here; barrels and stocks are, in
  quantity, so those need the firearm noun itself.
- **An entry in a list of features is not the head noun.** "Bolt Action,
  Bayonet, Exc Cond, Ser # M40829" is a rifle that has one — and neither is the
  *last* entry in one, which has no comma after it to give it away: "JRA
  Gallant Rifle, 5.56 NATO, 18in BBL, ..., 30 Rd Mag, Rifle Case" is a rifle
  sold with a case. Three commas are required before a title counts as a spec
  list, because "Boyle, Gamble, & McFee Bayonet Adapter" is a maker's name.
  Some vendors write the same list with dashes — "Smith & Wesson Model 30-1 –
  .32 Long – Pachmayr Grips – 4 Inch Barrel – 1969 C&R" is an $850 revolver
  whose third entry happens to be its grips — so three *spaced* dashes count
  too. Spaced, because the hyphen in "30-1" is not a separator.
- **What follows the part stops being evidence at "for", a colon or a dash.**
  Each of those introduces the gun a part *belongs to*: "Rear Sight **for** the
  M1903A1 Springfield Rifle", "Handbook**:** U.S. .30 M1 Garand", "Allin
  Conversion Sling Made from Civil War Slings **-** M1868 Trapdoor Springfield".
- **Order does not decide.** It used to: whichever of the firearm and the
  accessory came first was taken to be the product. That reads "Over & Under
  Double **Barrel** .44 Caliber Swivel Breech Percussion **Rifle**" as a barrel
  and "Matched Pair of Flintlock **Holster** **Pistols**" as a holster, because
  those dealers put the part word early as a description. The head-noun test
  reaches the same answer on the cases order was protecting — "Leather sling
  **for** a Mauser rifle" stops being evidence at "for" — and the right one on
  these.

**The vendor's category outranks all but the confident half of that.** A
category names the *section*, not the item, so a phrase that can only be a part
("parts kit", "dummy cartridges", "non-firing") and an accessory sitting in the
head-noun position both beat it. Nothing weaker does. Promoting the whole veto
above the category turned forty firearms into accessories, and the category had
been quietly rescuing them all along.

**A gun that has been made safe is still that gun.** An inert M2HB display at
$9,995, a non-firing 1903 training rifle and a 47%-scale replica revolver were
all filed under parts, by the same words — inert, dummy, non-firing, prop —
that correctly catch a box of dummy cartridges and a bare movie prop. Those
words now veto only when the title does not *name* the thing as a gun, so
"Non-Firing Training **Rifle**" and "Inert Display Machine **Gun**" come
through and "Non-Firing **Prop Gun**" does not. The same conditional treatment
covers the words that describe a gun as readily as they name a product — book,
cap, medal, patch, tripod — with one extra requirement: the gun must be named
*before* the word. That is the whole difference between "Single Action Revolver
Grouping - As Featured In … Firearms **Book**" and "Reference **book**, Mauser
rifles", which name the same two things in the opposite order.

**A dealer who deals in collectors' guns names the model and stops.** "ANIB FN
SCAR 16S - Desert Camo", "Like-New DSA SA 58 FALO", "Walther Model 4 -
Copenhagen Police", "Winchester Model 1873, .44-40 - 1882 mfg". Not one of
those contains the word rifle or pistol, so there was nothing in the title for
the rules above to read and every one of them was filed under parts and
accessories at four figures. `RIFLE_PATTERNS` and `PISTOL_PATTERNS` carry the
designations for that reason, and they are *models*, never bare makers: Colt,
Winchester, Remington, Springfield, Beretta and CZ all build both, so a maker's
name on its own decides nothing. The same list is what tells a specification
from a product in the rule above, which is why adding a maker there has a cost
— `hammerli` matched "Target Rifle – **Hammerli** Barrel" and turned a rifle
into a barrel, and now only the model does.

A listing whose maker, caliber or country could not be worked out is filed under
**Unknown** in the filters — the column stays empty, and "Unknown" is only what
the filter calls it, so the fill-in-the-blanks rules keep working. It is there so
the ones the heuristics fail on are the easiest to find rather than invisible.

**Each Type carries the count it would show.** The numbers next to Rifles,
Handguns, Bayonets, Parts kits and Other are counted over every other filter
but deliberately *not* over the Type itself — with the Type applied, choosing
Rifles would report zero handguns and the numbers would only ever restate the
choice already made. "Anything" is the sum of the five rather than a sixth
count, because the five partition the set by construction and computing it
separately would let the two disagree on screen. They are also the fastest way
to see a classification change land: a shift of forty in one column after
`reclassify` is either the fix or the regression.

### The write-ahead log

SQLite runs in WAL mode here, so writes append to a `milsurp.db-wal` sidecar and
are folded back on a checkpoint. The automatic checkpoints are PASSIVE: they
copy the pages across but leave the file at its high-water mark to be reused —
the right trade while the application is running, and the wrong one for a 36MB
log sitting against a 17MB database because one large scan grew it once.

A large WAL is not corruption and nothing in it is at risk. `make checkpoint`
folds it in and empties the file, `make start` does it automatically while the
app is stopped (when it can do the most), and `scripts/checkpoint-wal.sh` is
written to be run from cron in production:

```
17 4 * * *  cd /opt/milsurp && scripts/checkpoint-wal.sh
```

One hazard is worth knowing: **while a WAL exists, copying `milsurp.db` on its
own is not a backup.** The copy silently lacks everything not yet folded in,
which is exactly how a copy of this database turned up missing its newest
tables. Take `-wal` and `-shm` with it, or use `make backup`.

### The armory

Everything above reads a listing and *guesses*. The catalog is the opposite: a
table of things somebody who knows the trade has stated, which the guesses
defer to. Three tabs at `/armory` in the admin pages — Manufacturers, Models and Calibers.
One page, because they are three views of one body of knowledge: the makers used
to be a page of their own where each firm carried a flat textbox of model names
that nothing else could see, and that split is what the join tables removed.

**Calibers, and every way the trade writes one.** ".32 ACP" and "7.65mm
Browning" are the same round; so are ".30-06" and "7.62x63mm", "7.62x54R" and
"7,62x54R", "7.5x55mm Swiss" and "GP11". Until they are one row a filter on
either shows half the listings, and a missing caliber cannot be filled in from
anything. The longest spelling is tried first, which is what stops "7.62x54R"
being read as a bare "7.62".

**Models, with their makers, their calibers and what kind of gun they are.**
Both of those are lists, and for different reasons.

A model has *several makers*: the M1 Carbine was built by Inland, Winchester,
Rock-Ola, IBM, Underwood, Quality Hardware, National Postal Meter, Standard
Products and Saginaw, and a listing may name any of them or none. That is a
join table rather than a column because the relationship runs both ways —
Winchester also made the Model 1873 and the Model 94. It is one row per model,
never one per maker, so the kind is stated once and there is nothing to keep in
sync.

A model also has *several calibers*, because one built across decades is often
chambered in more than one round. A Steyr M95 is 8x50mmR or 8x56mmR depending
on when it was rebarreled, and both are correct for a rifle sold today as "an
M95".

Both lists follow the same rule when the catalog is asked to fill in a blank:
**with exactly one it is a fact, with several it says nothing.** A title naming
none of the nine makers does not tell us which built it, and "Steyr M95" does
not say which cartridge this particular rifle takes. A guess dressed as a fact
is worse than a blank.

The kind is finer than the browse filter's rifle/handgun split, because the
ignition system is half of what a muzzleloader is: rifle, carbine, shotgun,
pistol and revolver, each also in flintlock and percussion. A **carbine is not
a short rifle** — a Trapdoor Carbine and a Trapdoor Rifle are different guns,
priced and collected separately. Variants within a model, the years and the
arsenals and the marks, are aliases rather than kinds.

**A manufacturer is a tab here, not a page of its own.** Opening one expands to
the models the armory says that firm built, with **+ Add model** offering a new
one with the maker already ticked. A model built by nine firms appears under all
nine, and it is the *same row* — opening it from any of them edits one record,
whose caliber and kind are stated once. That is the whole reason the makers were
folded in: a flat list of model names per firm could only say "this firm made
something called M44", so a designation two firms both made had to be dropped
from maker-matching entirely. Now the same fact is expressible directly, and a
model with exactly one maker names it while a model with nine names none.

**Approving is a checkbox in the header away.** Each tab selects everything it
is currently listing — which, on the default "Awaiting approval" view, is the
whole queue for that tab — and promotes it in one go. The request is sent in
batches, because a single call is bounded and select-all on a grown armory is
exactly what outruns it.

**Nothing decides anything until a person says so.** Every row is either
*awaiting approval* or *production*, and only production rows fill in a
caliber or settle what kind of gun a listing is. That is what makes it safe
for a scan to write down every designation it does not recognize: a proposal
is inert, it is recorded once rather than re-asked on every scan, and it waits
somewhere an admin can rule on it. Promoting is one-way and sending a row back
is a separate button, because "I have checked this" and "I no longer trust
this" are different statements.

**Merging is how the same thing said twice becomes one thing.** "Mosin" folds
into "Mosin-Nagant", "7.65mm Browning" into ".32 ACP". The source's spellings
move to the target, so nothing it used to recognize stops being recognized,
and every listing carrying the old name is restamped. The merged row stays,
marked and pointing at its target, so a wrong merge is an undo rather than an
archaeology exercise.

**What the catalog will not do is argue with a dealer.** It normalizes a
stated caliber — the two spellings are one answer — and fills in a blank one,
and stops there. Sixty years of surplus is full of rebarreled and rechambered
guns, and the vendor has the thing in their hand.

#### Getting it in and out

The knowledge is versioned in the repository, in `backend/app/seed/armory.yaml`,
rather than inside a migration. A migration runs exactly once per database and
can never be corrected afterwards, which is the wrong shape for a list meant to
grow for as long as the site does.

```
make armory-seed      # add what the shipped file has and this database does not
make armory-export    # write this database's armory OVER the shipped file
make armory-sync      # preview what the shipped file would change here
make armory-apply     # carry that out (prune=1 to also delete)
```

`seed` is additive and matches on the name: a row already present is left
exactly as it is, edits and approvals and all, so it is safe on every deploy
and is how a later release's additions reach a running installation. The
corollary is worth knowing before it surprises you — a row *deleted* from the
database comes back, as pending, on the next seed, because "missing" and
"deleted" look the same from there. Deleting is not how a row gets rejected;
leaving it pending or turning it off is, and both survive a re-seed.

`export` writes straight over the versioned file, because the point of keeping
it under version control is that the change arrives as a reviewable diff.
Nothing is at risk if the result is wrong: discard it.

The file lives in `backend/app/seed/`, and deliberately **not** in a directory
called `data/`. This repository's .gitignore carries an unanchored `data/`,
which matches a directory of that name at any depth — the seed file sat in
`backend/app/data/` for a while, was never committed, passed every test locally
and then failed twelve of them in CI with a `FileNotFoundError` that said
nothing about the cause. A test now asserts it is where the code expects it and
not under any ignored directory.

`export` writes what the database holds in a stable order, so a diff shows what
actually changed. Statuses go with it, so a row promoted on one instance
arrives as production on the next.

`sync` is the destructive counterpart, and therefore plans first: it prints
every add, every update with the fields that differ, and every deletion it
*would* make, and does none of it without `--apply`. Deletions need `--prune`
on top, because a catalog is curated in two places and a row missing from the
file is more often unexported than unwanted.

### robots.txt

Every scraper obeys it: `Disallow` rules are enforced before a request is made,
and a `Crawl-delay` becomes the floor on the politeness delay. This is real work
rather than a formality — Collectors Firearms asks for ten seconds between
requests, which makes a scan of their catalog half an hour of wall clock, and
they disallow query strings entirely, which rules out the WooCommerce Store API
their shop would otherwise serve.

A scraper can ask before it fetches, so it can choose another route rather than
fail:

```python
if ctx.allowed(url):
    ...
```

An unguarded fetch of a disallowed URL raises `Disallowed`. If robots.txt cannot
be read at all — a 5xx, a 403, a connection failure — the site is treated as off
limits rather than open, so a blip cannot quietly switch off a vendor's rules.
Set `scraping.obey_robots: false` only for a vendor who has given explicit
permission.

**Check a real vendor's rules with the real call**, not a scratch script:

```python
Robots.parse(text).allows(path, user_agent)   # path first
```

The argument order has bitten once. A probe written the other way round reports
"allowed" for everything, because it matches the user agent against the rules
and looks for a group named after the path — which is exactly the answer you
were hoping for, arriving for the wrong reason. `ctx.allowed(url)` is the
production path and gets it right; ad-hoc checks should go through that or copy
its call.

**A site can disallow its own pagination.** Classic Firearms carries
`Disallow: /*?p=`, which is how Magento pages a category — so their category
listings stop at page one however many products are behind them. Two things are
worth trying before writing a site off: a page-size parameter (`?limit=`,
`?product_list_limit=`) may be permitted where `?p=` is not, though it may also
be ignored by the server; and the sitemap declared in robots.txt is the
sanctioned route to a full catalog, since a sitemap exists precisely to tell a
crawler what to fetch. Both were checked on that site — the first is allowed and
ignored, the second works.

### Being told to slow down, and being refused

A 429 is an instruction about the rest of the scan, not about one request.
Collectors Firearms publishes `Crawl-delay: 10`, was crawled at exactly that
pace, and still returned 429 after sixteen minutes: their limiter counts over a
window that ten seconds a request eventually fills. So a 429 sets a *standing*
slower pace for that host — 30 seconds at least, doubling on each further
refusal, honoring `Retry-After` when it is given — and every later request in
the scan pays it, not just the retry.

That escalation is capped at five minutes a request, and the cap is where the
meaning changes. A refusal that arrives when there is no slower left to go
cannot be "you are asking too often", so it fails immediately instead of
sleeping through three more attempts at a pace already shown not to work.

**Being refused is remembered across processes.** A pace learned inside one
scan used to die when that process exited, so the scheduler, the CLI and a
`make photos` run each rediscovered the same rate limit separately — which from
the vendor's side is not one crawler being told to slow down, it is several
ignoring the same instruction.

`app/services/cooldown.py` keeps a `host_cooldowns` table, and every fetching
path consults it before making a request. Three things about it are deliberate:

- **It is published only once the in-process backoff is exhausted.** A single
  429 means "slow down" and is handled where it happens; being refused *at the
  slowest pace available* is a different statement, and that is the one worth
  sharing. Publishing on the first 429 would have a scan abandon a whole vendor
  over a hiccup.
- **It is per host, not per site.** A rate limiter counts requests to a
  hostname, and a vendor's catalog pages and their uploads directory are
  usually the same one.
- **It fails open.** A cooldown that cannot be read means "carry on", never
  "fail the fetch" — an application whose HTTP layer stops working because a
  table is missing is a worse failure than asking a vendor too often.

A photo skipped because its host is resting does **not** count as a failed
attempt, or a cooldown would burn a photograph's whole retry budget without a
single request being made.

**A pause ends by itself.** The wait doubles with each refusal up to an hour,
and once it is up every fetcher resumes with no intervention — that is the
"cooling off" the whole thing is for. The Sites page shows which hosts are
resting and why, and an admin can lift one early with **Fetch anyway** once the
cause is known and fixed; `cli.py resting` and `cli.py resting --clear` do the
same from a terminal. Lifting it is deliberately a separate button rather than
a confirmation on Scan now: the pause exists because the vendor's server
refused us, so going back before they asked is a decision about them.

**When a photograph will not arrive.** The photo queue is rows with no file
yet, so a URL that can never work looks exactly like one not reached — and used
to be retried on every scan for the life of the listing, silently. Each row now
counts its `attempts` and keeps the `last_error`; the queue is read
fewest-failures-first so a dead URL drifts to the back instead of consuming the
per-scan budget ahead of photographs that would work; and after three failures
it is left alone.

**Only a failure that will still be true tomorrow counts.** A 404 or an
unsupported content type is a property of the URL and is worth giving up on; a
429, a 503 or a timeout is a property of the moment, and letting those
accumulate would strand every photograph a busy afternoon touched — which is
what the host cooldown exists to prevent, not to cause. Transient failures are
recorded and retried; bounding them is the cooldown's job. `make photos-retry` clears the counts once the cause is fixed,
which is the right thing to do by hand and the wrong thing to do on a schedule.

**When a shop refuses a page.** A page that cannot be read costs what was on
that page, and nothing more. Both storefront base classes apply that twice:

- A failed **product page** costs that listing its description and gallery. The
  card already carried the title, the price and a thumbnail, which is what price
  watching actually needs. After three refusals in a row the run stops asking
  for product pages at all, rather than walking the whole catalog one pointless
  request at a time.
- A failed **catalog page** stops that section there. Two pages read and the
  third refused is two pages of listings worth keeping. The first page is the
  exception: a section that could not be opened at all yielded nothing, and
  nothing is not a partial result.

All of it goes through `ctx.warn()`, so the run reports PARTIAL and says why.

Checkpoint Charlie's is what paid for these rules, and is worth reading as a
warning about diagnosing from a single probe. A `curl` comparison said the
answer plainly — `/product-tag/cr/` returned 200 and `/product/…` returned 429,
at any pace and with or without browser headers — so the first fix addressed
product pages alone. The full run then showed the rest of it: after an hour of
refusals they stop answering *anything*, and the scan died on page 3 of the tag
having walked 24 listings and saved 5, reporting nothing found. Both rules
together turn that same hour into a PARTIAL run with the listings it managed to
read. It is still a bad site to scan, and it may yet need the browser path.

Twelve vendors are read today; fifteen more are queued in
[ROADMAP.md](ROADMAP.md), grouped by the platform they run on because one base
class unlocks a whole group.

## Testing

```bash
make test            # both suites, both coverage gates
make test-backend    # pytest
make test-frontend   # Playwright
```

| Suite | Tool | Tests | Coverage | Gate |
|---|---|---|---|---|
| Backend | pytest | 861 | 79.6% | 65% |
| Frontend | Playwright | 69 | 79.1% lines | 65% |

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

### How a scan survives being interrupted

A Royal Tiger scan is about sixteen minutes of browser work. The scan service
consumes a scraper **lazily** and commits in batches, so a restart part way
through keeps everything already reconciled instead of discarding the run.

Three facts make the next scan resume rather than repeat:

| Fact | Where it is set | Effect |
|---|---|---|
| `Item.detail_fetched_at` | only when a scraper hands over a *complete* record | a listing that never got its detail page is fetched next time; one that did is skipped |
| `ItemPhoto.filename IS NULL` | the photo download query | a photo is downloaded exactly once, however many scans see it; `scraping.max_photo_downloads_per_scan` (default 400) caps each run and the rest carries over |

A scan caps its own image downloads so a first pass over a large catalog cannot
run for hours. The **scheduler works through what is left between scans**, one
batch at a time on its own single thread (`scheduler.photo_tick_seconds`,
default 180) — never on a scan worker, so draining a backlog cannot delay a due
scan. Without it a thousand-photo backlog would drain one batch per scan, which
on a daily cadence is days of listings with no pictures. `make photos` does the
same thing on demand.
| `ScrapedItem.images_are_complete` | by the scraper | a catalog-grid preview may seed photos but may never prune a gallery it cannot see |

De-listing only happens when the scraper's iterable is exhausted normally, so a
partial scan can never mark the listings it did not reach as gone. An unchanged
gallery — same URLs in the same order — is skipped entirely, so re-scanning a
static catalog costs no image traffic. `make stop` warns before interrupting a
scan in flight; `FORCE=1` skips the prompt.
- The backend suite runs on **every supported Python** in CI — 3.12, 3.13 and
  3.14 — as three separate jobs. `requires-python` says 3.12 because 3.12 is
  the oldest version anything actually proves; a floor nobody tests is not a
  floor. Production (Ubuntu 26.04) and local development both run 3.14, which
  is what the single-version jobs use.

### Git hooks

`make install-dev` installs the hook, or run `make install-hooks` on its own.

| Hook | Runs | Blocks on |
|---|---|---|
| `pre-push` | `make lint` | any finding, including black reporting it would reformat a file |

There is deliberately no `pre-commit` hook. A work-in-progress commit is nobody
else's problem; a push is. Putting the single gate at the boundary where the
code stops being yours alone means you can commit freely mid-thought and still
cannot ship something unformatted.

It does not run the test suites either. They take minutes, they would run again
for every tag push, and CI runs them on every push anyway — a hook slow enough
to be routinely bypassed protects nothing. It takes about two seconds, and
prints the full lint output when it blocks so you do not have to re-run
anything to find out why. Bypass in an emergency with `git push --no-verify`;
CI will still catch it.

### Continuous integration

Two workflows, one job per concern, so a red tick names the thing that broke.

| Workflow | Job | What it does |
|---|---|---|
| `ci.yml` | `lint` | `make lint` — black, ruff, mypy, bandit, prettier, eslint, shellcheck |
| | `test` | three jobs, one per supported Python (3.12, 3.13, 3.14): `make test-backend`, then `make test-frontend`; the frontend step runs even when the backend step fails, so one push reports both, and `fail-fast` is off so one bad interpreter does not hide the others |
| | `migrations` | applies the Alembic chain to an empty database and checks the models match |
| | `build` | production bundle, and asserts no coverage instrumentation shipped in it |
| `security.yml` | `security` | installs every scanner, then runs `make security` — the same script you run locally |
| | `codeql` | Python and JavaScript, `security-extended`; reports into the Security tab |

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
| **A08 Integrity Failures** | Pinned dependency floors with lockfiles; CodeQL, semgrep and bandit in CI; a pre-push hook that blocks on any lint finding. |
| **A09 Logging Failures** | Failed sign-ins, access requests, scan outcomes and every digest attempt are logged; scan history and email delivery history are queryable in the UI. Every attacker-supplied value is passed through `app/logsafe.scrub` first, so a newline in a username cannot forge a log record. |
| **A10 SSRF** | Image URLs come from third-party markup, so every download validates the URL first: http/https only, and DNS resolution must not land on a private, loopback, link-local or reserved address. Cloud metadata endpoints are unreachable. |

Run the same scanners CI runs, locally:

```bash
make security     # bandit · semgrep · Snyk · pip-audit · npm audit · gitleaks
```

`make install-dev` installs all of them, because a scanner that is missing is
reported as *skipped* rather than failing — so without them a local scan passes
by checking almost nothing. semgrep and pip-audit come from
`backend/requirements-security.txt`; gitleaks is pinned in
`scripts/tool-versions.env`, which the CI workflow sources too, so both run the
same binary. gitleaks is also accepted as a container image
(`docker pull ghcr.io/gitleaks/gitleaks:latest`) if you would rather not put a
binary in `/usr/local/bin`.

Snyk needs an account: run `snyk auth` once, or export `SNYK_TOKEN`. Until then
it is skipped and `pip-audit` / `npm audit` carry the dependency check.

CI additionally runs CodeQL and TruffleHog, and re-runs everything weekly so a
newly-disclosed CVE in an unchanged dependency is still caught.

Two of semgrep's findings are suppressed in-source with the reasoning next to
the code: two startup warnings are matched by its credential-in-log rule purely
for containing the words "secrets" and "admin.password" in their *message
text*, while the only values they interpolate are a setting's name and a file
path.

Nothing is suppressed for CodeQL. In-source `# codeql[...]` comments turned out
not to be honoured by GitHub code scanning, which was the right outcome: each
alert was a real weakness once looked at properly rather than argued with.
`make secrets` no longer prints secrets at all. Failed sign-ins put the
submitted username through an **allowlist** rather than an escape, and read the
client address from the connection instead of slicing it back out of the
throttle key, which had been carrying the username along with it. And the
startup secret check no longer keeps a setting's name in the same tuple as its
value — a taint tracker follows the container, not the slot, so logging the
name read as logging the secret.

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
backend/cli.py rebuild-thumbnails  # regenerate thumbnails from stored originals
backend/cli.py reclassify       # re-derive rifle/handgun/maker from stored text
backend/cli.py fetch-photos     # drain the photo queue without re-scraping
backend/cli.py running-scans    # list in-flight scans; exit 1 if any
backend/cli.py infer            # fill blank caliber/country/maker from other vendors
backend/cli.py backup           # snapshot the database now, and prune old ones
```

## Roadmap

[ROADMAP.md](ROADMAP.md) tracks planned work, including the fifteen vendor
sites queued for support, Debian packages and a Launchpad PPA driven by
`v1.2.3.4` git tags, and an Electron desktop app published to the Snap Store.

[TODO.md](TODO.md) is the working checklist for the current build.

## License

BSD 3-Clause — see [LICENSE](LICENSE).
