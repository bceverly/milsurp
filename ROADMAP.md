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

**Where this stands: nine vendors read, nineteen queued, one dropped.** Of the
eighteen, five are blocked on something that is not the platform — two need a
browser, one needs an entry URL, one publishes no prices, and two refuse a plain
request — so they are not simply waiting their turn in the queue.

### Shipped

| Site | Slug | Technique |
| --- | --- | --- |
| [Royal Tiger Imports](https://royaltigerimports.com/) | `royal-tiger` | Headless Chrome — infinite scroll, "Load More", classic pagination, Elementor gallery |
| [Empire Arms](https://www.empirearms.com/) | `empire-arms` | Static HTML, thumbnail-delimited block parsing |
| [Hunter's Lodge](https://www.hunterslodge.com/) | `hunters-lodge` | OCR of a scanned magazine flyer |
| [Collectors Firearms](https://collectorsfirearms.com/) | `collectors-firearms` | WooCommerce base class — category pages, path pagination |
| [Ancestry Guns](https://www.ancestryguns.com/) | `ancestry-guns` | WooCommerce — one selector (their `h2` is a share widget) |
| [Axis Arms](https://axisarmsonline.com/) | `axis-arms` | WooCommerce behind an Elementor loop; two sections |
| [CO Gun Sales](https://cogunsales.com/) | `co-gun-sales` | WooCommerce for text; their photographs are a CSS background and a JSON attribute, with no `<img>` anywhere |
| [Checkpoint Charlie's](https://checkpointcharlies.com/) | `checkpoint-charlies` | WooCommerce, a product *tag* rather than a category. Catalog only — their `/product/` pages refuse every request |
| [Legacy Collectibles](https://www.legacy-collectibles.com/) | `legacy-collectibles` | BigCommerce base class — `article.card`, `data-entity-id`, query-string pagination |

### Planned

Ordered by a rough guess at effort. The platform column matters more than the
site, because the reusable base class is most of the work: two of them —
WooCommerce and BigCommerce — are now shipped, and a site on either is a subclass
of a few lines.

The platform column below was originally **inferred from the URL shape** — a
`/product-category/` or `/product-tag/` path means WooCommerce, `/collections/`
means Shopify, and a trailing `-cNNNNNNNNN` means Shift4Shop/3dcart. That
inference was wrong often enough to matter; see **Platforms, verified** below,
which measured it instead and is what to trust.

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
group. Within each group the most popular site comes first, so the base class is
proved against the catalog most worth having.

**How well that has worked, now that two groups are built.** The base classes
earned their keep — a new shop on either really is a slug, a name and a list of
URLs. What did not hold is the claim this section used to make, that the ten
WooCommerce sites would be "ten selector-tweaks once the first one works". Two
of the ten were not WooCommerce at all. Three of the remaining eight are blocked
on a client-side catalog, a Cloudflare challenge and a page of category tiles —
none of which a base class can help with. And of the five that shipped, one
needed its title read from a different element, one needed cards de-duplicated
because the theme emits each twice, one needed two entirely new ways of finding
a photograph, and one needed the scan taught to survive a shop that refuses its
own pages.

So: group by platform, because it is still the best predictor available and the
base class is real leverage. Just do not read a group of four as four cheap
sites. Read it as one base class plus four unknowns.

**How "popular" was decided, and how far to trust it.** Where a third-party
traffic estimate exists it is quoted with its date; those are estimates, not
measurements, and they move. Everything else is ordered on softer evidence —
catalog size, how often a dealer is named in "best online gun store" round-ups
and collector forums, and how long they have been trading. Sites with no figure
are ordered by judgement and are the ones to re-check before committing to an
order. The ordering is a starting point for scheduling work, not a claim about
these businesses.

#### Group A — WooCommerce · base class **shipped**

Ten sites were filed here on the URL-shape guess. Two of them turned out to be
BigCommerce and moved to Group B; of the eight that remain, **five are shipped**
and three are blocked on something other than the platform.

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
5. **A 429 does not always mean "too fast".** Past the 300s ceiling there is no
   slower left to go, so a refusal there is a refusal and fails immediately
   rather than sleeping through three more attempts. A page that cannot be read
   then costs what was on that page and nothing more — a product page costs its
   listing the gallery, a catalog page ends that section. Checkpoint Charlie's
   is the case that paid for all of it.
6. **Count the photographs before calling a shop done.** Titles and prices being
   right is what a working scraper looks like, and CO Gun Sales had both for 144
   listings while storing no pictures at all. "No `<img>` on the page" does not
   mean "needs a browser": theirs are a CSS `background-image` on the card and
   JSON in a `data-wcsvi` attribute on the product page, and the site is
   entirely static.

| # | Site | Entry URL | Status | Notes |
| --- | --- | --- | --- | --- |
| — | **Collectors Firearms** | `/product-category/rifles/foreign-military-rifles/` | **Shipped** | ~284K visits/mo. Foreign and U.S. military rifles. `Crawl-delay: 10`, and their limiter wants more — see `min_request_delay` |
| — | **Ancestry Guns** | `/product-category/curio-relic/` | **Shipped** | Curio & Relic only. Their `h2` is a "Share on:" widget, so the title comes from the `h3` |
| — | **Axis Arms** | `/product-category/rifles/` + `/handguns/` | **Shipped** | Elementor loop: the `h1` is the name and the `h2` is the price. Cards match twice (article and inner div); de-duplicated by post id |
| — | **CO Gun Sales** | `/product-category/curio-relics-cr/` | **Shipped** | Stock WooCommerce for titles and prices, and nothing like it for pictures: the page carries no `<img>` at all. The card's photo is a CSS `background-image` and the product gallery is JSON in a `data-wcsvi` attribute, so all 144 listings arrived with no photograph until both fallbacks existed. The old entry URL here said `/page/6/`, which was somebody's browsing position; pagination follows the shop's own "next" link |
| — | **Checkpoint Charlie's** | `/product-tag/cr/` | **Shipped, but barely** | A product *tag*, which renders the same loop and paginates the same way. Their `/product/` pages answer 429 to any pace and any headers, and after an hour of that they stop answering the category pages too: a full run took 56 minutes to walk 24 listings and save 5. The scan now survives it — catalog-only entries, and a section that stops at the page it got to — but this site is a candidate for the browser path, or for dropping. See "When a shop refuses a page" in the README |
| 1 | J&G Sales | `/product-category/firearms/collectors-corner/military-surplus-collectible-category/` | **Needs a browser** | The `li.product` elements come back as 65-byte empty placeholders: the catalog is rendered client-side. Same treatment as Royal Tiger |
| 2 | DK Firearms | `/product-category/surplus/surplus-firearms/` | **Needs a browser** | Cloudflare returns a 403 challenge to plain HTTP |
| 3 | MCT Defense | `/product-category/firearms/` | **Needs an entry URL** | That page is thirty *category* tiles, not products — no price element anywhere on it. Their actual product pages have to be found before this is worth writing |

**Moved out of this group.** Legacy Collectibles and Arms Unlimited were listed
here on the URL-shape inference this section warned about, and they are not
WordPress: their robots.txt names `cart.php`, `checkout.php` and
`productimage.php`, and nothing in their markup parses as WooCommerce. They are
BigCommerce, and belong in Group B.

#### Platforms, verified

The groupings below were originally **inferred from the shape of a URL**, and
that section said so. Having now checked every remaining site by its response
headers and cookies — which are unambiguous where markup is not — most of those
guesses were wrong. What follows is measured, not inferred.

The first pass at this used HTML markers and was useless: a pattern for
Magento's static paths matched eleven of sixteen sites. Cookies settle it —
`SF-CSRF-TOKEN` and `fornax_anonymousId` are BigCommerce, `_shopify_y` is
Shopify, `X-Magento-Vary` is Magento, `ssr-caching` is Wix, `OCSESSID` is
OpenCart.

| Platform | Sites | Notes |
| --- | --- | --- |
| **BigCommerce** | Legacy Collectibles, Arms Unlimited, Edelweiss Arms, SARCO | **Base class shipped** (`app/scrapers/bigcommerce.py`). Four sites, one platform, and the markup is close to WooCommerce's: `article.card`, an entity id per card, a "next" link. Two of these were in Group A on the URL guess. Of the four, one shipped, one was dropped as out of scope, and two are blocked — see Group B |
| **Shopify** | IMA-USA, Centerfire Systems | **Next.** Cheapest per site — IMA-USA's `/products.json` returns full structured products. Only two sites though, and Centerfire was filed as a one-off build |
| **Wix** | Surplus Defense, The Mosin Crate, Pasadena Pawn | Three, not one-offs. Wix renders client-side, so expect the browser path |
| **Magento** | Century Arms | One, not the three Group B claimed |
| **Laravel (custom)** | AIM Surplus | `laravel_session`; a bespoke application, not BigCommerce |
| **PrestaShop** | Atlantic Firearms | The most-visited site on the list, and its own build |
| **OpenCart** | Joe Salter | `OCSESSID`; not Shift4Shop |
| **WooCommerce (blocked)** | J&G Sales, DK Firearms, MCT Defense | See Group A |
| **Unknown** | Classic Firearms, Simpson Ltd | No marker in headers, cookies or markup. Need a closer look |
| **No platform at all** | eBayonet | Apache, hand-written pages saved from Microsoft Word, no `robots.txt`. Static HTML parsing, like Empire Arms |
| **Refused a plain request** | Liberty Tree (403), Fernwood Armory (403 + Cloudflare) | Not identified; both need the browser before anything else can be said |

#### Group B — BigCommerce · base class **shipped**

Four sites on the platform, and the shape is familiar: `article.card` per
product, a numeric entity id on the card, a price element, and a `rel="next"`
pagination link.

It has not paid off the way the count suggested. One shipped, one was written
and then dropped as out of scope, and the remaining two are each blocked on
something the platform has nothing to do with — a client-side catalog and a shop
that does not publish prices. The base class was still worth building; the
lesson is that "four sites, one platform" counted sites rather than catalogs.

The questions the WooCommerce work produced apply here and are worth asking
before writing anything: is it really this platform, does the catalog arrive in
the HTML, is that page products or categories, and did the photographs come with
it?

`app/scrapers/bigcommerce.py` covers the group. Two things differ from
WooCommerce and are the reason it is a separate base class rather than a
subclass: **the key**, because Stencil themes are inconsistent about carrying
`data-entity-id` and the URL path is the fallback; and **pagination by query
string** (`?page=2`), which a shop is entitled to disallow in robots.txt — the
walk asks before each page rather than assuming.

| # | Site | Entry URL | Status |
| --- | --- | --- | --- |
| — | **Legacy Collectibles** | `/new-firearms/`, `/antique-handguns/`, `/antique-long-guns/` | **Shipped.** `data-entity-id` on every card, so a listing keeps its identity through a rename. Their two "Modern" sections were dropped after the first run: Glocks, Sigs, Kimber 2011s and FN SCARs, 43 listings and not one of them surplus — the Arms Unlimited call again. `/new-firearms/` is a new-arrivals feed rather than a category and carries some of the same, but it is also the only place a Portuguese-contract Mauser Luger appears |
| 1 | SARCO Inc. | https://www.sarcoinc.com/live-firearms/rifles/ | **Needs a browser.** No cards, titles or prices in the HTML: rendered client-side, like J&G Sales |
| 2 | Edelweiss Arms | https://edelweissarms.com/antiques/long-guns/ | **Prices are not published.** Cards and titles parse; the price element is empty site-wide. Worth having for new-stock alerts, worth nothing for price tracking — decide before building |
| — | ~~Arms Unlimited~~ | — | **Dropped: not a surplus dealer.** Written, run against the live site, and backed out. Their `/surplus/` section is police trade-in gear — Tasers, holsters, a water bottle — and `/rifles/` is modern Colt M4s. 97 listings landed correctly and none of them belonged in this catalog. The scraper was a two-line subclass; restoring it is easy if modern stock is ever wanted |

#### Group C — Shopify (2 sites) · least work per site

Shopify publishes `/products.json`: structured data, reliable prices, variants
and image galleries, no HTML parsing and no browser. **Verified** on IMA-USA,
which returns full product objects. Worth doing straight after BigCommerce, or
before it if two sites quickly is more use than four sites slowly.

| # | Site | Entry URL | Audience signal |
| --- | --- | --- | --- |
| 1 | IMA-USA | https://www.ima-usa.com/collections/original-antique-guns | Trading since 1981; has a Wikipedia entry |
| 2 | Centerfire Systems | https://centerfiresystems.com/ | No surplus-only section — needs filtering by category |

#### Group D — one site each

Each of these is its own build, so weigh it on its own merits. Atlantic Firearms
is the most-visited site on the whole list and is worth building despite that.

| # | Site | Entry URL | Platform | Audience signal | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Atlantic Firearms | https://atlanticfirearms.com/military-surplus | PrestaShop | ~837K visits/mo (Similarweb, Aug 2024) | The most-visited here. Big surplus section |
| 2 | Classic Firearms | https://www.classicfirearms.com/firearms/rifles/military-surplus/ | Unknown | 1.6M visits/3mo (Similarweb, Jul 2026) | The biggest name on the list; identify it first |
| 3 | AIM Surplus | https://aimsurplus.com/categories/firearm/curio-and-relic | Laravel | ~357K visits/mo (Semrush, Apr 2026) | Bespoke application. An earlier list guessed BigCommerce from the URL shape; the cookies say otherwise |
| 4 | Century Arms | https://store.centuryarms.com/surplus-corner/firearms | Magento | Importer, widely stocked by the others | Surplus Corner section only |
| 5 | Joe Salter | https://shop.joesalter.com/CandR-Firearms-curio-and-relic-handguns-rifles | OpenCart | Long-established collector dealer | Not Shift4Shop, which the `-cNNNNNNNNN` URL suffix suggested |
| 6 | Simpson Ltd. | https://www.simpsonltd.com/ | Unknown | Trading since 1962 | Very large; no surplus-only path, so needs filtering by category |
| 7 | eBayonet | https://www.ebayonet.com/bayonetsa_f.htm | Static HTML (Word export) | Specialist; catalog dated 9 Aug 2026 | Bayonets only. See below — it is the closest thing on this list to Empire Arms |

**eBayonet, measured rather than guessed.** No e-commerce platform at all: an
Apache server, hand-maintained pages, and no `robots.txt` (it 404s, which the
crawler treats as "no restrictions"). The pages were saved out of Microsoft
Word — `MsoNormal` classes and `<o:p>` tags throughout — so the markup carries
no product structure whatsoever. What it does have is a consistent shape:

- The catalog is five pages split by country initial: `bayonetsa_f.htm`,
  `bayonetsg.htm`, `bayonetsh_m.htm`, `bayonetsn_s.htm`, `bayonetst_z.htm`.
- Each listing is a `<p>` beginning with a stock number, which is a stable
  external key and better than most shops manage.
- Countries are `<hr>` plus a bold heading, so the country is recoverable from
  position — this site would populate that facet properly.
- The "G" page alone is 211 KB with 118 prices, so the catalog is substantial.
- No images on the listing pages, so listings would carry no photograph.

This is the Empire Arms treatment — static HTML, block parsing on a delimiter —
rather than a platform base class, and it is worth doing now that bayonets have
their own type rather than sitting in the accessories pile.

#### Group E — Wix (3 sites) · expect the browser

Wix renders its catalog client-side, so these are likely to need the browser
path rather than plain HTTP, the way J&G Sales does.

| # | Site | Entry URL | Notes |
| --- | --- | --- | --- |
| 1 | Surplus Defense | https://www.surplusdefense.com/all-products | Also `/surplus-rifles` — one scraper, two sources, the same shape as Empire Arms |
| 2 | The Mosin Crate | https://www.themosincrate.com/ | Narrow, single-family inventory |
| 3 | Pasadena Pawn and Gun | https://www.pasadenapawnandgun.com/antique-guns | Pawn shop; inventory may turn over fast and unpredictably |

#### Group Z — refused a plain request

Neither could be identified without a browser, which is itself the finding.

| Site | Entry URL | What happened |
| --- | --- | --- |
| Liberty Tree Collectors | https://www.libertytreecollectors.com/Rifles-C&R-c179758763 | 403. Note the literal `&` in that URL |
| Fernwood Armory | https://www.fernwoodarmory.com/militarysurplus.html | 403 behind Cloudflare. Static HTML underneath, so likely similar in shape to Empire Arms |

#### Group F — built

| Site | Entry URL | Platform | Status |
| --- | --- | --- | --- |
| Royal Tiger Imports | https://royaltigerimports.com/ | WooCommerce / Elementor | **Built** — browser-driven; infinite scroll, Load More and pagination |
| Empire Arms | https://www.empirearms.com/ | Static HTML | **Built** — two catalog pages |
| [Hunter's Lodge](https://www.hunterslodge.com/) | https://www.hunterslodge.com/ | Scanned flyer image | **Built** — OCR; see below |

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

### Calibers as a managed list, like makers

**Planned.** Calibers are still a tuple of regular expressions in
`app/services/classify.py`, which is where the maker list started before it
became a table with an admin page. The same argument applies, and more sharply:
a cartridge has one name that collectors use and several that vendors write, and
which one is the "real" one is a judgement about the market rather than about
code.

The shape is the one `manufacturers` and `manufacturer_models` already have:

- A **display name** — what the filter shows and what a listing is filed under.
  "7.62 NATO", or "6.5 Swedish".
- **Aliases** underneath it, one per line, for what vendors actually write:
  "7.62x51mm", "7.62x51", ".308 Winchester" under the first; "6.5x55mm",
  "6.5x55 Swedish", "6.5x55 Mauser" under the second. Matched as literal text
  on word boundaries, never as patterns, because they come from a form.
- Editable from the admin pages, with the edit **re-filing every listing it
  reaches** and saying how many moved — the manufacturers page already works
  this way and the machinery is shared.
- Seeded from `CALIBER_NORMALIZATIONS`, exactly as the maker table was seeded
  from `MANUFACTURER_PATTERNS`, so nothing is lost and the first edit can be
  made from the UI.

**What this fixes beyond tidiness.** The catalog currently files the same
cartridge under whatever each vendor calls it, so "7.62x51mm" and "7.62 NATO"
are two filter entries for one round, and neither shows the other's listings.
Today's caliber audit found the same thing at a smaller scale — `.25ACP` and
`6.35` are one cartridge, and only a rule in code could say so.

The bare-bore rules added since — a listing that says `.31` or `4.25mm` and
nothing more, which is how the whole percussion end of the catalog is written —
make this sharper still. Those produce an honest *number* because that is all
the listing gives, and a number is exactly what wants an alias: whoever runs the
site knows that a Colt M1877 Thunderer marked ".41" is .41 Colt, and no amount
of pattern-writing will.

**Two lessons from the maker work that carry over.** Order decides ties, so the
list needs a position column: a rule for ".38" must not be reached before
".380". And a caliber claimed by two display names identifies neither — the
manufacturers table already refuses to guess in that case, and this should too.

Worth doing before the market-pricing work below, which needs a stable caliber
identity to key against as much as it needs a stable model identity.

### Market pricing — "is this a good deal?"

**Planned.** The application can already say what a vendor is asking and how
that has moved. It cannot say whether the price is *good*, which is the question
somebody watching surplus actually has. The pieces:

1. **A reference source for realised prices.** Asking prices are what this
   application already collects, and they are not evidence: a rifle listed at
   $900 for eight months is not a $900 rifle. What is wanted is what things
   *sold* for — completed auction results. Candidates, in rough order of how
   usable they look:
   - **GunBroker** — the largest volume of completed sales in this market, and
     it has a real API. Terms and pricing need reading before anything is
     built; scraping the site instead is likely against its terms and would be
     the wrong way round when an API exists.
   - **Rock Island Auction, Morphy's, Amoskeag** — published results archives,
     smaller volume but skewed towards exactly the collector-grade surplus this
     application follows, and each result carries a condition description.
   - **Blue Book of Gun Values** — the reference dealers actually quote, but
     licensed and priced accordingly.
   Whatever is chosen gets a scraper like any other vendor, obeying robots.txt
   and its own crawl delay, into its own table rather than into `items`.

2. **Something to key the reference against.** This is the hard part and it is
   already underway: `manufacturers` and `manufacturer_models` exist, and the
   caliber work has shown how much of this is domain knowledge rather than
   parsing. A price for "Mosin-Nagant M44" means something; a price for
   "RUSSIAN M44 CARBINES good condition, cracked stock (toe)" does not until it
   has been reduced to a maker and a model.

3. **A distribution, not a number.** Condition dominates surplus prices — a
   matching-numbers rifle and a refurbished one are different objects at the
   same model number — so a single "book price" would be confidently wrong in
   the way this project keeps having to learn. Store the sold prices and quote
   a percentile: "asking less than 80% of recent sales of this model". With the
   condition grade as a second axis where the source supplies one.

4. **The UI.** A small distribution strip on the item detail page with the
   asking price marked on it — the reader can see both the spread and where
   this one sits, which a single "23% below book" cannot show. Then a **Good
   Deal** filter on the browse page, which is the whole point of the feature.

**What would make it dishonest, and must not be skipped.** A minimum sample
before any claim is made, the sample size shown next to the claim, and no
verdict at all for a model the reference has three sales of. The
caliber-to-maker inference in `crosscatalog.py` is the precedent: measured
against the real catalog, the obvious version of that filed thirty-two M1
Carbines under Marlin on the strength of three rows. The same trap is waiting
here, and it is worse, because a number with a currency symbol on it reads as a
fact.

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
