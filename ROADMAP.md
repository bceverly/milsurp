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
| [Hunter's Lodge](https://www.hunterslodge.com/) | `hunters-lodge` | OCR of a scanned magazine flyer |
| [Collectors Firearms](https://collectorsfirearms.com/) | `collectors-firearms` | WooCommerce base class — category pages, path pagination |

### Planned

Ordered by a rough guess at effort. The platform column matters more than the
site: eight of these are WooCommerce and four are Shopify, so the reusable base
classes below are worth building before working through the list one by one.

The platform column is **inferred from the URL shape**, not verified — a
`/product-category/` or `/product-tag/` path means WooCommerce, `/collections/`
means Shopify, and a trailing `-cNNNNNNNNN` means Shift4Shop/3dcart. Anything
not inferable is marked Unknown rather than guessed at.

### What to take from a site that also sells parts

Several of these dealers carry a large accessories and components inventory
alongside the firearms. **The only non-firearm category worth ingesting is
"parts kits".** Individual components — stocks, magazines, springs, barrels,
bayonets, slings, cleaning kits, ammunition — are explicitly out of scope: they
turn over constantly, they swamp the listing count, and nobody is watching this
application for a price drop on a recoil spring.

A parts kit is a different thing: it is a whole disassembled firearm minus the
receiver, it is priced and tracked like a firearm, and it is exactly what
someone following surplus stock wants alerting on. Royal Tiger's "Parts Kit"
section is the reference case, and `classify.enrich()` already has somewhere to
put the distinction.

Scrapers for parts-carrying sites should therefore ingest the firearm
categories plus any parts-kit category, and skip the rest of the parts tree
rather than importing it and filtering later.

### The build order

Grouped by **backend platform**, because one platform base class unlocks a whole
group: the ten WooCommerce sites are ten selector-tweaks once the first one
works, and the Shopify sites need no HTML parsing at all. Within each group the
most popular site comes first, so the base class is proved against the catalog
most worth having.

**How "popular" was decided, and how far to trust it.** Where a third-party
traffic estimate exists it is quoted with its date; those are estimates, not
measurements, and they move. Everything else is ordered on softer evidence —
catalog size, how often a dealer is named in "best online gun store" round-ups
and collector forums, and how long they have been trading. Sites with no figure
are ordered by judgement and are the ones to re-check before committing to an
order. The ordering is a starting point for scheduling work, not a claim about
these businesses.

#### Group A — WooCommerce (10 sites) · base class **shipped**

`app/scrapers/woocommerce.py` covers the group: `li.product` cards, the post id
as the external key, sale-aware prices, lazy-loaded images, gallery
de-duplication, and pagination by following the shop's own "next" link. A new
shop in this group should be a slug, a name, a list of category URLs and — if
its theme is customized — a couple of selectors in front of the defaults.

**Three findings from the first build that apply to the whole group.**

1. **The WooCommerce Store API is not the shortcut it looks like.** Every shop
   here publishes `/wp-json/wc/store/v1/products`, which returns exactly the
   structured data the HTML parsing recovers by hand. Filtering it to a
   category, or reading past the first ten products, needs a query string — and
   Collectors Firearms disallows `/*?*`. Their catalog is 207,000 products, so
   an unfiltered walk is not an alternative. Worth re-checking per shop: where
   robots permits it, a subclass can override `scrape()` and use the API.
2. **robots.txt is now obeyed** (`app/robots.py`), which changes scan planning
   more than anything else here: Collectors Firearms sets `Crawl-delay: 10`, so
   their scan is half an hour of wall clock and almost no bandwidth.
3. **Two of these shops sit behind a Cloudflare challenge.** dkfirearms.com
   returns 403 to plain HTTP, so it needs the browser path Royal Tiger already
   uses rather than the `requests` path. Expect the same of others in the group;
   it is a per-site fact, not a platform one.
4. **A published `Crawl-delay` may be optimistic.** Collectors Firearms asks for
   ten seconds, was crawled at exactly ten, and returned 429 after sixteen
   minutes. A 429 now sets a standing slower pace for the rest of the scan, and
   a shop measured to need more than it advertises gets a `min_request_delay`.
   Budget the *first* scan of a large shop in hours, not minutes; later scans
   only pay for listings that are new.

| # | Site | Entry URL | Audience signal | Notes |
| --- | --- | --- | --- | --- |
| — | **Collectors Firearms** | https://collectorsfirearms.com/product-category/rifles/foreign-military-rifles/ | ~284K visits/mo (Similarweb, Oct 2024) | **Shipped.** Foreign and U.S. military rifle sections. Their military handguns are not separately categorized, so handguns are out of scope for this vendor until they are |
| 2 | J&G Sales | https://www.jgsales.com/product-category/firearms/collectors-corner/military-surplus-collectible-category/ | Top-10 competitor of Classic Firearms (Similarweb) | Long-established, high volume |
| 3 | DK Firearms | https://dkfirearms.com/product-category/surplus/surplus-firearms/ | Competitor set includes Atlantic Firearms | **Behind Cloudflare** — plain HTTP gets a 403 challenge page, so this one needs the browser |
| 4 | Legacy Collectibles | https://legacy-collectibles.com/new-firearms/ | Tracked by Similarweb as a peer of IMA-USA | High-end WWI/WWII collector pieces |
| 5 | Ancestry Guns | https://www.ancestryguns.com/product-category/curio-relic/ | — | Strong photography; the gallery test case |
| 6 | Axis Arms | https://axisarmsonline.com/product-category/rifles/ | — | **Two sections**: `/product-category/rifles/` and `/product-category/handguns/`. One scraper, two sources — same shape as Empire Arms |
| 7 | Arms Unlimited | https://armsunlimited.com/surplus/ | — | Standard WooCommerce category |
| 8 | MCT Defense | https://mctdefense.com/product-category/firearms/ | — | ” |
| 9 | CO Gun Sales | https://cogunsales.com/product-category/curio-relics-cr/page/6/ | — | URL given is page 6 — start from page 1 |
| 10 | Checkpoint Charlie's | https://checkpointcharlies.com/product-tag/cr/ | — | A product *tag*, not a category; pagination differs slightly |

#### Group B — BigCommerce (3 sites) · the largest audiences

Small group, but it holds the most-visited surplus catalog on the list.

| # | Site | Entry URL | Audience signal | Notes |
| --- | --- | --- | --- | --- |
| 1 | Classic Firearms | https://www.classicfirearms.com/firearms/rifles/military-surplus/ | 1.6M visits/3mo, US e-commerce category rank #50 (Similarweb, Jul 2026) | The biggest name here; large catalog, clean pagination |
| 2 | AIM Surplus | https://aimsurplus.com/categories/firearm/curio-and-relic | ~357K visits/mo (Semrush, Apr 2026) | High-volume surplus dealer |
| 3 | Century Arms | https://store.centuryarms.com/surplus-corner/firearms | Importer, widely stocked by the others | Surplus Corner section only |

#### Group C — Shopify (4 sites) · cheapest wins on the list

Shopify publishes `/products.json`: structured data, reliable prices, variants
and image galleries, no HTML parsing and no browser. Least work per site of
anything here.

| # | Site | Entry URL | Audience signal | Notes |
| --- | --- | --- | --- | --- |
| 1 | IMA-USA | https://www.ima-usa.com/collections/original-antique-guns | Trading since 1981; 70K+ eBay sales; has a Wikipedia entry | Try `/products.json` first |
| 2 | Surplus Defense | https://www.surplusdefense.com/all-products | — | Two sources, one scraper: `/all-products` and `/surplus-rifles` |
| 3 | Edelweiss Arms | https://edelweissarms.com/ | — | High-end collector stock |
| 4 | The Mosin Crate | https://www.themosincrate.com/ | — | Narrow, single-family inventory |

#### Group D — Shift4Shop / 3dcart (2 sites)

Shared 3dcart-derived category URLs and markup; the `-cNNNNNNNNN` suffix is the
giveaway.

| # | Site | Entry URL | Audience signal | Notes |
| --- | --- | --- | --- | --- |
| 1 | Joe Salter | https://shop.joesalter.com/CandR-Firearms-curio-and-relic-handguns-rifles | Long-established collector dealer | — |
| 2 | Liberty Tree Collectors | https://www.libertytreecollectors.com/Rifles-C&R-c179758763 | — | Note the literal `&` in the URL |

#### Group E — one-off builds (6 sites) · no reuse, so weigh each on its own

No shared platform, so each is a scraper from scratch. Atlantic Firearms is the
single most-visited site on the whole list and is worth building on its own
merits despite that.

| # | Site | Entry URL | Platform | Audience signal | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Atlantic Firearms | https://atlanticfirearms.com/military-surplus | Magento/custom | ~837K visits/mo (Similarweb, Aug 2024); ~606K (Oct 2024) | The most-visited site here. Big surplus section |
| 2 | SARCO Inc. | https://www.sarcoinc.com/live-firearms/rifles/ | Custom | Named in surplus round-ups as a primary source | Deep parts inventory — take the firearms and any parts *kits*, skip the component tree (see below) |
| 3 | Simpson Ltd. | https://www.simpsonltd.com/ | Unknown | "Largest full-line collector shop in the Midwest", trading since 1962 | Very large; no surplus-only path, needs category filtering |
| 4 | Centerfire Systems | https://centerfiresystems.com/ | Custom | — | No surplus-only section; needs category filtering |
| 5 | Fernwood Armory | https://www.fernwoodarmory.com/militarysurplus.html | Static HTML | — | Likely the same shape as Empire Arms — cheap |
| 6 | Pasadena Pawn and Gun | https://www.pasadenapawnandgun.com/antique-guns | Unknown | — | Pawn shop; inventory turns over fast and unpredictably |

#### Group F — built

| Site | Entry URL | Platform | Status |
| --- | --- | --- | --- |
| Royal Tiger Imports | https://royaltigerimports.com/ | WooCommerce / Elementor | **Built** — browser-driven; infinite scroll, Load More and pagination |
| Empire Arms | https://www.empirearms.com/ | Static HTML | **Built** — two catalog pages |
| [Hunter's Lodge](https://www.hunterslodge.com/) | https://www.hunterslodge.com/ | Scanned flyer image | **Built** — OCR; see below |

### What to take from a site that also sells parts

Several of these dealers carry a large accessories and components inventory
alongside the firearms. **The only non-firearm category worth ingesting is
"parts kits".** Individual components — stocks, magazines, springs, barrels,
bayonets, slings, cleaning kits, ammunition — are explicitly out of scope: they
turn over constantly, they swamp the listing count, and nobody is watching this
application for a price drop on a recoil spring.

A parts kit is a different thing: it is a whole disassembled firearm minus the
receiver, it is priced and tracked like a firearm, and it is exactly what
someone following surplus stock wants alerting on. Royal Tiger's "Parts Kit"
section is the reference case, and `classify.enrich()` already has somewhere to
put the distinction.

Scrapers for parts-carrying sites should therefore ingest the firearm
categories plus any parts-kit category, and skip the rest of the parts tree
rather than importing it and filtering later.

| # | Site | Entry URL | Likely platform | Notes |
| --- | --- | --- | --- | --- |
| 1 | Classic Firearms | https://www.classicfirearms.com/firearms/rifles/military-surplus/ | BigCommerce | Large catalog, clean pagination |
| 2 | Atlantic Firearms | https://atlanticfirearms.com/military-surplus | Magento/custom | Big surplus section |
| 3 | SARCO Inc. | https://www.sarcoinc.com/live-firearms/rifles/ | Custom | Deep parts inventory — take the firearms and any parts *kits*, skip the component tree (see above) |
| 4 | Surplus Defense (all) | https://www.surplusdefense.com/all-products | Shopify | Shopify exposes `/products.json` — may need no HTML parsing at all |
| 5 | Surplus Defense (rifles) | https://www.surplusdefense.com/surplus-rifles | Shopify | Same site, narrower section; likely one scraper with two sources |
| 6 | DK Firearms | https://dkfirearms.com/product-category/surplus/surplus-firearms/ | WooCommerce | Candidate for the shared WooCommerce base |
| 7 | Arms Unlimited | https://armsunlimited.com/surplus/ | WooCommerce | ” |
| 8 | MCT Defense | https://mctdefense.com/product-category/firearms/ | WooCommerce | ” |
| 9 | Axis Arms | https://axisarmsonline.com/product-category/rifles/ | WooCommerce | Two sections to scrape: `/product-category/rifles/` and `/product-category/handguns/`. One scraper, two sources — same shape as Empire Arms |
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
| 27 | [Hunter's Lodge](https://hunterslodge.com) | https://www.hunterslodge.com/ | Scanned flyer image | **Built** — see below. No HTML catalog at all |

#### Hunter's Lodge — the OCR case — **Built**

Hunter's Lodge does not publish an HTML catalog. It posts a **scanned flyer
image** that is replaced every couple of months, with a small block of text
above it giving the month and year. Everything the site sells for that period is
inside that one picture.

Implemented as `app/scrapers/hunters_lodge.py` (the vendor) and
`app/scrapers/flyer.py` (the reusable flyer machinery).

- [x] **Change detection, not crawling.** A scan checks the flyer's Wix media
      id and the month/year above it. If neither has moved, the run finishes in
      one request having read nothing — measured at 0.19s against the live
      site. Cadence defaults to **weekly**.
- [x] **OCR the flyer** once it does change. Tesseract, via `pytesseract`.
- [x] **Segment the flyer** so each product is its own item. Done by cutting on
      the page's *rules*, not its whitespace: an advertisement is inked edge to
      edge, and on the real page not one of its 4813 pixel columns is blank, so
      a classic XY-cut finds nothing to split.
- [x] **Title and description come from the OCR** of that listing's own block.
- [x] **The photo is a crop of the flyer**, padded, upscaled when small (capped
      at 3x, which is the point past which enlarging only magnifies the paper
      grain), and stored as PNG rather than JPEG — these are crops of an
      already-compressed scan, and small text is what JPEG is worst at.

Platform work this needed, all of it now in place:

- [x] OCR dependency: `pytesseract` in `requirements.txt`, `tesseract-ocr` in
      both installers. The import is lazy and the site reports a clear error
      when it is missing, so a machine without OCR runs everything else.
- [x] Image *derivation*: `ScrapedItem.generated_images` carries `(key, bytes)`,
      and `ImageStore.store_bytes()` writes them with the same layout, naming
      and thumbnailing as a download.
- [x] A stable `external_key`: `<wix-media-id>-<issue>-<NNN>`. Both signals are
      used, so a vendor who re-uploads the same image under a new issue is
      treated as having published something new.
- [x] `ScrapeContext.report_unchanged()`, because "I checked and there is
      nothing new" is not the same statement as "the catalog is empty" — and
      without the distinction an unchanged flyer would de-list the whole site.

**Measured accuracy, honestly.** Against the real July 2026 flyer this recovers
22 listings with names and prices. That is most of the page but not all of it,
and a few listings take a neighbouring panel's price. Every listing carries the
crop it was read from and keeps the raw OCR text as its description, so the
source is always one click away.

- [x] **Panel-bounded listings.** Side-by-side panels within one half of the
      page were read interleaved, so a product quoted its neighbour's price —
      the CZ 50/70 pistol kit came out at the Turkish Mauser's $322.88. The
      page is now cut recursively on its own rules and a panel boundary ends a
      listing, while still letting a heading cross the single rule the flyer
      draws between a name and its description.
- [x] **Whole product names.** The flyer breaks a name over as many lines as it
      needs — "S&W" / "K-FRAME," / "SNUB-NOSE" / "REVOLVER KITS" — and only the
      last line was kept. A run of heading lines is now one name.
- [x] **Heading attachment.** Four faults, found by measuring rather than
      squinting — the metric is "does this title begin with a product name",
      which took the reader from 60% to **88%** (23 of 26 listings):
      1. A name is set *on* the rule beneath the panel above it, so assigning
         a line to a panel by its midpoint put it in the gap and it belonged to
         neither. Panels are now assigned by area of overlap, with the nearest
         panel below as a fallback.
      2. A group that ended without a price was discarded — and it is almost
         always a name looking for one. The heading lines are now carried into
         the next listing, which is what fixed titles reading "needs TLC" and
         "frame for".
      3. A bulleted line is a product and anything above it is the section
         header it sits under, so "OLE ZEKE'S TREASURES" was taking the title
         of the first item beneath it.
      4. Every product here is named in capitals, so lower-case words in front
         of the first capitalised one leaked in from a neighbour: "Swedish
         steel. GAHENDRA MARTINI RIFLE".
- [x] **Content-versioned photo URLs.** `/items/<id>/photos/<id>` is built from
      two reused database ids, so the same URL could come to hold different
      content — and did, every time a site was cleared and re-scanned. The URL
      now carries a `?v=` token derived from the stored file, so changed
      content is a changed URL.
- [x] **Bulleted lists survive OCR losing the bullet**, and the price is taken
      as the first amount in a listing rather than the largest — the order the
      page is written in. 26 to 30 listings, and the prices that were borrowed
      from a neighbour are the item's own.
- [ ] **The last three.** "1903 TURKISH CONTRACT MAUSERS", "WW2 ENFIELD NO1 MK2
      PARTS KITS" and "CZ 52 SEMI AUTO ASSAULT RIFLES" still take their title
      from their own prose. In each case the heading is on the far side of a
      *column* boundary from its body, which is the one boundary nothing is
      allowed to cross — and for good reason, since crossing it is what made a
      product quote its neighbour's price. Worth revisiting only with a way to
      tell the two cases apart.
- [ ] **Confidence handling.** OCR misreads prices. Tesseract reports a
      per-word confidence that is currently used only as a filter; a listing
      whose price came from a low-confidence token should mark the scan PARTIAL
      and flag the item for review rather than quietly writing a wrong number
      into the price history.

**Supporting work this implies**

- [x] **Done** — Support for scrapers that generate their own images rather
  than downloading them by URL. `ScrapedItem.generated_images` plus
  `ImageStore.store_bytes()`; used by Hunter's Lodge and available to any other
  flyer- or PDF-based vendor.
- [ ] **Planned** — A reusable `WooCommerceScraper` base class. **Group A** is
  ten sites on one platform; the Royal Tiger scraper already has most of the
  parsing logic and needs generalizing rather than rewriting. This is the
  single highest-leverage piece of work on this list.
- [ ] **Planned** — A `ShopifyScraper` base class using `/products.json`.
  Shopify publishes structured JSON, so all of **Group C** needs no HTML
  parsing, no browser, and gives reliable prices, variants and image galleries.
  Cheapest wins on the list after the WooCommerce base.
- [ ] **Planned** — A `Shift4ShopScraper` base class for **Group D**, whose two
  sites share the same 3dcart-derived category URLs and markup.
- [ ] **Planned** — A per-site scraper self-test (`make scan site=<slug> --dry-run`)
  that fetches one page and reports what it parsed, without touching the
  database. Adding a vendor currently means a full scan to find out if the
  selectors were right.
- [ ] **Planned** — Detect when a site's markup changes: if a scan returns far fewer
  items than the last successful run, mark it PARTIAL and alert rather than
  silently de-listing the whole catalog.
- [ ] **Planned** — Per-site `robots.txt` awareness and a configurable crawl delay
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

- **Shipped** — The maker list is a table, not code, with an admin page at
  `/manufacturers`. Aliases are literal text rather than patterns, order is part
  of the data because it decides ties ("Mosin-Nagant" before "Nagant"), and an
  edit re-files the listings it can reach and reports how many moved.
- **Shipped, and dry** — Cross-catalog field filling (`milsurp infer`): borrow a
  blank caliber, country or maker from another vendor's better-described listing
  of the same thing. It matches titles only and demands two nearly unique words
  plus agreement on rifle/handgun/neither, which on the current three vendors
  finds nothing. That is the intended behavior at this catalog size; it gets
  better with every vendor added. See `app/services/crosscatalog.py` for what a
  looser version got wrong.
- **Planned** — Cross-site duplicate detection proper. The same rifle listed by
  two vendors should be recognizable — the token index built for field filling
  is the start of this, but a duplicate needs more than a shared model name.
- **Planned** — Admin UI for the rest of the classification heuristics
  (calibers, countries, the accessory vetoes), on the pattern the maker list now
  sets.
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
- **Shipped** — Daily database snapshots in production: SQLite's online backup
  API, ten kept, `backups/` gitignored, off in development. Taken by the
  scheduler on the age of the newest snapshot rather than on a timer, so a
  restart does not skip a day, and `milsurp backup` takes one by hand.
- **Planned** — A documented restore drill. A backup nobody has restored is not
  a backup, and the snapshots above have been opened by the tests but never
  actually restored into service.
- **Planned** — Off-machine copies of those snapshots. Ten backups on the same
  disk as the database survive a bad UPDATE, which is what they were written
  for, but not a lost disk.
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
