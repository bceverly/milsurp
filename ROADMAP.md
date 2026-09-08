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

**Where this stands: seventeen vendors read, thirteen queued, two dropped.**
Eight of the thirteen are blocked on something no base class can fix — a
Cloudflare challenge, two missing entry URLs, a shop that publishes no prices,
two that refuse a plain request, and two Wix pages that turn out to be photo
galleries rather than stores. They are not simply waiting their turn.

**The three most recent were added for their parts kits rather than their
guns**, which is a first for this list: Apex Gun Parts, Arms of America and
Bowman Arms. **None of them came out of the queue below** — they came out of
the parts-kit candidate list, which is why the queued count has not moved. See
**Parts kits as a coverage push** for what each was measured at and, in one
case, why a fourth was refused on measurement.

**Two of them left the queue without a browser being written.** J&G Sales and
SARCO were both filed under "needs a browser" on the same evidence — a catalog
page with no products in it — and both turned out to be publishing the whole
catalog as JSON to the widget that draws the grid. See `woo_store_api.py` and
`searchanise.py`. That leaves exactly one site waiting on Chrome, and it is a
Cloudflare challenge rather than a rendering problem.

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
| [IMA-USA](https://www.ima-usa.com/) | `ima-usa` | Shopify base class — `products.json`, no HTML parsing and no detail fetch |
| [Centerfire Systems](https://centerfiresystems.com/) | `centerfire-systems` | Shopify; three surplus collections out of a general retailer's catalog |
| [Classic Firearms](https://www.classicfirearms.com/) | `classic-firearms` | Magento base class — schema.org JSON-LD; facet-walked, because they disallow `?p=` |
| [J&G Sales](https://www.jgsales.com/) | `jg-sales` | WooCommerce **Store API** — the catalog as JSON, no browser and no detail fetch |
| [SARCO, Inc.](https://www.sarcoinc.com/) | `sarco` | Searchanise base class — the search widget's own JSON API, plus a product-page fetch for the description the API truncates |
| [Apex Gun Parts](https://www.apexgunparts.com/) | `apex-gun-parts` | Magento — ordinary pagination, because their robots.txt is empty. **Parts kits only; they sell no complete firearms** |
| [Arms of America](https://armsofamerica.com/) | `arms-of-america` | BigCommerce — their parts kits and their four Swiss C&R rifles; their modern AK builds are left alone |
| [Bowman Arms](https://bowmanarms.com/) | `bowman-arms` | BigCommerce — parts kits, which is all they list |

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

### Sold listings on BigCommerce — **Shipped**

Reported: a $1,095 Winchester titled "SOLD - Excellent Winchester Model 9410
Parker Compact" sitting in the Available section. The cause was wider than one
listing — **`bigcommerce.py` never set `is_sold` at all**, alone among the five
platform base classes, so all three shops on it read as fully in stock forever.
A sold listing's card in the grid looks exactly like an in-stock one; only the
product page says.

`bigcommerce.sold_out()` now reads two signals, because the shops split evenly
on which they publish:

| Signal | Legacy Collectibles | Bowman Arms | Arms of America |
| --- | --- | --- | --- |
| schema.org `availability` | 15 of 15 | 4 of 4 | **0 of 6** |
| Stencil `.alertBox--error` | yes (reads "SOLD") | — | yes |

The schema.org reader moved out of `magento.py` into `base.py` on the way —
`product_json_ld()`, `offer_of()`, `is_sold_out()`. It was never Magento's
idea; three of the four platforms here publish it.

**Measured over 52 product pages with both signals in place: 14 listings move
from available to sold and none the other way.** Six of seventeen Bowman kits,
five Arms of America kits, and three of thirteen Legacy listings — one of them
a $5,175 Atlas Gunworks the shop had renamed "SOLD - ..." *since it was last
read*, so nothing in the stored record gave any sign.

**The banner check is scoped to that element and must stay that way.** "Out of
stock" also appears in the theme's JSON configuration, in the option list of a
product whose *variants* differ in stock, and on every related-product card in
the page footer — an in-stock PPSh-41 kit at $599.99 carries the phrase five
times over.

Two things this leaves open. The **catalog grid** also labels an out-of-stock
card (`a.card-figcaption-button` reading "Out of stock" instead of "Add to
Cart"), which would let a re-scan notice a sale without fetching the product
page at all — worth doing, and not done. And a listing that sells **between**
scans of its site is still shown as available until the next one; that is true
of every vendor here and is a property of the scan interval, not of this fix.

### Legacy Collectibles' spec table — **Shipped**

Found by auditing every stored description after the Apex stylesheet bug. **All
258 Legacy Collectibles listings had no description at all**, and that was not a
scraper fault in the ordinary sense: they publish no prose. What they publish
instead is a specification table, and it is worth more than prose would be:

    Year: 1911-15   Maker: Mauser   Type: C96
    Caliber: 7.63mm Mauser   Bore: 9/10   Condition: ~94-95%

It is BigCommerce's stock **custom fields** feature — `table.productView-custom-fields`
— not one shop's theme, so reading it lives in `bigcommerce.py` and any shop on
the platform can claim it with a few lines. A subclass says which of its own
field names mean something here (`custom_field_map`), and only the four columns
a vendor can state are accepted: caliber, country, manufacturer, condition. A
shop that says nothing gets nothing guessed at.

**The fields are named rather than poured in as text, and that was measured.**
The first attempt fed the table to the classifier as a description: six of eight
listings gained a caliber and one **regressed** — a Magnum Research Desert Eagle
reported its manufacturer as "Luger", out of "Caliber: 9mm Luger". A stated
value outranks a derived one everywhere else in this application; naming the
field is what makes it stated.

**Measured on forty of their listings, against what was stored:**

| | |
| --- | --- |
| Gained a caliber | 17 |
| Gained a manufacturer | 13 |
| Gained a bore grade | 40 |
| Caliber corrected | 13 |
| Manufacturer corrected | 13 |
| Reclassified as a different kind | **0** |
| Lost a value it had | **0** |

The corrections are the interesting half. A Sig P320 and a Krieghoff Luger had
their manufacturer read as "Luger"; a Beretta Mod 96 was a Smith & Wesson
because it is chambered in .40 S&W; a Spanish Model 1893 was filed as 8mm Mauser
when it is 7x57; a Springfield M1A was .308 when its own title says 6.5
Creedmoor. Every one of those was the classifier doing its best with a title,
and every one is now the vendor simply saying so.

**The cost is spellings, and it is a real one.** They write "S&W", "6.5
Creedmore", "5.56x45" and "9mm Luger" where this catalog has settled on other
forms, so their listings propose those to the armory as calibers and makers to
approve or merge. That is what the armory's merge screens are for, and there is
no way to accept a vendor's stated value without accepting their spelling of it.

**The description is for the reader, not the classifier.** `description_from()`
restates the table as prose, and measured on the same forty it changes no
classification, matches no additional armory model, and gains one country. What
it carries that nothing else does is **Year** and **Type** — 1911-15, C96 —
which have no column and would otherwise never reach a detail page.

One thing left open: `condition` now holds two vocabularies. It is shown as
"Bore condition" and is not filtered on, so their "9/10" and "Like New" sit
happily beside the seven grades `BORE_GRADES` derives — but that has to be
settled before anything filters on it.

### Police surplus — **Planned**

Asked for directly, and it widens what this catalog is for. Departments
re-equip on a cycle and their old duty guns are sold on in lots: Glock 17s,
19s and 22s, S&W M&Ps, SIG P226s and P229s, Beretta 92s, and further back the
S&W Model 10, 64, 65 and 686 revolvers that preceded them. They are traded,
priced and watched much the way surplus military arms are — a department
trade-in Glock has a known street price that moves — and they turn up at the
same dealers, usually filed under a heading with the word "surplus" in it.

**The boundary is the same one the parts rule already draws, one category
over.** Police *gear* stays out: holsters, duty belts, vests, Tasers, radios.
Those are the water bottle in the Arms Unlimited section and the field gear in
a military surplus one — they turn over constantly, they swamp a listing count
and nobody is watching this application for a price drop on a duty belt. What
is wanted is the *firearms*.

**Arms Unlimited is worth reopening on this.** It was written, run and backed
out, and the note above says why: "their `/surplus/` section is police trade-in
gear — Tasers, holsters, a water bottle — and `/rifles/` is modern Colt M4s."
That judgment about the gear stands. Whether they also list trade-in *pistols*
was never checked, because the section was condemned as a whole. Re-measure it
before rebuilding: the scraper was a two-line BigCommerce subclass and restoring
it is cheap if the handguns are there.

**What has to change in the classifier, and it may be nothing.** A police
trade-in Glock reads as a handgun already — that is not the problem. The
problem is the opposite of the surplus rules' usual one: much of the existing
vocabulary exists to *reject* modern stock, because "not a surplus dealer" has
been the right call three times (Arms Unlimited, Legacy's Modern sections,
Centerfire's AR-15 collections). Police surplus is modern by definition, so the
distinction can no longer be "is it old" and has to become "is it *surplus*" —
which is a fact about the vendor's section, not about the gun. Read the
sections that say so and leave the rest, exactly as with parts kits.

Worth deciding before building: whether these want their own Type in the browse
filter, or simply sit among the handguns and rifles. They partition cleanly by
vendor section, so either is available.

#### Parts kits as a coverage push — **Mostly shipped**

That rule had been in this document since the beginning and **no scraper had
ever followed it.** Audited across the fourteen vendors read at the time: not
one named a parts-kit section in its `sources`. The 25 parts kits then in the
catalog were entirely incidental — 22 from Royal Tiger, whose scraper walks the
whole site rather than a list of categories, and 3 from `classify` recognizing
the word "kit" in a title that happened to arrive through a firearms section.

Both jobs below are now done for the vendors worth doing them for: two existing
shops gained a parts-kit section, and three new shops were added for their kits.
What remains is the long tail of candidate sites that each need their own build,
and the browse-filter question at the end.

So this is a real gap, and it is two jobs rather than one.

**1. Add the section to the vendors already read — done for two of the four,
and the other two were measured and refused.** Every section below was fetched
and run through `classify` before anything was added, which is the whole point
of the caution that follows:

| Vendor | Parts-kit section | Measured | Verdict |
| --- | --- | --- | --- |
| Centerfire Systems | `/collections/parts-kits-surplus-parts-kits` | 417 listings over two pages; 413 read as a kit, the other four being conversion and armorer's repair kits — FAL, AK, UZI, PPS43, MG42, Tavor | **Added, and scanned:** 417 new listings |
| CO Gun Sales | `/product-category/parts-accessories/parts-kits/` | 27 listings, of which a $9.99 cleaning kit, a $24.95 service kit and a gas block are not kits | **Added**, with the classifier taught to refuse those |
| SARCO | `Parts & Kits` (465) | Solenoids, feed trays, sears, extractors, springs, screws, rail covers | **Refused.** This is precisely the recoil-spring problem, at 465 items against a 2,446-listing catalog |
| SARCO | `Kits / Sets` (22) | Mixed: genuine 1911 builders kits beside spring sets and magazine pairs | Marginal; left out with the above |
| J&G Sales | category id **3773** | The section is real, five products deep, and returns none through the Store API today — as does their Military Mausers section, whose 56 are out of stock | **Added.** Costs one request; picks them up when they restock |

**Two things this cost, both worth writing down.** J&G answered 500 to
everything for a few minutes and the conclusion drawn was that their site was
down; it was a wobble behind their Cloudflare cache and the site was up in a
browser throughout. And their category list pages: reading the first 100 of 224
categories and concluding there was no parts-kit section was the same mistake
in a different shape. A negative from one request is not a negative.

Note the CO Gun Sales URL. The obvious `/product-category/parts-kits/` answers
200 with a page of sub-category *tiles* — "FAL Parts (23)", "Luger Parts (1)" —
and a dozen products among them; the full path under `parts-accessories` is the
real section. That is the MCT Defense trap in a shop that otherwise works.

The remaining ten answered 404 to the obvious URL, which is **not** evidence
they have no parts kits — it is evidence the guess was wrong. Their sections
have to be found from each site's own navigation before anything is concluded.

**The caution, and it is the whole difficulty — now enforced in code.** "Parts
kits" as a *vendor category name* is not the same thing as a parts kit. SARCO's
"Parts & Kits" is 465 items and most are single components; the ampersand is
doing the work.

`classify._is_a_parts_kit` no longer believes a section heading on its own: it
proposes, and the listing has to corroborate by saying "kit" somewhere of its
own. That is what separates a Royal Tiger ZB37 parts kit — which says so only
in its description — from the **M3 Tripod Mount** and the **Zeiss periscope**
filed beside it, both of which were parts kits until this existed. A cleaning,
service, repair or conversion kit is disqualified by name.

**2. Thirteen candidate sites, measured — and three of them are now shipped.**
Every URL below was fetched. The platform column is from response headers and
markup, not from the URL shape:

| Site | Entry URL | Platform | What the fetch showed |
| --- | --- | --- | --- |
| Apex Gun Parts | `/parts-kits.html` | Magento | **Shipped** (`apex-gun-parts`). A live run over five of their six pages: 98 listings, no warnings, 93 reading as kits and **a price on every one**. The five that miss are titled "Parts Set" or "Parts Selection" rather than "kit", which is the corroboration rule doing its job — Beretta M38/49 SMG, BGS FAL, Brazilian 1908 Mauser, Hotchkiss M1909 LMG, STEN Mk 3, C93, CETME C and L. Their "Rifles" and "Handguns" menus are *parts* sections, so there is nothing else here to take |
| Arms of America | `/all-products/parts-kits/` | BigCommerce | **Shipped** (`arms-of-america`). 47 listings on a full run, and every one lands where it should: 43 kits and the 4 Swiss C&R rifles, nothing miscategorized. PPSh-41 with drum, IWI UZI, Yugo M72B1 RPK, Polish Radom DPM and RPD, Sig STG 57, VZ61, G3/HK91. 25 of the 47 carry no price, which is BigCommerce hiding it on an out-of-stock product. Their modern AK builds are left alone |
| Bowman Arms | `/parts-kits/` | BigCommerce | **Shipped** (`bowman-arms`). 17 listings, all 17 reading as kits and all 17 priced — the only shop on this list where both are true. One product page (their Colt 653) answers 403 to every retry, so the run is PARTIAL with the catalog entry kept — Polish PM63 RAK, WZ.43/52, Yugoslav M56, Israeli FAL, Colt 653, G36 Schnittmodell, 1928 Thompson. No firearms section to leave out |
| Every Gun Part | `/parts-kits/` | BigCommerce | **Refused.** 177 listings and only nine name anything milsurp — and those nine are modern production (Springfield Armory 1911A1, ArmaLite AR10, Walther PPK). The rest is Del-Ton, Charter Arms, Röhm, Rock Island, Taurus, Ruger, Glock, SCCY, Bryco Jennings. A parts-kit section is not automatically a *surplus* parts-kit section |
| Centerfire Systems | `/collections/parts-kits-surplus-parts-kits` | Shopify | **Already a shipped vendor** — this is job 1 above, not a new site |
| Robert RTG | `/parts-kits` | Not identified | 200, 33 prices, 32 blocks. Renders server-side; needs its markup read |
| Proteus Armaments | `/partskits` | Not identified | 200, 18 prices, 18 blocks. Small |
| Atlantic Firearms | `/parts-kits` | PrestaShop | 200, 36 prices, 12 cards. Already queued in Group D as the most-visited site on the whole list; the parts-kit section is another reason to build it |
| Max Arms | `/product-category/parts-kits/` | WooCommerce | 200, 16 cards and **zero prices** — either client-side rendering or no prices published. Check the Store API first, the way J&G was settled |
| MCT Defense | `/product/military-surplus-parts-kits/` | WooCommerce | 200, 2 cards, zero prices. Note the URL is `/product/`, not `/product-category/` — this is one product page, not a section. Already in Group A as "needs an entry URL", and this does not supply one |
| Numrich (gunpartscorp) | `/category/gun-parts-kits` | Not identified | 200 but 2 prices and no cards — client-side. Look for the endpoint before concluding it needs a browser; that reading has now been wrong twice |
| What A Country | `/parts-kits.aspx` | ASP.NET | 200, 64 prices, no recognizable cards. A bespoke build, like eBayonet |
| APP Arms Co | `/product-category/parts-kits/` | — | **403 from nginx** to a plain request, 75KB of body. Not Cloudflare; some other block. Bottom of the list with DK Firearms |

**Suggested order**, cheapest first: the four existing vendors (job 1) — done —
then the three BigCommerce sites and Apex Gun Parts — done, less Every Gun Part,
which was refused on measurement — then Atlantic Firearms as part of building
that vendor properly. Robert RTG, Proteus, What A Country and Numrich are each
their own build. Max Arms and MCT need a question answered before they are worth
starting, and APP Arms Co is blocked.

**What the first Apex scan actually put in the database, and what it cost to
find.** 85 of their 102 listings arrived with a Magento Page Builder stylesheet
where their description should be. Two separate faults, both in shared code and
both older than this vendor:

- `get_text()` reads the text inside a `<style>` element out like any other
  text, and every platform here flattened descriptions that way. Fixed once,
  in `scrapers.base.flatten_html()`.
- That was not Apex's fault at all. Their schema.org `description` is Magento's
  *meta* description, generated from the Page Builder layout and truncated at
  120 characters, so it is the stylesheet with no `<style>` element anywhere
  near it — on every product they sell. The base class now tests the field with
  `is_prose()` and falls back to the markup selectors when it fails, keeping the
  price, availability, SKU and gallery the structured data gave. Apex's real
  description sits in an id with dots in it that no stock selector matches, so
  their scraper names it.

Fixing how a page is read does not fix the pages already read, because a scan
skips a product page it has already fetched. `make refetch-details` clears that
mark for the damaged listings; see the README.

**Two figures in the table above were wrong before they were measured
properly, both in the same direction.** Apex was recorded as "837 product
blocks in one 722KB page" from a loose grep of the markup; their own toolbar
says "Items 1 - 20 of 102", which is six pages of twenty, and
`product_list_limit=all` is a query string their robots.txt happens not to
forbid but which the ordinary "next" link makes unnecessary. Arms of America
was recorded at 86 cards and 82 prices; the section is one page of exactly 43
`article.card` elements with 43 distinct product links, and 25 of the 43 carry
no price at all. A grep over markup counts markup, not products; the only
honest count comes from running the scraper.

**One thing to settle before writing any of it**: the browse page currently
treats "Parts kits" as one of five Types. Thirteen dealers' worth of kits is a
different proposition from 25 — it is plausibly the largest category in the
application — and it is worth deciding whether a kit should be filterable by
the model it builds before there are thousands of them.

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
are ordered by judgment and are the ones to re-check before committing to an
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
| ~~1~~ | ~~J&G Sales~~ | — | **Shipped** | The HTML observation was right and the conclusion drawn from it was wrong. The catalog is rendered client-side, but the same WordPress install publishes the WooCommerce **Store API** — the whole catalog as JSON, with prices, stock, galleries and descriptions, and no browser. See `scrapers/woo_store_api.py`. The lesson is the one this section already draws about platform inference: what the HTML looks like is not what a site *is* |
| 2 | MCT Defense | `/product-category/firearms/` | **Needs an entry URL** | That page is thirty *category* tiles, not products — no price element anywhere on it. Their actual product pages have to be found before this is worth writing |
| **last** | DK Firearms | `/product-category/surplus/surplus-firearms/` | **Parked — Cloudflare** | Moved to the bottom of the list deliberately. Not a rendering problem and not a scraping problem: the site answers plain HTTP with a `cf-mitigated: challenge` interstitial, so what is being asked for is a way *around* a bot check the operator switched on. Everything else in the queue is a site that will simply answer. Revisit if they ever turn it off |

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
| **BigCommerce** | Legacy Collectibles, Arms of America, Bowman Arms, Arms Unlimited, Edelweiss Arms, SARCO | **Base class shipped** (`app/scrapers/bigcommerce.py`). Six sites, one platform, and the markup is close to WooCommerce's: `article.card`, an entity id per card, a "next" link. Two of these were in Group A on the URL guess. Of the six, four shipped — Arms of America and Bowman Arms arriving later from the parts-kit push, and each of them a subclass of four lines — one was dropped as out of scope, and one publishes no prices. SARCO is on the platform and is *not* read by this class: its grid is drawn by Searchanise, so it goes through `searchanise.py` instead — but the external keys are deliberately the same `bc-<id>`, so it could move here without arriving as a duplicate catalog |
| **Shopify** | IMA-USA, Centerfire Systems | **Both shipped** (`app/scrapers/shopify.py`). Cheapest per site, and the estimate held: structured JSON, no browser, no detail fetch. Centerfire had been filed as a one-off build on the URL guess |
| **Wix** | Surplus Defense, The Mosin Crate, Pasadena Pawn | Three, not one-offs. Wix renders client-side, so expect the browser path |
| **Magento** | Classic Firearms, Apex Gun Parts, ~~Century Arms~~ | **Base class shipped** (`app/scrapers/magento.py`), and two sites of the three kept. Classic Firearms was listed as Unknown until its markup was read: 59 `mage.` markers and a `/media/catalog/product/cache/` image path. It is the most-visited site on the list. Apex Gun Parts arrived later, from the parts-kit push, and is the one shop here that runs on the base class's **stock selectors unchanged** — the theme is plain `li.product-item`. Century Arms is dealer-only and was dropped |
| **Laravel (custom)** | AIM Surplus | `laravel_session`; a bespoke application, not BigCommerce |
| **PrestaShop** | Atlantic Firearms | The most-visited site on the list, and its own build |
| **OpenCart** | Joe Salter | `OCSESSID`; not Shift4Shop |
| **WooCommerce (blocked)** | DK Firearms, MCT Defense | See Group A. J&G Sales was here and shipped through the Store API |
| **Unknown** | Simpson Ltd | No marker in headers or cookies, and the home page answers with 2.8 KB — a splash or a client-side shell rather than a catalog. Needs a real entry URL before anything else can be said |
| **No platform at all** | eBayonet | Apache, hand-written pages saved from Microsoft Word, no `robots.txt`. Static HTML parsing, like Empire Arms |
| **Refused a plain request** | Liberty Tree (403), Fernwood Armory (403 + Cloudflare) | Not identified; both need the browser before anything else can be said |

#### Group B — BigCommerce · base class **shipped**

Four sites on the platform, and the shape is familiar: `article.card` per
product, a numeric entity id on the card, a price element, and a `rel="next"`
pagination link.

It did not pay off the way the count suggested — at first. Of the four, one
shipped, one was written and then dropped as out of scope, and the remaining two
were each blocked on something the platform has nothing to do with: a
client-side catalog and a shop that does not publish prices. The lesson recorded
here was that "four sites, one platform" counted sites rather than catalogs.

**It paid off later, from a direction this group did not list.** Arms of
America and Bowman Arms both came out of the parts-kit push, both are
BigCommerce, and each is a slug, a name and one or two URLs — no selector work
at all. So the base class is now four shipped sites rather than one, and the
right reading of the original lesson is narrower than it was written: counting
sites overstates what a *queue* is worth, but it does not overstate what a base
class is worth, because the class goes on being claimed by sites that were
never in the queue.

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
| — | **SARCO, Inc.** | Searchanise — Pistols, Shotgun, Shop All Firearms | **Shipped, and not on the base class this group is about.** The measurement that filed it here was right — zero cards and zero prices in 236 KB — and so was the platform: it *is* BigCommerce, and the product pages are ordinary Stencil. Only the catalog grid is client-side, drawn by a Searchanise widget from a public JSON API whose key the page carries in plain sight. 429 listings kept of 512 offered: 83 bare frames and stripped receivers are skipped as components, and the sections are read specific-first because the vendor's section name outranks the classifier — under the parent category 200 of their 283 pistols read as handguns, under "Pistols" 281 do. Their rifles live in a category called "Rifles \| Military Surplus Guns" and the pipe makes it unaskable, so those 75 come through the catch-all and are left to the classifier and the armory. See `scrapers/searchanise.py`, and the second finding under Group A about what an empty page does and does not prove |
| 1 | Edelweiss Arms | https://edelweissarms.com/antiques/long-guns/ | **Prices are not published.** Cards and titles parse; the price element is empty site-wide. Worth having for new-stock alerts, worth nothing for price tracking — decide before building |
| — | ~~Arms Unlimited~~ | — | **Dropped: not a surplus dealer.** Written, run against the live site, and backed out. Their `/surplus/` section is police trade-in gear — Tasers, holsters, a water bottle — and `/rifles/` is modern Colt M4s. 97 listings landed correctly and none of them belonged in this catalog. The scraper was a two-line subclass; restoring it is easy if modern stock is ever wanted |

#### Group C — Shopify · base class **shipped**

The cheapest group by a distance, and the only one whose estimate held up.
`/collections/<handle>/products.json` returns the numeric product id, the
title, the price, availability, the SKU, the full gallery at original
resolution and the description — so `app/scrapers/shopify.py` does **no HTML
parsing and no per-listing detail fetch at all**. That second point is the win:
the detail fetch is where every other scraper spends its time, and a collection
of two hundred products is one request here.

Measured on the live sites before writing anything, because the two rules that
have caught this project out both applied:

- **Pagination is `?limit=250&page=N`,** and a query string is exactly what
  ruled out the WooCommerce Store API — Collectors Firearms disallows `/*?*`.
  Both of these shops allow it, and neither publishes a `Crawl-delay`. The walk
  still asks robots.txt before each page.
- **The catalog has to be scoped to collections.** Centerfire's unscoped
  `/products.json` opens with Browning hunting ammunition, and their two
  largest collections are 455 AR-15 rifles and 288 AR-15 pistols. That is the
  Arms Unlimited mistake waiting to be made a third time.

| # | Site | Collections read | Status |
| --- | --- | --- | --- |
| — | **IMA-USA** | `original-antique-guns`, `collectible-antique-guns`, `antique-long-guns`, `antique-handguns`, `garand-u-s-rifles` | **Shipped.** 197 listings from the first collection alone, every one with a price, a gallery (21–27 photographs) and a description. `/collections/all` is 2,898 items including gun parts and holsters, so it is not read |
| — | **Centerfire Systems** | `c-r-eligible` (360), `firearms-classic-firearms-military` (147), `firearms-certified-used` (25) | **Shipped.** A general retailer with a genuine surplus section. Sold-out listings keep their price, which is what tells "sold" apart from "call for price" |

#### Group D — one site each

Each of these is its own build, so weigh it on its own merits. Atlantic Firearms
is the most-visited site on the whole list and is worth building despite that.

| # | Site | Entry URL | Platform | Audience signal | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Atlantic Firearms | https://atlanticfirearms.com/military-surplus | PrestaShop | ~837K visits/mo (Similarweb, Aug 2024) | The most-visited here. Big surplus section |
| — | ~~Classic Firearms~~ | — | **Magento** | 1.6M visits/3mo (Similarweb, Jul 2026) | **Shipped.** Moved to Group G |
| 3 | AIM Surplus | https://aimsurplus.com/categories/firearm/curio-and-relic | Laravel | ~357K visits/mo (Semrush, Apr 2026) | Bespoke application. An earlier list guessed BigCommerce from the URL shape; the cookies say otherwise |
| — | ~~Century Arms~~ | — | Magento | Importer, widely stocked by the others | **Dropped: dealer-only prices.** See Group G |
| 5 | Joe Salter | https://shop.joesalter.com/CandR-Firearms-curio-and-relic-handguns-rifles | OpenCart | Long-established collector dealer | Not Shift4Shop, which the `-cNNNNNNNNN` URL suffix suggested |
| 6 | Simpson Ltd. | https://www.simpsonltd.com/ | Unknown | Trading since 1962 | **Needs an entry URL.** The home page is 2.8 KB with no platform marker; whatever the catalog is, it is not there |
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

#### Group G — Magento · base class **shipped**

Two sites, one platform, and one of them is the most-visited on the whole list.
That was the argument for building it, and the last of those arguments
available: everything remaining is one site each. In the event only one of the
two was worth keeping — which is the argument's weakness stated plainly, since
it counts sites rather than catalogs.

**The base class then paid for itself somewhere the group never anticipated.**
Apex Gun Parts came out of the parts-kit push, not out of this group, and it is
seven lines: a slug, a name, a URL and one source. Their theme is stock
`li.product-item` with a stock "next" link, so none of the selectors below need
overriding, and their robots.txt is served empty — so unlike Classic Firearms
they permit `?p=N` and the facet walk is not needed. Six pages, 102 listings.
That is the second time a base class built for one group has been claimed by a
site from outside it, after BigCommerce.

They are the WooCommerce situation exactly — the same platform underneath, different theme classes on top:

| | Classic Firearms | Century Arms |
| --- | --- | --- |
| Cards | `.products-grid .item` (custom `product-card` theme) | `li.product-item` (stock Magento) |
| Per page | 24 | 20 |
| Pagination | `?p=N` | `?p=N` |
| Images | `/media/catalog/product/cache/…` | same |

So: a base class with overridable selectors, the fourth time that shape has
paid.

**The catch, and it is a real one. Classic Firearms disallows its own
pagination.** Their robots.txt carries `Disallow: /*?p=` with an `Allow:` only
for `/news`, so page 2 of a category is off limits — 24 listings per section is
all the category pages can honestly give. Three routes past it were checked:

- `?product_list_limit=96` **is** allowed by robots, and is **not honored** by
  the site: it returns 24 cards either way. Dead end.
- Their sitemap index is declared in robots.txt and product pages are allowed,
  including `sitemap_longguns.xml.gz`, `sitemap_handguns.xml.gz` and
  `sitemap_firearms.xml.gz`. The sanctioned route to the whole catalog, at one
  request per product and a mixed bag to filter, since those files carry modern
  AR-15s alongside the surplus.
- **Better than either, and the next thing to do for this site: their caliber
  facets are paths, not query strings.**
  `/firearms/rifles/military-surplus/30_06/` is 19 rifles and needs no query
  string at all, so it is allowed as it stands. Walking those would reach most
  of the catalog well within the rules and at a fraction of the sitemap's cost.

Century Arms allowed `?p=` and needed none of this, which was the argument for
pairing them. It was dropped for an unrelated reason; see below.

| # | Site | Sections read | Status |
| --- | --- | --- | --- |
| — | **Classic Firearms** | `/firearms/rifles/military-surplus/`, `/firearms/handguns/military-surplus/`, `/firearms/c-and-r-eligible/` | **Shipped, facet-walked.** Their robots.txt bars `?p=`, so each section is read one caliber facet at a time. A live run returned **122 listings from the rifle section** rather than the 24 a single page can show — every one with a price, a gallery and a description, all from their JSON-LD |
| — | **Apex Gun Parts** | `/parts-kits.html` | **Shipped, and not from this group.** Added by the parts-kit push; the base class took it with no selector overrides at all. Their robots.txt is served empty, so ordinary `?p=N` pagination is permitted and the facet walk is not needed. Six pages, 102 listings |
| — | ~~Century Arms~~ | `/surplus-corner/firearms` | **Dropped: dealer-only.** Written, run against the live site, and backed out — the same call as Arms Unlimited, for a different reason. Seventeen of the first twenty listings have no public price and about fifteen are modern commercial stock. Its 31 listings were deleted from the database |

**What reading the cards changed.** This group was recommended as "two sites,
one platform, and one of them is the most-visited on the list". Half of that
survived contact:

- **Classic Firearms is everything hoped for.** Their product pages carry
  schema.org `Product` JSON-LD — name, SKU, price, availability, description and
  original-resolution images — so the base class reads structured data first and
  the markup only as a fallback. That is the opposite of the other three base
  classes and is the right way round wherever a shop publishes it.
- **Century Arms turned out not to be worth having, and was removed.** Of the
  first twenty listings, seventeen say "DEALER LOGIN REQUIRED TO PURCHASE"
  where a price would be, and roughly fifteen are modern commercial stock —
  Antonio Zoli over-unders, an Armalite M15, a row of Arminius .38 revolvers.
  The three with prices are the three that are genuinely old. It was built,
  scanned once, and then the scraper and its 31 listings were deleted.

  Being on a platform already supported is a statement about cost, not value.
  This is the third time — Arms Unlimited, Edelweiss Arms, Century Arms — so
  the check is now written into the README: read twenty cards and count how
  many carry a price and how many are surplus, *before* writing the subclass.

**Three things the build cost, worth not repeating.**

1. **Guessing category URLs cost two 404s.** `/firearms/curio-relic/` and
   `/firearms/handguns/surplus-handguns/` are the obvious names for those
   sections and neither exists. The real ones are in the site's own navigation.
2. **The obvious external key was the wrong one.** Classic Firearms' cards carry
   a `data-product-id` — on a financing widget that appears on in-stock products
   and not on sold-out ones. Keying on it would have made a rifle selling out
   look like one listing de-listed and a different one arriving. Only Magento's
   own `product-item-info_<n>` wrapper counts.
3. **Their cents live in their own element.** `$1599<span
   class="decimal">99</span>` reads as "$1599 99" and parses to $1599.00, while
   the JSON-LD says 1599.99 — a phantom price change on every re-scan that
   skipped the detail fetch. Removing the cents by *text* is the trap after
   that: "$1599 99" minus the first "99" is "$15 9", which parses to $15.99.

#### Group E — Wix · **not a group**

Filed as three sites on one platform needing the browser. Measured, it is one
site worth having, and no browser is needed for it.

**The browser part was wrong.** Wix renders client-side, which is true of the
*rendering* and not of the data: a Wix Stores page embeds its whole catalog as
JSON in the HTML for search engines. Surplus Defense's `/all-products` carries
a `productsWithMetaData` blob with the product id, name, price, SKU,
`isInStock`, a "SOLD" ribbon, the URL slug and the media URLs — 20 products of
a stated `totalCount` of 58, so it pages, but plain HTTP reaches all of it.

**The group part was wrong too.** Being on Wix says nothing about having a
shop:

| Site | What it actually is |
| --- | --- |
| **Surplus Defense** | A real Wix Store. Embedded catalog JSON, 58 products, genuine surplus — a Krag-Jorgensen and a Type 14 Nambu holster on the first page. **Worth building** |
| The Mosin Crate | `/shop-1` is a Wix Pro Gallery, not a store: 71 dollar amounts on the page and the first is the shipping table. No catalog blob |
| Pasadena Pawn and Gun | Also a Pro Gallery, and the prices are **in the image filenames** — `Savage Model 1899 Takedown Rifle – .300 Savage - Frank 30__$975__.jpg`. No product ids, no stock, no product pages. Their navigation is Glock, Taurus, Canik and Sig, so it is a modern shop besides |

#### Browser-backed fetching — no longer the leverage it looked like

This section used to name three sites blocked on the *same missing piece*, and
call building it the best remaining work. Two of the three have since shipped
with no browser involved, which is worth recording as a finding rather than
quietly editing away.

| Site | What was said | What was true |
| --- | --- | --- |
| J&G Sales | Catalog rendered client-side | It is. The same WordPress install publishes the WooCommerce Store API — the whole catalog as JSON. **Shipped** |
| SARCO, Inc. | Catalog rendered client-side | It is. The Searchanise widget that draws the grid reads a public JSON API, key in the page source. 429 of its 512 firearms, in nine requests. **Shipped** |
| DK Firearms | Cloudflare answers plain HTTP with 403 | Still true, and still the last item on the list |

**The finding: "the catalog is not in the HTML" says nothing about whether a
browser is needed.** A client-side grid has to get its products from
*somewhere*, and that somewhere is an HTTP endpoint the page itself will tell
you about. Both of these took under an hour to find — a `grep` for the widget
script, and one request to the API it names — against an estimated multi-day
build for browser-backed fetching. **Look for the endpoint before reaching for
Chrome.**

What is left, then, is not a mechanism blocking three sites. It is one site,
and a browser may not unblock it: DK Firearms is a Cloudflare challenge rather
than a rendering problem, and headless Chrome does not reliably pass one.
Getting past it is bot-check circumvention rather than scraping, which is why
it now sits at the bottom of Group A rather than at the top of a plan. The
Wix sites need no browser either (Group E), and Royal Tiger — the one site that
genuinely does — already has `app/scrapers/browser.py` to itself.

Build browser-backed `get_text()` when a site turns up that actually needs it.
Right now none does.

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
- **Shipped** — Accessory-versus-firearm classification, twice reworked against
  the site owner's own reports. First pass: forty-two IMA-USA slings, bayonets,
  cases, cheek pads, oilers, wire hangers, cartridge belts and one film-prop
  en-bloc clip were arriving as rifles, because those dealers name the gun a
  part fits before naming the part and file the whole lot under "M1 Garand &
  U.S. Rifles". Second pass, the mirror image: eighty-six genuine firearms were
  sitting in "Other parts & accessories" — a $39,995 pair of flintlock holster
  pistols, a $29,995 drilling, Walther, Glock, SCAR, Galil, CETME, M1A and
  Winchester listings — because a collector's dealer names the model and stops,
  or names the gun and then everything it is made of. Both halves pull against
  each other, so every rule is measured over all 1,930 stored listings before it
  is kept and 77 of the reported titles are now test cases. See the head-noun
  and specification rules in the README.
  A third pass cleared the last ten: deactivated and display pieces (an inert
  M2HB, a non-firing training rifle, a scale replica revolver), goods named
  beside a gun rather than instead of one (a revolver "As Featured In … Firearms
  Book", a pistol with a "Butt Cap", a machine gun on its tripod), a
  "Percussion Pistol Carbine" in .58 that the caliber rule turned into neither,
  and a Beretta whose model the vocabulary only recognized without the word
  "Model" in the middle.
  A fourth pass, from the same source, cleared two more: a Beretta whose extras
  were bundled with a "+" rather than a "with", and a Smith & Wesson written as
  a dash-separated spec list whose third entry was its grips. `make reclassify`
  now also applies the reference catalog, which it did not — so promoting a
  model taught every future scan something that reclassify then quietly undid
  on the listings already stored. Its summary line also counted "other" as
  everything that is not a rifle or a handgun, which silently included the
  bayonets and parts kits printed beneath it: it read 131 against a filter
  showing 88.
- **Shipped** — A count beside each Type in the filter rail, and the total
  beside "Anything". Counted over every other filter but not over Type, so the
  numbers say what choosing one would give rather than restating the choice
  already made.
- **Shipped** — An armory of manufacturers, models and calibers (`/armory`), which
  is the first thing in the application that states facts rather than guessing
  at them. Calibers carry every spelling the trade uses, so ".32 ACP" and
  "7.65mm Browning" are one row and one filter. Models carry their aliases,
  their kind, and *all* of their makers and *all* of their calibers — the M1
  Carbine had nine makers, and a Steyr M95 is 8x50mmR or 8x56mmR depending on
  when it was rebarreled. Both are join tables, which is why there is one M1
  Carbine rather than nine. With exactly one maker or caliber the catalog fills
  a listing's blank from it; with several it says nothing, because it does not
  know which this one is. Kind is finer than the browse filter: rifle, carbine,
  shotgun, pistol, revolver, each also in flintlock and percussion, because a
  Trapdoor Carbine and a Trapdoor Rifle are different guns. Every row is
  awaiting-approval or production and only production rows decide anything,
  which is what would make it safe for a scan to write down every designation
  it meets — see the discovery item below, which is still not wired up. Merging folds
  "Mosin" into "Mosin-Nagant", carrying the spellings across and restamping the
  listings. The catalog seeds from a versioned file, exports back to one, and
  syncs with a plan-then-apply flow.
- **Shipped** — The maker list folded into it as a third tab. It was a page of
  its own where each firm carried a flat textbox of model names, which could
  only say "this firm made something called M44" — so a designation two firms
  both made had to be dropped from maker-matching, because a list per firm
  cannot express one thing built by two. Maker rules now read the armory's
  models: one with exactly one maker names that maker, one with nine names
  none. Expanding a firm shows what it built, with "+ Add model" pre-checking
  it, and a cartridge can be added without leaving the model dialog. The two
  registries are one cache now — the maker rules depend on the armory, so
  promoting a model has to clear both, and not doing so meant promoting
  "Inland" left "Inland M1 Carbine" with no maker and nothing to explain it.
  Not called "Registry", deliberately: in the US firearms world that word means
  a government list of owners.
- **Shipped** — A listing records which armory model it matched (migration
  0012, a foreign key rather than a copy of the name), the browse rail offers a
  Model filter, and the detail view names the model with its kind and a
  reference link. 592 of 1,994 listings name one. Models are matched from the
  title only: reading descriptions gave sixty-three listings the Walther PP,
  a third of them CZ pistols described as copies of it and one of them a box of
  ammunition listing what it suits.
- **Shipped** — A model carries its **country of origin** (migration 0013),
  seeded for all 57 shipped models and filled into any listing whose own text
  names no country. That was the commonest blank left: the classifier reads
  "RUSSIAN M44 CARBINES" and "SWEDISH MAUSER M96" perfectly well and has
  nothing to say about "M1 Garand, EXC, all matching". Origin of the *pattern*,
  not provenance of the gun — a Mosin-Nagant is Russian however many Finland
  rebuilt — so the fill is one-directional and a listing that states a country
  keeps what it states. Unlike the maker it is never a choice: all nine firms
  that built the M1 Carbine built an American carbine, so a model can state the
  country even where it cannot name a maker. The admin box suggests the
  classifier's own spellings, because both answers land in the same column and
  a model recorded as "USSR" against listings read as "Russia" would split one
  country into two half-empty filters.
- **Planned** — Filter the browse page by the finer kinds (flintlock pistol,
  percussion carbine). The data is there through the model link; only the
  reading of it is missing.
- **Shipped** — The armory fills its own queue. Every scan ends by reading the
  listings it just stored and proposing the cartridges, firms and designations
  the table cannot explain (`services/discovery.py`); `make armory-discover`
  does the same over a whole catalog. Measured over 2,014 listings: 287 models,
  57 calibers, 20 manufacturers. Everything arrives pending, so nothing it
  writes can change what a scan decides about a listing.
  The design problem was never recall, it was junk — a queue nobody reads is
  worse than no queue — so each rule was measured before it was kept and each
  is narrower than the obvious one. Calibers come from the classifier's own
  reading, which already had to look like a cartridge. Models come from
  designation *shapes* and only from listings that are firearms and that the
  armory cannot already match; parentheses are stripped first, because that is
  where vendors put lot codes and every one of those has a designation's shape.
  Makers are the weak case: a firm's name has no shape, only a position (the
  words before a designation), so a candidate must be seen in two different
  listings before it is written down. A leading-capitals rule was tried first
  and measured at about half junk — "U.S.", "Ben's", "Vietnam Bring-Back
  Chinese".
  Two bugs fell out of building it, both latent for as long as the propose
  functions had existed: the session runs with `autoflush=False`, so proposing
  the same name twice without a commit added two rows and died on the UNIQUE
  constraint at flush — every earlier test committed in between, which is
  exactly why nothing caught it. And a maker propose path did not exist at all.
- **Shipped** — A fifth pass of misclassification reports from the site's
  owner, twenty-eight listings, and two causes. Most had **no rule fire at
  all**: a surplus title is often a maker, a designation and a caliber with no
  gun noun, so a generic "firearms" category is now read as a last resort and
  the caliber decides the kind. The rest were complete firearms carrying an
  accessory word — a barrel count ("SINGLE BARREL"), a missing bolt ("No
  Bolt"), an engraved slide, or a maker whose surname is a gun part ("FRANZ
  STOCK"). A category that is *only* a type word now outranks the accessory
  veto, unlike a collection like "M1 Garand & U.S. Rifles". 33 listings moved,
  29 of them the reported ones and the other four correct.
  A parts kit no longer counts as a firearm as well, and a **cut-up receiver is
  a parts kit** whatever the ATF calls it. That last rule was written twice: a
  bare "cut receiver" pattern took the JRA BM-59 and BM-62, which are built on
  a *billet cut* receiver — freshly machined, the opposite of demilled.
- **Shipped** — The armory curated end to end: 53 merges, 108 fills and 46
  designations disabled. Models carrying a kind went 51 → 159 and a country
  56 → 164; listings pointing at a model that could not say what it was fell
  **745 → 78**. The Lee-Enfields alone had been written six ways by five
  dealers. The disabled rows are the interesting half — `M16` was matching
  French Berthier carbines in 8mm Lebel, `Model 1911` the Colt automatic and
  the Schmidt-Rubin rifle — and they are turned off with a note rather than
  deleted, so the judgment survives a re-seed.
  Two bugs fell out of doing it. Six Zastava M83s titled ".357 Magnum" were
  stored as .38 Special, because the caliber extractor pooled title and
  description and let the *order of the table* decide; the title now wins, and
  68 listings were corrected. And `merge_models` was dropping the `country` of
  the row it folded away — missed when that column was added.
- **Planned** — Two caliber patterns that are wrong in the same way: a bare
  `8mm` claims "8mm Mauser" ahead of "8mm Lebel", and `7.65mm` claims ".32 ACP"
  where a Luger means 7.65 Parabellum. Both surfaced while measuring whether a
  title's stated caliber should outrank `MODEL_CALIBERS` — which it should, and
  cannot until these are fixed, because today that change is a wash.
- **Planned** — Better maker candidates. Two in three is a usable queue and not
  a good one. The obvious next signal is the description rather than the title,
  and the obvious risk is the one that made model matching title-only: prose
  names other people's guns.
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
which one is the "real" one is a judgment about the market rather than about
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
- **Shipped** — The photo SSRF guard tells a private address from a resolver
  that gave up. Both used to be reported as "not a public HTTP(S) URL" and both
  counted against a photograph's retry budget; one SARCO scan refused 151
  perfectly good CDN images that way, because the guard resolved every photo URL
  separately and the resolver buckled under four hundred lookups of one name.
  Resolutions are cached per host, and only successes are cached.
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
