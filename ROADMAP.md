# Milsurp Monitor — Roadmap

Planned work, roughly in the order it is likely to be tackled. Nothing here is
committed to a date; the sections are a place to capture intent so it does not
live only in a chat log.

Status key: **Planned** · **In progress** · **Shipped** · **Parked**

---

## 1. Vendor coverage

The whole point of the application is breadth. Each new vendor is one subclass
of `SiteScraper` in `backend/app/scrapers/` plus one line in `SCRAPER_CLASSES`;
scheduling, admin controls, price history, images and digests all come for free.

### Shipped

| Site | Slug | Technique |
| --- | --- | --- |
| [Royal Tiger Imports](https://royaltigerimports.com/) | `royal-tiger` | Headless Chrome — infinite scroll, "Load More", classic pagination, Elementor gallery |
| [Empire Arms](https://www.empirearms.com/) | `empire-arms` | Static HTML, thumbnail-delimited block parsing |

### Planned

Ordered by a rough guess at effort. The platform column matters more than the
site: eight of these are WooCommerce and four are Shopify, so the reusable base
classes below are worth building before working through the list one by one.

The platform column is **inferred from the URL shape**, not verified — a
`/product-category/` or `/product-tag/` path means WooCommerce, `/collections/`
means Shopify, and a trailing `-cNNNNNNNNN` means Shift4Shop/3dcart. Anything
not inferable is marked Unknown rather than guessed at.

| # | Site | Entry URL | Likely platform | Notes |
| --- | --- | --- | --- | --- |
| 1 | Classic Firearms | https://www.classicfirearms.com/firearms/rifles/military-surplus/ | BigCommerce | Large catalog, clean pagination |
| 2 | Atlantic Firearms | https://atlanticfirearms.com/military-surplus | Magento/custom | Big surplus section |
| 3 | SARCO Inc. | https://www.sarcoinc.com/live-firearms/rifles/ | Custom | Deep parts inventory too |
| 4 | Surplus Defense (all) | https://www.surplusdefense.com/all-products | Shopify | Shopify exposes `/products.json` — may need no HTML parsing at all |
| 5 | Surplus Defense (rifles) | https://www.surplusdefense.com/surplus-rifles | Shopify | Same site, narrower section; likely one scraper with two sources |
| 6 | DK Firearms | https://dkfirearms.com/product-category/surplus/surplus-firearms/ | WooCommerce | Candidate for the shared WooCommerce base |
| 7 | Arms Unlimited | https://armsunlimited.com/surplus/ | WooCommerce | ” |
| 8 | MCT Defense | https://mctdefense.com/product-category/firearms/ | WooCommerce | ” |
| 9 | Axis Arms | https://axisarmsonline.com/ | Unknown | No obvious surplus-only section — may need filtering |
| 10 | Fernwood Armory | https://www.fernwoodarmory.com/militarysurplus.html | Static HTML | Likely similar in shape to Empire Arms |
| 11 | Edelweiss Arms | https://edelweissarms.com/ | Shopify | High-end collector stock |
| 12 | The Mosin Crate | https://www.themosincrate.com/ | Shopify | Narrow, single-family inventory |
| 13 | J&G Sales | https://www.jgsales.com/product-category/firearms/collectors-corner/military-surplus-collectible-category/ | WooCommerce | ” |
| 14 | Collectors Firearms | https://collectorsfirearms.com/product-category/foreign-military-rifles/ | WooCommerce | Very large catalog; expect a long first scan |
| 15 | Century Arms | https://store.centuryarms.com/surplus-corner/firearms | BigCommerce | Surplus Corner section |
| 16 | Centerfire Systems | https://centerfiresystems.com/ | Custom | No surplus-only section; needs category filtering |
| 17 | Liberty Tree Collectors | https://www.libertytreecollectors.com/Rifles-C&R-c179758763 | Shift4Shop / 3dcart | The `-cNNNNNNNNN` category suffix is the giveaway; note the literal `&` in the URL |
| 18 | Checkpoint Charlie's | https://checkpointcharlies.com/product-tag/cr/ | WooCommerce | A product *tag*, not a category — pagination differs slightly |
| 19 | Pasadena Pawn and Gun | https://www.pasadenapawnandgun.com/antique-guns | Unknown | Pawn shop; inventory may turn over fast and unpredictably |
| 20 | Joe Salter | https://shop.joesalter.com/CandR-Firearms-curio-and-relic-handguns-rifles | Shift4Shop / 3dcart | Long-established collector dealer |
| 21 | CO Gun Sales | https://cogunsales.com/product-category/curio-relics-cr/page/6/ | WooCommerce | URL given is page 6 — start from page 1 |
| 22 | AIM Surplus | https://aimsurplus.com/categories/firearm/curio-and-relic | BigCommerce/custom | High-volume surplus dealer |
| 23 | Ancestry Guns | https://www.ancestryguns.com/product-category/curio-relic/ | WooCommerce | Strong photography; good gallery test case |
| 24 | IMA-USA | https://www.ima-usa.com/collections/original-antique-guns | Shopify | `/collections/` — try `/products.json` first |
| 25 | Simpson Ltd. | https://www.simpsonltd.com/ | Unknown | Very large collector inventory; no surplus-only path given, needs category filtering |
| 26 | Legacy Collectibles | https://legacy-collectibles.com/new-firearms/ | WooCommerce | High-end WWI/WWII collector pieces |
| 27 | [Hunter's Lodge](https://hunterslodge.com) | https://hunterslodge.com | Scanned flyer image | **Special case — see below.** No HTML catalog at all |

#### Hunter's Lodge — the OCR case — **Planned**

Hunter's Lodge does not publish an HTML catalog. It posts a **scanned flyer
image** that is replaced every couple of months, with a small block of text
above it giving the month and year. Everything the site sells for that period is
inside that one picture.

This needs a different shape of scraper from every other vendor:

- **Change detection, not crawling.** A scan just checks two things: has the
  flyer image changed, and has the month/year in the text block above it moved
  on? If neither has, the run finishes immediately having done nothing. Because
  a new flyer only appears every month or two, the site's cadence should default
  to something like **weekly**, not daily — polling it hourly would be pointless
  and rude.
- **OCR the flyer** once it does change, to recover the individual products and
  their prices from the image.
- **Segment the flyer** into its individual listing blocks, so each product
  becomes its own item rather than one giant blob.
- **Title and description come from the OCR** of that listing's own small text
  block.
- **The photo is a crop of the flyer**: the region that was OCR'd for that
  listing, cropped out and **upscaled** so it is legible at card and detail
  size.

Implications for the platform, none of which exist yet:

- A new dependency for OCR (Tesseract via `pytesseract`, or a hosted OCR API)
  and for image segmentation.
- Image *derivation* in the scraper: today a scraper hands back photo URLs and
  the scan service downloads them. This one produces crops of an image it
  already has, so `ScrapedItem` needs a way to supply image **bytes** rather
  than a URL.
- A stable `external_key` when the source has no identifiers at all — likely
  `"<flyer-period>:<slug of the OCR'd title>"`, so a product that appears on two
  consecutive flyers is recognized as the same listing rather than a new one.
- Confidence handling: OCR misreads prices. Low-confidence extractions should
  probably mark the scan PARTIAL and flag the item for review rather than
  silently recording a wrong price into the price history.

Worth treating as its own milestone rather than "one more site".

**Supporting work this implies**

- **Planned** — Support for scrapers that generate their own images rather than
  downloading them by URL (needed by Hunter's Lodge above, and likely by any
  other flyer- or PDF-based vendor).
- **Planned** — A reusable `WooCommerceScraper` base class. **Eight** of the
  sites above are WooCommerce (6, 7, 8, 13, 14, 18, 21, 23, 26); the Royal Tiger
  scraper already has most of the parsing logic and needs generalizing rather
  than rewriting. This is the single highest-leverage piece of work on this
  list.
- **Planned** — A `ShopifyScraper` base class using `/products.json`. Shopify
  publishes structured JSON, so sites 4, 5, 11, 12 and 24 need no HTML parsing,
  no browser, and give reliable prices, variants and image galleries. Cheapest
  wins on the list after the WooCommerce base.
- **Planned** — A `Shift4ShopScraper` base class for sites 17 and 20, which
  share the same 3dcart-derived category URLs and markup.
- **Planned** — A per-site scraper self-test (`make scan site=<slug> --dry-run`)
  that fetches one page and reports what it parsed, without touching the
  database. Adding a vendor currently means a full scan to find out if the
  selectors were right.
- **Planned** — Detect when a site's markup changes: if a scan returns far fewer
  items than the last successful run, mark it PARTIAL and alert rather than
  silently de-listing the whole catalog.
- **Planned** — Per-site `robots.txt` awareness and a configurable crawl delay
  per vendor rather than one global setting.

---

## 2. Packaging and distribution

### Debian packages and a PPA — **Planned**

Build `.deb` packages for every actively supported Ubuntu release and publish
them to a Launchpad PPA.

- `debian/` packaging: `control`, `rules`, `changelog`, `postinst`, `postrm`.
- Install layout matching `scripts/install-production.sh`: `/opt/milsurp`,
  `/etc/milsurp`, the `milsurp` service account, the systemd unit.
- `postinst` runs `scripts/dbupdate.py` so an upgrade migrates the database.
- Target every active Ubuntu variant (currently 24.04 LTS, 25.10 and 26.04 LTS),
  with a source package per series.
- **Release trigger:** pushing a version tag matching `v1.2.3.4` to GitHub kicks
  off a workflow that builds the source packages, signs them, and `dput`s them
  to Launchpad. The tag is the single source of version truth — the workflow
  derives `debian/changelog` from it, so a release is one `git tag` and one
  `git push`.
- Secrets needed in GitHub Actions: the GPG signing key and the Launchpad
  credentials.

### Electron desktop app + Snap Store — **Planned** (after production launch)

Once the service is running in production, wrap the web UI in an Electron
application and publish it as a snap.

- Electron shell pointing at the production instance, with a native window,
  menu bar, and OS notifications for new listings and price drops.
- Package as a strictly-confined snap.
- **Release trigger:** the same `v1.2.3.4` tag that builds the debs also builds
  the snap and pushes it to the Snap Store, so the deb, the PPA and the snap
  never disagree about the version number.
- Secrets needed: a Snapcraft store login macaroon.
- Open question: whether the Electron app talks to the hosted instance only, or
  can also run fully local against its own database.

---

## 3. Application features

### Search and discovery

- **Planned** — Saved searches: name a set of filters and return to it.
- **Planned** — Per-search email alerts, so a digest can be scoped to "Mosin
  Nagants under $400" rather than to whole sites.
- **Planned** — SQLite FTS5 full-text index. The current `LIKE`-per-term search
  is fine at tens of thousands of rows; it will not stay fine at hundreds of
  thousands.
- **Planned** — Price range slider driven by the actual distribution, rather
  than free-text min/max.
- **Planned** — "Similar listings" on the detail page, matched on caliber,
  country and manufacturer.

### Watchlists and notifications

- **Planned** — Per-user watchlist: star a listing, get told when its price
  moves or it sells.
- **Planned** — Price-target alerts ("tell me if this drops below $X").
- **Planned** — Web push notifications as an alternative to email.

### Data quality

- **Planned** — Cross-site duplicate detection. The same rifle listed by two
  vendors should be recognizable.
- **Planned** — Admin UI for the classification heuristics, so a mis-detected
  caliber can be corrected without a code change.
- **Planned** — Manual override fields on an item, preserved across re-scrapes.
- **Planned** — Strip vendor boilerplate from descriptions (ordering
  instructions, FFL notices) that currently reaches the detail view.
- **Parked** — Optical character recognition of proof marks from photos. Fun,
  but a long way from paying for itself.

### Reporting

- **Planned** — Market view: average price by caliber and country over time,
  built on the price history that is already being collected.
- **Planned** — CSV / JSON export of a filtered result set.
- **Planned** — "What changed this week" digest across all sites, distinct from
  the per-user email.

---

## 4. Platform and operations

- **Planned** — PostgreSQL as an alternative backend. SQLite is right for one
  machine; it stops being right the moment scans need to run on more than one.
- **Planned** — Move scans to a real queue (Celery/RQ or `arq`) so the scheduler
  and the workers can be separate processes.
- **Planned** — Prometheus metrics endpoint: scan durations, item counts, error
  rates.
- **Planned** — Structured JSON logging, for log aggregation in production.
- **Planned** — Database backup script plus a documented restore drill. A backup
  nobody has restored is not a backup.
- **Planned** — Image store housekeeping on a schedule (`prune-images` exists as
  a CLI command but is not yet automatic).
- **Planned** — Docker Compose deployment as an alternative to the bare-metal
  installer.

---

## 5. Security and compliance

- **Planned** — Two-factor authentication (TOTP) for admin accounts.
- **Planned** — Audit log of administrative actions: user creation, role
  changes, site enable/disable.
- **Planned** — Self-service password reset over email. Deliberately not built
  yet: it adds an unauthenticated, token-issuing endpoint, and with a handful of
  users an admin reset is a smaller attack surface.
- **Planned** — Session management UI: see and revoke active sessions.
- **Planned** — Move the session token from `sessionStorage` to a
  `HttpOnly`/`Secure`/`SameSite=Strict` cookie plus a CSRF token. That removes
  the token from JavaScript's reach entirely, at the cost of needing CSRF
  protection the current header-based scheme does not.

---

## 6. Testing and tooling

- **Planned** — Recorded HTTP fixtures for every scraper, so parsing can be
  tested without touching a vendor's site.
- **Planned** — A nightly canary run against each live site that fails loudly
  when a vendor's markup changes.
- **Planned** — Visual regression tests on the screenshots `make screenshots`
  already produces.
- **Planned** — Load testing of the item list endpoint at realistic row counts.
- **Planned** — Raise the coverage floor from 65% toward 80% as the suite fills
  in.
