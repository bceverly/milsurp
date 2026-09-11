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

**Where this stands: twenty-six vendors read, four queued, four dropped.**
Eight of the thirteen are blocked on something no base class can fix — a
Cloudflare challenge, two missing entry URLs, a shop that publishes no prices,
two that refuse a plain request, and two Wix pages that turn out to be photo
galleries rather than stores. They are not simply waiting their turn.

**The three most recent were added for their parts kits rather than their
guns**, which is a first for this list: Apex Gun Parts, Arms of America and
Bowman Arms. **None of them came out of the queue below** — they came out of
the parts-kit candidate list, which is why the queued count has not moved. See
**Parts kits as a coverage push** for what each was measured at and, in one
case, why one of them was refused on measurement.

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
| [Legacy Collectibles](https://www.legacy-collectibles.com/) | `legacy-collectibles` | BigCommerce base class — `article.card`, `data-entity-id`, query-string pagination. Their spec table supplies the caliber, maker and bore grade; 1,001 listings |
| [IMA-USA](https://www.ima-usa.com/) | `ima-usa` | Shopify base class — `products.json`, no HTML parsing and no detail fetch |
| [Centerfire Systems](https://centerfiresystems.com/) | `centerfire-systems` | Shopify; three surplus collections out of a general retailer's catalog |
| [Classic Firearms](https://www.classicfirearms.com/) | `classic-firearms` | Magento base class — schema.org JSON-LD; facet-walked, because they disallow `?p=` |
| [J&G Sales](https://www.jgsales.com/) | `jg-sales` | WooCommerce **Store API** — the catalog as JSON, no browser and no detail fetch |
| [SARCO, Inc.](https://www.sarcoinc.com/) | `sarco` | Searchanise base class — the search widget's own JSON API, plus a product-page fetch for the description the API truncates |
| [Apex Gun Parts](https://www.apexgunparts.com/) | `apex-gun-parts` | Magento — ordinary pagination, because their robots.txt is empty. **Parts kits only; they sell no complete firearms** |
| [Arms of America](https://armsofamerica.com/) | `arms-of-america` | BigCommerce — their parts kits and their four Swiss C&R rifles; their modern AK builds are left alone |
| [Bowman Arms](https://bowmanarms.com/) | `bowman-arms` | BigCommerce — parts kits, which is all they list |
| [DuPage Trading](https://dupagetrading.com/) | `dupage-trading` | BigCommerce — 20 bayonets and 3 WWII rifles; their grid renders each product twice |
| [Atlantic Firearms](https://www.atlanticfirearms.com/) | `atlantic-firearms` | PrestaShop base class — three of their nine sections; the other six are gear and modern builds |
| [Recoil Gun Works](https://www.recoilgunworks.com/) | `recoil-gun-works` | BigCommerce — 229 police trade-ins across pistols, rifles and shotguns, every one priced |
| [Officer Store](https://officerstore.com/) | `officer-store` | BigCommerce — 13 LE trade-in Glocks, graded by condition |
| [Arms Unlimited](https://armsunlimited.com/) | `arms-unlimited` | BigCommerce — 20 used and collectible, twelve of them military; their gear and current-production sections are not read |
| [AIM Surplus](https://aimsurplus.com/) | `aim-surplus` | Its own JSON API — 162 police trade-ins and 18 curio-and-relic, all priced; the largest *live* police catalog here |
| [eBayonet](https://www.ebayonet.com/) | `ebayonet` | **No platform at all** — five Word-exported pages, prices and photographs typed into the prose |
| [Surplus Defense](https://www.surplusdefense.com/) | `surplus-defense` | **Wix Stores base class** — 45 listings and every one collector milsurp |
| [Joe Salter](https://shop.joesalter.com/) | `joe-salter` | **OpenCart** — 320 collector listings, every one priced; **no photographs, because their robots.txt disallows `/image`** |

### Planned

**This list is now also in the application.** `app/scrapers/planned.py` carries
the four vendors still queued, and the Sites page shows them under **Coming
soon** with what each is waiting on. It is deliberately narrower than this
section: only vendors that are still going to be built, never one that was
measured and refused — Impact Guns, USA Gun Shop, Edelweiss Arms, The Mosin
Crate, Century Arms — because listing a refusal as "coming soon" quietly
reverses it. `backend/tests/test_planned_sites.py` fails if a planned vendor
gains a scraper, so a shipped site cannot go on promising itself.

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

### The source-list audit — **Shipped**

Legacy Collectibles was being read at 13% and nobody noticed for weeks, so the
same question was put to every other vendor: **does this shop's own navigation
call something a catalog that we are not reading?** Every site's category list
was fetched and every candidate section was counted before anything was
changed.

Five shops were under-read, and the misses were not marginal:

| Vendor | Was | Now | What was missing |
| --- | --- | --- | --- |
| **Collectors Firearms** | 218 | **691** | US Model 1861 and 1842 muskets, a B.S.A. Snider, a Spandau 1871/84, a Vetterli-Carcano, a Type 14 Nambu, an Astra 600/43, Mauser S/42 Lugers, a C96 flatside, a byf 44 P.38 |
| **Ancestry Guns** | 12 | **36** | A Gustave Young-engraved Colt M1849, a Civil War surgeon's M1860 Army, a Confederate 3rd Model Dragoon, a Sharps U.S. Navy M1855, an 1866 Winchester musket, a Brown Bess |
| **CO Gun Sales** | 171 | **218** | Snider-Enfield Mk II\*\*, Schmidt-Rubin 1889, a Swiss Modell 1842/59, two W+F Bern cadet rifles, a Whitney breech-loading carbine |
| **J&G Sales** | — | **+12** | A Swiss K11, a Carcano M.91 cavalry carbine, a Yugo M57 Tokarev, an Arisaka Type 38 trainer, three Springfield 1903s, a Krag, an Izhevsk 91/30 |
| **Checkpoint Charlie's** | 163 | **349** | A Winchester Hotchkiss 1879 carbine, a Quality Hardware M1 Carbine, a Krieghoff Luftwaffe flare pistol, Allen & Wheelock and Remington derringers |

Axis Arms gained their Curio & Relic section, which held one listing the other
two did not.

Checkpoint Charlie's is the one that needed a second look at *why*: they were
read through `/product-tag/cr/`, and C&R eligibility is a legal fact about a
gun's age rather than a claim the shop makes about every old gun it stocks. 186
of the 264 listings in their military and antique leaves carry no such tag.
**A tag is a filter, not a catalog.**

**Five shops were checked and needed nothing**, which is worth recording so the
work is not repeated: IMA-USA (the five collections read cover 272 products and
every other antique-firearm collection adds nine), Centerfire Systems (their
other firearm collections are AK, AR, 1911 and shotgun), Classic Firearms
(`/firearms/` has one C&R and two military-surplus leaves and this reads all
three), SARCO and Apex Gun Parts.

**The lesson, three times over.** Each miss came from taking one thing a shop
said about itself and stopping there. On Collectors Firearms a parent category is
a page of **sub-category tiles with no products on it at all** — the MCT
Defense trap recorded elsewhere in this document — so "Antique Handguns" looked
like a section and was a menu; the two leaves under it are 74 listings. On
Ancestry Guns the three sections have **no product in common**, so "Curio &
Relic" being the C&R section did not make it the catalog. And Checkpoint Charlie's were read through a *tag*, which is a filter over a
catalog and not the catalog. *Open every parent before judging it, check
whether sections overlap before assuming one contains another, and do not
mistake a filter for a catalog.*

**What it costs.** Collectors Firearms ask for a 10-second crawl delay and get
**30** — their limiter refuses 10, and refused 20 as well once this scraper grew
from two sections to nine — so their 473 new listings are something over three
hours of first-scan wall clock, paid once. The others are minutes —
Checkpoint Charlie's especially, whose product pages refuse every request
anyway, so a section there costs its category pages and nothing more.

**A browser would not help here, and it is the obvious next idea.** This is
rate limiting rather than bot detection: they answer plain requests perfectly
well, they just will not answer that many. Headless Chrome makes *more*
requests per page — stylesheets, scripts, fonts, images — so it would reach the
limit sooner and pay Chrome's overhead to do it. What would genuinely reduce
the count is their sitemap, which robots.txt declares and which would replace
the ~70 category-page fetches; that is worth doing and is not done.

**Collectors Firearms moved to a fortnightly scan** because of it. Their
default was daily, which was defensible for two sections and is not for nine:
even a later pass, where every product page has already been read, is ~70
catalog pages at twenty seconds each. Antique and collector stock does not turn
over in a day. That needed a new cadence on the site list, which stopped at
weekly — it is spelled **"Every 2 weeks"** and not "biweekly", because that
word means both "every two weeks" and "twice a week".

#### "Unchanged" is not "already read" — **Fixed**

The category sitemap saves a section whose `lastmod` predates our last
successful scan. On 9 Sep that skipped **U.S. Military Antique Long Guns**, and
it was right about the fact and wrong about what to do with it: the section was
unchanged, and it was also 132 listings this scraper had never opened, because
it was one of the seven sections added *after* the last successful scan.

The trap closes permanently. A section nobody reads never changes either, so it
would have been skipped again on every run from then on — and five more of the
new sections (Military Handguns, U.S. Martial Antique Handguns, Foreign
Military Antique Handguns, Lugers, Mausers) were still ahead of that run and
would have gone the same way. A twelve-hour scan would have finished having
read three sections of nine, reported success, and de-listed nothing, so
nothing would have looked wrong.

The fix is to ask both questions instead of one. `ScrapeContext` now carries
`stored_categories` — the sections this site already holds listings under, read
once at the start of a run before it writes anything — and
`ctx.holds_category(name)` answers it. A section is skipped only when the shop
says unchanged **and** we have read it before; otherwise it is read, with a log
line saying why. The saving is not discarded, only made to wait until it is
true.

**Still open, and smaller:** a section counts as read the moment one listing
from it is stored, so a section interrupted part way through counts as fully
read. Closing that needs per-section read state, which is a schema change; the
practical mitigation today is that an interrupted run never updates
`last_success_at`, so the next run compares against the same "since" and walks
whatever it walked before.


### Legacy Collectibles: read the catalog, not three corners of it — **Shipped**

Found by asking why 142 of their listings de-listed in a single day. A sample
of 24 found only **5 genuinely sold**; the other 19 were still on sale, under
sections this scraper did not read. Chasing that turned up the real problem:

| Section | Listings | Read before |
| --- | --- | --- |
| `/hand-guns` | **696** | no |
| `/rifles` | **281** | no |
| `/us-military` | 105 | no |
| `/walther-ppk` | 52 | no |
| `/new-firearms` | 78 | yes |
| `/antique-long-guns` | 38 | yes |
| `/antique-handguns` | 22 | yes |

**We were reading 127 of 977 — thirteen percent.** And the 87% skipped was not
modern stock but a Commercial Mauser C96, a Swiss Bern 1906/29 Luger, a
Kriegsmarine Mauser 1934 rig, a 1902 American Eagle Luger, Walther PP and P.38
rigs, an Izhevsk M91/30, a Robbins & Lawrence Mississippi Rifle. The "Modern
Handguns"/"Modern Long Guns" sections this scraper declines — and was right to
decline — are different and far narrower sections than these two.

The new source list is `/hand-guns`, `/rifles`, the two antique sections,
`/us-military` and `/walther-ppk`. **A live walk returns 1,001 unique listings,
no warnings, and a price on every one**: 530 rifles, 460 handguns, 11 that the
classifier would not type from a title. The four narrow sections are there only
for what the first two lack — 4 antique handguns, 6 antique long guns, 11 US
military rifles, 4 Walther PPKs.

**Two sections are deliberately absent.**

- `/discounted-items` is 57 listings unreachable elsewhere and 55 of them are
  gear: Luger holsters, a K98 bayonet, a Hospital Corps pouch, binoculars, a
  Luftwaffe overcoat, a book. The standing rule refuses all of it.
- `/new-firearms` is gone, and its removal is the fix for the de-listing. A
  rolling new-arrivals feed de-lists everything that ages off it, which is
  indistinguishable from a withdrawal. With the catalog itself read, its only
  unique listing was one already sold.

**One classifier change fell out of it**, measured against all 3,067 stored
listings before being accepted: `_CATEGORY_IS_ONLY_A_TYPE` knew `long guns`
with its space and `handguns` without one, so "Hand Guns" did not count as a
bare type at all and six of their guns read as accessories on a word in the
title — a Radom VIS 35 "Red Grips", a PPK rig "W/ SS Mags", an M1911A1
"Documented In Clawson Book". Bringing the spelling into line moves nothing
else anywhere.

**What it costs.** The first scan fetches about 880 new product pages at five
seconds apiece — a little over an hour, paid once. After that only new arrivals
need one.

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

**The catalog grid says so too, and it says so on every scan.** That was left
open when the product-page reading shipped, and is now done: `sold_from_card()`
reads the same signal off the card in the grid — `a.card-figcaption-button`,
which reads "Add to Cart" on an in-stock product and is swapped for "Out of
stock" or "SOLD" on a sold one, plus Legacy's badge over the photograph. It
costs no request at all, and it matters because a product page is fetched
**once**: without it a listing that sells after that fetch stays available for
as long as it stays in the catalog.

Measured across the three shops' whole catalogs from the grid alone: 27 of Arms
of America's 47 and 7 of Bowman's 17 read as sold, 12 of them stored as
available, and **not one moved the other way**. One of the twelve can be caught
no other way at all — Bowman's Colt 653 answers 403 to every request, retries
included, so its product page is never read.

**Scoped to those elements, never the card's whole text.** A card carries its
own title, and Legacy Collectibles rename a sold listing "SOLD - ..." — so
reading the text would make a title sufficient evidence on any shop that had
merely used the word, which is how Apex Gun Parts describe most of their kits
("Sold as a Set").

What remains open is only this: a listing that sells **between** scans of its
site is shown as available until the next one. That is true of every vendor
here and is a property of the scan interval, not of this fix.

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

### Atlantic Firearms — **Shipped**, and the fifth platform

The most-visited site on this list — roughly 837,000 visits a month when that
was last measured — and the shop the PrestaShop base class was written for.

**Three sections of nine, and measuring all six candidates before writing
anything is what kept the other four out:**

| Section | Rows | Verdict |
| --- | --- | --- |
| `/parts-kits` | 77 | **Taken.** 38 read as kits — Yugo, AK, VZ58, Galil, RPD. The other 39 are bare barrels, AR uppers and "IGLIM packages" of trigger guards and sights |
| `/c-r-eligible` | 38 | **Taken.** FN 1910s, a Radom P-64, a Bernardelli 60, Yugo M48A and M24/47 |
| `/knives-blades` | 13 | **Taken.** 8 AKM bayonets, and that bucket is small enough to want them |
| `/military-surplus` | 180 | **Refused.** 98 read as neither gun nor kit: gas masks, rucksacks, ammo pouches, thread protectors, magazine grips |
| `/surplus-guns-gear` | 165 | **Refused.** The name is honest — guns *and gear* — and it overlaps the above |
| `/soviet-russian-surplus` | 20 | **Refused.** GP-5 gas masks, AKM wood grips, recoil spring assemblies |
| `/other-cool-firearms` | 180 | **Refused.** "Classic Military Arms" is modern Bula Defense M14 builds. The Arms Unlimited call, for the fifth time |

The four refused sections are 318 unique listings between them, 123 of which
are gear. Refusing them is the standing rule working rather than timidity.

**A live run over the three taken returns 128 listings and no warnings**: 55
kits, 47 rifles, 13 handguns, 13 neither. Fifty-five rather than the 38 a
title-only count suggested — the product pages say "kit" where several titles
do not, which is the corroboration rule earning its keep again.

**The caveat is the price, and it is a real one.** **71 of the 128** show no
price at all — PrestaShop hides it on an out-of-stock product. They are worth storing and start reporting a price
when the shop restocks, but a price watcher gets less from this vendor than the
listing count suggests. That is a smaller version of what dropped Century Arms,
where the prices were hidden by policy rather than by stock, and it is written
down so nobody re-measures it hopefully.

**Two things the build turned up**, both now in the base class:

- **Their theme wraps every card twice.** Each `article.product-miniature` sits
  inside a `div.js-product`, so a plain comma-selector matched 24 cards for 12
  products. `_cards()` keeps the innermost match — the inner element is the
  card, the outer is the grid cell holding it — which fixes it for any
  PrestaShop theme rather than only this one.
- **The cover is not the gallery.** `.product-cover img` is one photograph and
  `.product-images img` is the strip of seventeen that contains it. The walk
  stops at the first selector that yields anything, so the gallery selector has
  to come first or every listing stores a single picture and calls it complete.

Their robots.txt is PrestaShop's generated one: it disallows the facet and sort
parameters — `?order=`, `?tag=`, `?search_query=`, `?limit=` — and says nothing
about `?page=`, so pagination is permitted where filtering is not.

### DuPage Trading — **Shipped**

Requested, and it was as cheap as the measurement suggested: a subclass of a
slug, a name, two URLs and one selector override.

| Section | Listings | Priced |
| --- | --- | --- |
| `/bayonets/` | **20** | 20 |
| `/firearms/` | **3** | 3 |

A live run returns 23 listings, no warnings, and a price on every one.
**Nineteen of the twenty bayonets read as bayonets** — M1905s with M3
scabbards, AFH- and ENS-marked M1s, an M5A1 with its M8A1 scabbard — and the
one that does not is a USMC K-Bar, which is a fighting knife and is right to
sit outside the bucket.

Their two bare M8A1 scabbards are worth a note, because on the title alone the
classifier calls them neither: a scabbard is only a bayonet if the listing says
so, which is the rule `classify._is_a_bayonet` was written around. Their
*descriptions* say so, so the detail fetch settles it — which is the corroboration
rule doing exactly what it is for rather than an exception to it.

**Twenty bayonets nearly doubles that bucket**, which held 24 across the whole
catalog before them.

The three firearms are WWII rifles and all read as such: a Springfield Armory
M1 Garand, a Winchester M1 Garand, and an M14 rebuilt on a Criterion barrel.

**Their grid renders each product twice**, and the count nearly went into this
document wrong because of it: the base class's `li.product article` alternative
matches a second `article` inside every product, so 20 listings arrive as 40
and 3 as 6. The `seen` set collapses them by key, so nothing would have been
stored twice — but the scan log would report double what the shop sells, and a
count that is wrong in the logs is one somebody later trusts. `card_selector`
is narrowed to `article.card`.

**Most of the shop is left alone**, on the standing rule: `/parts/` is broken
down to the barrel, receiver, stock and trigger groups of an M1 Garand and an
M14, `/rifle-stocks/` is USGI and reproduction stocks and handguards, and
`/militaria/` is gear. There is no parts-*kit* section, so this is one of the
shops where "parts, not parts kits" is the whole of the decision and costs
nothing. `/firearms/us-military-firearms/` is the same three guns one level
down, so only the parent is a source.

Their robots.txt is the stock BigCommerce template — cart, checkout, account
and their faceted-search parameters. Nothing in the way.

### Parts kits as a coverage push — **Mostly shipped**

That rule had been in this document since the beginning and **no scraper had
ever followed it.** Audited across the fourteen vendors read at the time: not
one named a parts-kit section in its `sources`. The 25 parts kits then in the
catalog were entirely incidental — 22 from Royal Tiger, whose scraper walks the
whole site rather than a list of categories, and 3 from `classify` recognizing
the word "kit" in a title that happened to arrive through a firearms section.

Both jobs below are now done for the vendors worth doing them for: two existing
shops gained a parts-kit section, and four new shops were added for their kits.
What remains is the long tail of candidate sites that each need their own
build, and the browse-filter question at the end.

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
categories and concluding there was no parts-kit section was the same mistake in
a different shape. A negative from one request is not a negative.

Note the CO Gun Sales URL. The obvious `/product-category/parts-kits/` answers
200 with a page of sub-category *tiles* — "FAL Parts (23)", "Luger Parts (1)" —
and a dozen products among them; the full path under `parts-accessories` is the
real section. That is the MCT Defense trap in a shop that otherwise works, and
the same trap that later hid five sections at Collectors Firearms.

**The caution, and it is the whole difficulty — now enforced in code.** "Parts
kits" as a *vendor category name* is not the same thing as a parts kit. SARCO's
"Parts & Kits" is 465 items and most are single components; the ampersand is
doing the work.

`classify._is_a_parts_kit` no longer believes a section heading on its own: it
proposes, and the listing has to corroborate by saying "kit" somewhere of its
own. That is what separates a Royal Tiger ZB37 parts kit — which says so only in
its description — from the **M3 Tripod Mount** and the **Zeiss periscope** filed
beside it, both of which were parts kits until this existed. A cleaning,
service, repair, maintenance or conversion kit is disqualified by name.

**2. Thirteen candidate sites, measured — and four of them are now shipped.**
Every URL below was fetched. The platform column is from response headers and
markup, not from the URL shape:

| Site | Entry URL | Platform | What the fetch showed |
| --- | --- | --- | --- |
| Apex Gun Parts | `/parts-kits.html` | Magento | **Shipped** (`apex-gun-parts`). A live run over five of their six pages: 98 listings, no warnings, 93 reading as kits and **a price on every one**. The five that miss are titled "Parts Set" or "Parts Selection" rather than "kit", which is the corroboration rule doing its job — Beretta M38/49 SMG, BGS FAL, Brazilian 1908 Mauser, Hotchkiss M1909 LMG, STEN Mk 3, C93, CETME C and L. Their "Rifles" and "Handguns" menus are *parts* sections, so there is nothing else here to take |
| Arms of America | `/all-products/parts-kits/` | BigCommerce | **Shipped** (`arms-of-america`). 47 listings on a full run, and every one lands where it should: 43 kits and the 4 Swiss C&R rifles, nothing miscategorized. PPSh-41 with drum, IWI UZI, Yugo M72B1 RPK, Polish Radom DPM and RPD, Sig STG 57, VZ61, G3/HK91. 25 of the 47 carry no price, which is BigCommerce hiding it on an out-of-stock product. Their modern AK builds are left alone |
| Bowman Arms | `/parts-kits/` | BigCommerce | **Shipped** (`bowman-arms`). 17 listings, all 17 reading as kits and all 17 priced — the only shop on this list where both are true. One product page (their Colt 653) answers 403 to every retry, so the run is PARTIAL with the catalog entry kept — Polish PM63 RAK, WZ.43/52, Yugoslav M56, Israeli FAL, Colt 653, G36 Schnittmodell, 1928 Thompson. No firearms section to leave out |
| Atlantic Firearms | `/parts-kits` | PrestaShop | **Shipped** (`atlantic-firearms`), with two other sections. 77 listings, 38 reading as kits; see its own section above for why the other four candidate sections were refused |
| Every Gun Part | `/parts-kits/` | BigCommerce | **Refused.** 177 listings and only nine name anything milsurp — and those nine are modern production (Springfield Armory 1911A1, ArmaLite AR10, Walther PPK). The rest is Del-Ton, Charter Arms, Röhm, Rock Island, Taurus, Ruger, Glock, SCCY, Bryco Jennings. A parts-kit section is not automatically a *surplus* parts-kit section |
| Centerfire Systems | `/collections/parts-kits-surplus-parts-kits` | Shopify | **Already a shipped vendor** — this is job 1 above, not a new site |

**The long tail, re-measured, and it is mostly gone.** Every remaining candidate
was fetched again rather than trusted from the notes above, which was the right
call — half of them have changed since:

| Site | Then | Now | Verdict |
| --- | --- | --- | --- |
| Max Arms | WooCommerce, 16 cards, no prices | `maxarms.com` is now the personal site of an AI product manager | **Dropped.** The shop is gone |
| Robert RTG | 200, 33 prices | **Connection reset** at TCP level, on the root as well as the section | **Blocked** |
| Proteus Armaments | 200, 18 prices | **403** from Cloudflare | **Blocked** |
| APP Arms Co | 403 from nginx | 403 from nginx, unchanged | **Blocked** |
| Numrich | client-side | 200, 170KB, 2 prices, no cards — Miva (`mm5-GPC-basket-id`) | Needs its endpoint found before it is worth starting |
| What A Country | bespoke ASP.NET | 200, 64 prices, product links like `/colt-m16a1-parts-kit.aspx` — a Colt M16A1 kit, an M1 Carbine kit, a Hungarian AK63D underfolder | Real stock behind bespoke markup; its own build, and the pick of what remains |
| MCT Defense | one product page | unchanged — `/product/` is a product, not a section | Still needs an entry URL |

So of the thirteen: **four shipped**, **one refused on measurement**, **one
dropped** (domain gone), **three blocked**, **three needing their own build**,
and one that was already a vendor.

**Two figures in the tables above were wrong before they were measured
properly, both in the same direction.** Apex was recorded as "837 product blocks
in one 722KB page" from a loose grep of the markup; their own toolbar says
"Items 1 - 20 of 102", which is six pages of twenty. Arms of America was
recorded at 86 cards and 82 prices; the section is one page of exactly 43
`article.card` elements with 43 distinct product links, and 25 of the 43 carry
no price at all. A grep over markup counts markup, not products; the only honest
count comes from running the scraper.

**One thing to settle before the rest of it**: the browse page currently treats
"Parts kits" as one of five Types. Several dealers' worth of kits is a different
proposition from 25 — it is plausibly the largest category in the application —
and it is worth deciding whether a kit should be filterable by the model it
builds before there are thousands of them.

### Police surplus — **Four shipped, two refused** of ten measured

Departments trade in their duty weapons in lots, and a dealer sells them as a
named section: Glock 22s and 17s, M&P 40s, 870s, and increasingly AR-15
patrol rifles. It is not milsurp and it is squarely the same *question* —
somebody's service weapon, sold on, in quantity, at a price worth watching.

**The boundary, and it has already caught this list out once.** Arms Unlimited
was written, run and backed out because their `/surplus/` section is police
trade-in *gear* — Tasers, holsters, a water bottle — and their `/rifles/` is
modern Colt M4s. That judgment about the gear stands. What was never checked
is whether they also list trade-in *pistols*, because the section was condemned
whole; the scraper was a two-line BigCommerce subclass and restoring it is
cheap if the handguns are there.

**What has to change in the classifier, and it may be nothing.** A police
trade-in Glock reads as a handgun already. The problem is the opposite of the
surplus rules' usual one: much of the vocabulary exists to *reject* modern
stock, because "not a surplus dealer" has been the right call four times now
(Arms Unlimited, Legacy's Modern sections, Centerfire's AR-15 collections,
Atlantic's "Classic Military Arms"). Police surplus is modern by definition, so
the distinction can no longer be "is it old" and has to become "is it
*surplus*" — a fact about the vendor's section, not about the gun. Read the
sections that say so and leave the rest, exactly as with parts kits.

#### The ten sites, as they answer today

| Site | Section | Platform | What the fetch showed |
| --- | --- | --- | --- |
| **Recoil Gun Works** | `/police-trade-in/firearms/pd-trade-rifles/` | **BigCommerce** | 200, **12 cards, 54 prices**. Stock Stencil — `article.card`, `SF-CSRF-TOKEN`, `fornax_anonymousId`. A four-line subclass, and the readiest of the ten |
| **Officer Store** | `/firearms/used-firearms` | **BigCommerce** | 200, **9 cards, 31 prices**. Same shape, same cost |
| **Impact Guns** | `/police-trade-in-guns/` | BigCommerce + **Searchanise** | **Refused** — measured and empty. See below |
| **USA Gun Shop** | `/used-guns/` | WordPress | **Refused — not a dealer.** It is an affiliate price-comparison site: 89 of its product links go to `classic.avantlink.com`, with Bass Pro affiliate links beside them, and the cards say "Compare price" and "sold by". Its listings are other shops' stock and its prices are other shops' prices, so following it would duplicate catalog that belongs to the dealers themselves. Its robots.txt also asks crawlers off the pricing API in as many words — *"every bot fetch counts as an AvantLink click with no real buyer"* — which is a request worth honoring whatever else were true. The platform note was wrong too: `wp-content` throughout, but no WooCommerce Store API (404) |
| **GunPrime** | `/tags/police-trade-in` | Rails (Passenger) | 200, 46KB, 25 prices, no standard cards. Its own build |
| **AIM Surplus** | `/categories/firearm/police-trade-ins` | **Laravel + Vue 3** | **It has an endpoint, and the browser reading would have been wrong a fourth time.** The page is 39KB with zero prices, and `/js/store.js` (507KB) names the routes: `/data/search`, `/data/search/suggestions`, `/data/products/`, `/items/`. `/data/search` answers with JSON — a 500 for a guessed parameter shape, which is an endpoint refusing a bad query rather than a route that is not there. Its robots.txt is `Disallow:` with nothing after it: everything is permitted. **The next one to build**, once the query shape is worked out |
| ~~**Southern Tactical**~~ | `/firearms/police-trade-in-firearms` | nginx, not identified | 200, 36KB, 3 prices. **Dropped: not viable.** Three prices in 36 KB, no endpoint found, and no evidence the catalog is worth the build |
| **GovDeals** | `/en/firearms-live-ammunition` | Akamai bot management | 200 but `_abck`/`bm_sz` cookies and no prices. A government *auction* site, not a shop — the price model is bids, which this application has no idea about. Bottom of the list, and arguably out of scope |
| **Clyde Armory** | `/agency-trade-in/` | — | **TLS handshake fails** from here. Retry later; it may be transient |
| **Palmetto State Armory** | `/guns/used-guns-surplus-firearms-trade-ins.html` | Magento, Cloudflare | **403** to a plain request. Blocked, like APP Arms Co |

**Suggested order**, cheapest first: ~~Recoil Gun Works and Officer Store~~
(both shipped); ~~then Impact Guns~~ (refused — its police section is empty and
its "Used Guns" is 8% surplus); ~~then re-open Arms Unlimited's handguns~~ (restored). USA Gun Shop,
GunPrime is its own build. AIM Surplus needs an
endpoint found. GovDeals is an auction and Palmetto is blocked.

**And take their milsurp while there.** Several of these are general dealers
with surplus and parts-kit sections of their own — Impact Guns' catalog is
12,340 items and Palmetto's is larger still — so each build should read the
site's own navigation for C&R, military-surplus and parts-kit sections at the
same time, on the same rules that govern every other vendor here. That is one
visit rather than two, and the section-by-section measurement is the same work
either way.

**Decided, and it is their own Type.** "Police surplus" now sits in the browse
filter between Parts kits and Other. The column is `items.is_police_surplus`
(migration 0016) and it sits **alongside** `is_rifle`/`is_pistol` rather than
replacing them: a PD Trade Glock is a handgun and everything except the browse
filter should keep getting that answer, so `KINDS` in `services/search.py`
subtracts police surplus from Rifles and Handguns in the one place that cares.
Making the column lie would have been cheaper and wrong.

A listing earns the flag from **the vendor's section and nothing else** — a PD
Trade Glock 22 is mechanically the same object as any other Glock 22 and no
title distinguishes it — with one condition measurement forced: it must also be
a firearm. Those sections are not pure. Officer Store shelve used Glock
magazines among the pistols, and Recoil file Federal HST and Speer Gold Dot on
the parent page above theirs.

#### The first two — **Shipped**

**Recoil Gun Works** (`recoil-gun-works`): **229 listings, 0 warnings, every
one priced** — 161 pistols, 39 rifles, 29 shotguns. **222 of the 229 are sold**:
this shop leaves sold stock up, and on the grid it is indistinguishable from
stock they have, so the browse page's default "Available" filter shows seven of
them. Not a reason to skip the shop — a trade-in that sold is a price somebody
paid for a department Glock on a day that has passed — but the catalog count is
not coverage here. Glock 17/19/21/22/23/26 in
Gen 4 and 5, Sig P226s on German frames and P220s, CMMG, Windham, Rock River,
Bushmaster and S&W M&P-15 patrol rifles, Remington 870 Police Magnums and
Mossberg 590A1s. The survey's "12 cards" was page one of fourteen.

Three sections read, four refused, and the refusals are the judgment worth
keeping. `/police-trade-in/` looks like *the* section and is a mixed shelf —
its first page holds ammunition and a $10.99 magazine — so the firearms are
taken one level down as three leaves. `equipment` and `magazines` are gear.
And `/surplus/` is the trap of the four, because the name is exactly right and
the contents are not: Scott M98 respirators, UTM and Simunition marking
cartridges, a P226 UTM conversion kit, an AR-15 conversion bolt carrier.
Sampled and rejected, the same call as Arms Unlimited's `/surplus/`.

**Officer Store** (`officer-store`): **13 listings, 0 warnings, every one
priced** — 11 pistols, and the two "other" are Glock magazines shelved among
them. Their titles carry a condition grade, which almost nothing else in this
catalog does: "LE Trade-In Glock 21 Gen 4, .45 ACP, 3 Mags, Grade 2" at $339.99
against a Grade 3 at $329.99. That is a vendor stating plainly what surplus
listings usually leave to a photograph.

Both are four-line BigCommerce subclasses. The base class needed no changes at
all, which is the one prediction in this section that held exactly.

#### Impact Guns — **Refused**, and the shelf is empty

The largest catalog on the list and the one that looked readiest after the two
BigCommerce shops: the Searchanise key `4u8N0h9r5t` still works, the base class
needed no changes, and the subclass would have been four lines. The build was
never the obstacle.

**Their police trade-in section holds nothing.** The page exists, declares
itself (`categoryId 1631`, `category":"Police Trade In Guns"`) and says in its
own markup: *No products. 0 items.* The API agrees --
`restrictBy[categories]=Police Trade In Guns` returns `totalItems: 0`. This
document listed them for the URL, and the URL is a shelf with nothing on it.

**Their "Used Guns" (117) is not this catalog's subject.** All 117 titles were
pulled and sorted:

| | Count | What they are |
| --- | --- | --- |
| Modern used | **106** | Colt King Cobra *Factory Blemished*, Stag 15 Tactical SBR *Demo*, Glock 43 Rebuilt, Glock 21 Gen3 Used, Detonics Pocket-9, Bushmaster Hunter 450 |
| Milsurp-ish | 11 | Mosin M91/30 Ex-Dragoon, three Russian SKS-45s, a Century SKS, a Norinco SKS |
| Police trade-in | **0** | — |

And the eleven thin out on inspection: an Auto-Ordnance M1 Carbine is current
production and a High Standard Supermatic Trophy matched only on the words
"Military Grip". Nine genuine in 117, or **8%** -- which is Every Gun Part's
ratio almost exactly (177 listings, 9 milsurp), and that was refused. Taking it
would import 106 modern used handguns and ARs to gain nine surplus rifles.

**"Military Guns" (228) is the same trap with a better name**: Springfield M1A,
HK MK23, Colt AR6951, Auto-Ordnance M1 Carbine, a Traditions mini cannon.
Current production in military patterns. That is the "not a surplus dealer"
call for the fifth time, after Arms Unlimited, Legacy's Modern sections,
Centerfire's AR-15 collections and Atlantic's "Classic Military Arms".

One measuring note worth keeping, because it would mislead the next person:
**the Searchanise facet counts do not match the category counts.** The
`categories` facet reports `Used Guns: 1`; asking for the category directly
returns 117. Trust `restrictBy`, not the facet bucket.

#### Wix Stores — **Base class shipped**, and Wix does not need a browser

This document has said *"Wix renders client-side, so expect the browser path"*
since the platform table was first written. It is wrong. The catalog grid and
the product page both arrive as HTML with the store's data already in them;
what renders client-side is the interactivity, not the content. That is the
**fifth** "needs a browser" reading to be wrong here, after J&G Sales,
Centerfire, SARCO and AIM Surplus, and at this point the inference should be
treated as evidence of nothing at all.

**Wix is the easiest platform on this list to read**, which was not expected
either. It marks its own furniture with stable `data-hook` attributes —
`product-item-root`, `product-item-product-details-link`, `product-item-name`,
`product-item-price-to-pay`, `product-item-out-of-stock`, and `description`,
`sku`, `product-price` on the product page. Those are Wix's, not a theme's, so
they survive a shop restyling itself. The BigCommerce and WooCommerce classes
both had to start from CSS selectors chosen out of one vendor's markup, and
both have since needed per-shop overrides; this one may not.

Two things the class had to learn:

* **Paging is `?page=N`.** Wix hides an SEO pagination list beside its
  "Load More" button (`product-list-pagination-seo`), so the pages a person
  reaches by scrolling are reachable by asking. Guarded by robots.txt —
  Surplus Defense disallows only `*?lightbox=`, but Collectors Firearms'
  `Disallow: /*?*` is the standing reminder that a query string is not always
  available.
* **Strip the image transform.** Wix serves everything through
  `…~mv2.jpg/v1/fill/w_1000,h_750,…/file.jpg` and the page never references
  the original. Cutting from `/v1/` gives it: **1.7MB against 53KB** for one
  M1 carbine photograph. Hunter's Lodge taught this on the same CDN, where the
  difference was OCR that worked against OCR that returned nothing.

**It did not unlock The Mosin Crate, and the reason took two goes to get
right.** The first reading was "no products": their `/shop-1` answers 200 with
625KB of Wix scaffolding and zero product hooks, zero `/product-page/` links
and zero prices, and Wix generates a `store-products-sitemap.xml` only for a
store with stock — Surplus Defense has one, The Mosin Crate's index lists
`pages-sitemap.xml` and nothing else. Every one of those observations is true
and the conclusion drawn from them was wrong.

**They do not use the store app they have installed.** The stock is *prose*, on
the page, beside group photographs of numbered items — the same shape as
Hunter's Lodge's scanned flyer, one technology up. And it is strikingly
regular:

```
#1  - RIA 1903 12th Cav C&R 30.06 - G   - $1599**SOLD**
#5  - Lahti L-35 C&R 9mm          - G   - $2099**SOLD**
#3  - Maynard Cav Carbine ATQ     - F/G - $1199**SOLD**
#DC - SMKH Tungsten 15rd Box 8mm  - B   - $259
```

`#<number> - <description> - <grade> - $<price>[**SOLD**]`, with grades from a
fixed set (N, V, G, G/V, F/G, B) and a sold marker that varies only in its
asterisks. A pattern written in five minutes matched **43 of 43** lines on the
one page.

**And 41 of the 43 are sold.** What is actually for sale is an AR lower pack
and a box of 8mm ammunition — no firearms at all. So this is a shop that sells
out a crate at a time and leaves the record up, and the two live items are
things this catalog does not take anyway.

**Refused, and worth re-checking rather than re-deciding** — emphatically so
here, because the format is parseable and the stock when it lands is exactly
the subject: a French Lebel 1888, an RIA 1903 12th Cavalry, a Steyr M95, a
Maynard cavalry carbine, a Lahti L-35, a Romanian TTC, and a run of USMC 1903s.
Catch a crate drop and this is worth a bespoke text scraper of perhaps fifty
lines. Their newsletter announces the drops.

Pasadena Pawn, the third, now answers 114 bytes and is gone. So the Wix group
is one live site of three — which is an argument for the base class having been
worth writing anyway, since it is what made the other two cheap to dismiss.

#### Surplus Defense — **Shipped**

Forty-five listings across three sections and **every one of them collector
milsurp**, which is a combination this list does not offer often: an IBM Corp.
M1 Carbine of 1943, a Spanish Oviedo Mauser 1917, a matching Russian 91/30 Tula
1939, an M41 Carcano, a Turkish M1938 Mauser, a WW1 German DWM 1916 Artillery
Luger matching with its holster, two T-Series Browning High Powers, an 1895
Nagant revolver, a chromed 1941 Mauser Luger, an SS dagger, an SA dagger by
J.P. Sauer und Sohn, and a Japanese Imperial Type 98 sword.

**Their edged weapons are read, unlike most shops'.** The standing rule keeps
gear and components out, and an SS dagger, an SA dagger by J.P. Sauer und Sohn
and a Japanese Imperial Type 98 sword are neither — they are the collectible
objects this catalog is about, at $550 to $1,500 apiece. `/accessories`,
`/ammunition`, `/field-gear` and `/flags-and-armbands` are left alone on the
usual grounds.

**They file under "Other", and that is a gap rather than a decision** — worth
recording because the first draft of this section claimed the opposite. The
classifier has a bayonet bucket and these are not bayonets, so all five land
with the accessories; measured, not assumed. Whether daggers and swords should
join bayonets, or whether the browse filter wants an edged-weapons Type of its
own, is a question for whoever next touches those buckets, and it wants asking
against more than five listings.

**Eighteen of the forty-five are out of stock**, and on this platform that is
how a shop says sold: the price is removed along with the availability, so a
card with no price here is gone rather than "call for price". Their
`/sold-items` page is deliberately not read — what it holds is already in the
three sections above, marked out of stock, and reading it too would file each
sold rifle twice.

#### AIM Surplus — **Shipped**, and the fourth "needs a browser" that did not

**180 listings, 0 warnings, every one priced** — 162 Police Trade-Ins and 18
Curio and Relics, 123 handguns and 53 long guns. The largest *live* police
catalog of the four: Recoil has 229 but only seven in stock.

This document said it was "a bespoke application, not BigCommerce" and told
whoever picked it up to look for the endpoint first, because that reading had
been wrong three times. It was wrong a fourth. Two routes, both named in
`/js/store.js`:

```
/data/search?q=&g=&category=<id>&filter=&sort_by=&pagesize=<n>&page=<n>&mode=category
/data/products/<id>
```

**Send every parameter, including the empty ones.** `/data/search?q=glock`
answers 500 and so does `?category=firearm/police-trade-ins`, which is what
made this look like a route that was not there. The full form is a 200. And a
category is a *numeric id* — the page carries its own in `data-category-id`.

**Their `properties` list is better than parsing**: Manufacturer, Caliber and
Capacity arrive as named fields, so the caliber and the maker are read rather
than inferred from a title. Almost nothing else on this list does that.

**Where the images live, because nothing on the site will tell you.** The API
returns bare filenames and no page anywhere carries a product image — the whole
site renders client-side, and fourteen guessed paths returned 404. The bucket
is named in exactly one place: an inline Vue template binding a *category*
thumbnail to `'https://dvjr4l3xblvos.cloudfront.net/categories/' +
category.image`. The products sibling of that path answers 200, and the
`master` key is full resolution.

**A gallery is not all photographs.** A video sits in the same array as
`{"embed": "zPvfPM28-SI", "master": "zPvfPM28-SI"}` — a YouTube id, with
`master` reused to carry it rather than naming a file. Read as a filename it
becomes a CloudFront key that does not exist, and the bucket answers **403
rather than 404**, so eight queued downloads looked like a host blocking us
instead of eight URLs that were never pictures. Three of the eight were the one
product video several trade-in listings share. Entries carrying `embed` are
skipped.

**Two of seven firearm sections read.** Handguns (392) and Long Guns (179) are
a modern dealer's shelf — BCM RECCE-16s, Radical Firearms, Spike's Tactical —
with the occasional Yugo SKS among them; NFA Items (221) is suppressors and
short-barreled rifles; Receivers (69) and Frames (30) are components. The
trade-ins cross-listed under Long Guns are collapsed by the `seen` set.

#### Arms Unlimited — **Restored**, on a section nobody had opened

Written, backed out, and restored. **The original refusal was right about what
it examined**, and both halves were re-checked before this shipped:
`/surplus/` really is police trade-in *gear* — Tasers, Taser batteries, a
Magpul rear sight, a stainless water bottle — and `/firearms/` really is
current production: Beretta A300s and 92FSs, B&T suppressors, a Colt M4A1
SOCOM. Both still refused.

What the call got wrong is that it condemned the shop whole. There is a third
section, `/used-collectible-firearms/`, and it is the trade-in stock this
document wondered about:

**20 listings, one page, 0 warnings, every one priced.** Twelve are military —
Zastava M57 7.62x25, M88A 9mm and two M83 revolvers, a Beretta 70 .32 ACP, an
M79 Thumper 40mm, a French FRF2 sniper rifle with scope, a SIG PE57 in 7.5x55
Swiss, HK AG36 37mm and HK69A1/MZP1 40mm launchers, and an 1881 Colt Gatling
gun. Five are modern used (a Remington 870, a Glock G44, a DPMS A15, two Colt
carbines) and two are collectible rather than surplus, including Benny Binion's
personal Colt Single Action Armys.

**Sixty per cent on subject**, against the 8% that got Impact Guns refused on
the same page. That is the number the two decisions turn on, and it is why one
shipped and the other did not.

`/department-trade-program/` turned out to be a page describing how a
department trades its duty weapons in. It holds no products; what comes out of
it is shelved under used and collectible with everything else.

**One known gap, measured and left alone.** A Gemtech SeaHunter suppressor in
that section reads as a rifle. The classifier's own judgment is correct —
without a category it says accessory — and it is the section name *"…
Firearms"* that promotes it, which is the deliberate rule that a vendor's
category outranks the heuristics. One listing in twenty, against a heuristic
with a history of regressions: recorded rather than fixed. The four listings in
the stored catalog that mention a suppressor are all guns *with* one, and all
classified correctly.

#### A spec list puts the product first — **Fixed**

Recoil write every title as `PD Trade | 870 Police Magnum | 12GA | Wood Stock`,
and the accessory test reads English word order: the thing being sold sits
last, with nothing firearm-shaped after it. In a specification list that is
exactly backwards, and it cost seven firearms — two Mini-14s and an LWRCI REPR
read as a stock and a barrel, four 870s and a 590A1 as stocks.

The head-noun question is now asked of the first pipe-delimited segment.
**Measured before it was written: no listing in the stored catalog of 4,121
uses a pipe in its title**, so the narrowing provably cannot change what any
existing vendor is filed as — re-classifying the whole catalog moved exactly
one listing, a Steyr Model 1909 that is a pocket pistol and was stored as a
rifle, which is unrelated drift and a `make reclassify` away.

**Worth deciding before building**: whether police trade-ins want their own
Type in the browse filter, or simply sit among the handguns and rifles. They
partition cleanly by vendor section, so either is available.

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
| **BigCommerce** | Legacy Collectibles, Arms of America, Bowman Arms, Arms Unlimited, Edelweiss Arms, SARCO | **Base class shipped** (`app/scrapers/bigcommerce.py`). Six sites, one platform, and the markup is close to WooCommerce's: `article.card`, an entity id per card, a "next" link. Two of these were in Group A on the URL guess. Of the six, **five shipped** — Arms of America and Bowman Arms arriving from the parts-kit push and Arms Unlimited from the police one, each a subclass of four lines. Arms Unlimited had been dropped as out of scope and was restored on a section nobody had opened; Edelweiss Arms is the one refusal, and not for the reason recorded for years — it is stock-less rather than price-less. SARCO is on the platform and is *not* read by this class: its grid is drawn by Searchanise, so it goes through `searchanise.py` instead — but the external keys are deliberately the same `bc-<id>`, so it could move here without arriving as a duplicate catalog |
| **Shopify** | IMA-USA, Centerfire Systems | **Both shipped** (`app/scrapers/shopify.py`). Cheapest per site, and the estimate held: structured JSON, no browser, no detail fetch. Centerfire had been filed as a one-off build on the URL guess |
| **Wix** | Surplus Defense, ~~The Mosin Crate~~, ~~Pasadena Pawn~~ | **Base class shipped** (`app/scrapers/wix_stores.py`), and **no browser needed** — see the section above. Only one of the three is a Wix *store*: Surplus Defense shipped. The Mosin Crate has the app installed and sells in prose beside group photographs, with 41 of its 43 numbered items sold; Pasadena Pawn answers 114 bytes and is gone |
| **Magento** | Classic Firearms, Apex Gun Parts, ~~Century Arms~~ | **Base class shipped** (`app/scrapers/magento.py`), and two sites of the three kept. Classic Firearms was listed as Unknown until its markup was read: 59 `mage.` markers and a `/media/catalog/product/cache/` image path. It is the most-visited site on the list. Apex Gun Parts arrived later, from the parts-kit push, and is the one shop here that runs on the base class's **stock selectors unchanged** — the theme is plain `li.product-item`. Century Arms is dealer-only and was dropped |
| **Laravel (custom)** | AIM Surplus | `laravel_session`; a bespoke application, not BigCommerce |
| **PrestaShop** | Atlantic Firearms | **Base class shipped** (`app/scrapers/prestashop.py`). The most-visited site on the list, and still a class of one — which is the arithmetic the BigCommerce group got wrong, so it is worth saying plainly. The class is small and the shop is worth reading; a second PrestaShop vendor would be nearly free |
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
| — | ~~Edelweiss Arms~~ | https://edelweissarms.com/ | **Refused. Not price-less — stock-less.** Re-measured properly: nine products sampled across `long-guns/switzerland`, `handguns/lugers` and `handguns/semi-automatic`, and **all nine are `OutOfStock` with no price on the grid or the product page**. Even their *New Arrivals* page is twelve sold items. The earlier note said "worth having for new-stock alerts, worth nothing for price tracking" — the first half is wrong too, because there is no new stock to alert on. This is a gallery of past sales. The stock is superb and entirely beside the point: a ZFK 31/42 sniper rifle, DWM Artillery Lugers with stock and holster, a SIG Vetterli 1868 prototype — all sold, none priced. Nothing here can be tracked |
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
  This is the fourth time — Arms Unlimited, Edelweiss Arms, Century Arms,
  Impact Guns — so the check is now written into the README: read twenty cards
  and count how many carry a price, how many are surplus and **how many are in
  stock**, *before* writing the subclass. The third of those was added when
  Edelweiss was finally measured rather than assumed: it is not price-less, it
  is stock-less, and a scraper would have imported a hundred sold listings that
  never change again.

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
and a few listings take a neighboring panel's price. Every listing carries the
crop it was read from and keeps the raw OCR text as its description, so the
source is always one click away.

- [x] **Panel-bounded listings.** Side-by-side panels within one half of the
      page were read interleaved, so a product quoted its neighbor's price —
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
         of the first capitalized one leaked in from a neighbor: "Swedish
         steel. GAHENDRA MARTINI RIFLE".
- [x] **Content-versioned photo URLs.** `/items/<id>/photos/<id>` is built from
      two reused database ids, so the same URL could come to hold different
      content — and did, every time a site was cleared and re-scanned. The URL
      now carries a `?v=` token derived from the stored file, so changed
      content is a changed URL.
- [x] **Bulleted lists survive OCR losing the bullet**, and the price is taken
      as the first amount in a listing rather than the largest — the order the
      page is written in. 26 to 30 listings, and the prices that were borrowed
      from a neighbor are the item's own.
- [ ] **The last three.** "1903 TURKISH CONTRACT MAUSERS", "WW2 ENFIELD NO1 MK2
      PARTS KITS" and "CZ 52 SEMI AUTO ASSAULT RIFLES" still take their title
      from their own prose. In each case the heading is on the far side of a
      *column* boundary from its body, which is the one boundary nothing is
      allowed to cross — and for good reason, since crossing it is what made a
      product quote its neighbor's price. Worth revisiting only with a way to
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

#### Saved searches, and a per-search email — **Shipped**

Name a set of browse filters, see them listed, run one, and have its results
mailed with your digest. Requested, specced here, and built.

**A saved search is the browse page's own query string under a name.** Not a
column per filter: the filter set has grown four times already and a column
each means a migration each time. So `saved_searches` is `(user_id, name,
query, sort, email_enabled, email_item_limit)` and "run this search" is a link
to `/?<query>` — there is no second search implementation to drift from the
first.

**The query is validated when it is saved, not when it is sent.** A saved
search runs unattended every morning, so a row that has rotted into an unknown
parameter would otherwise mail an empty result with nobody there to see the
error. `services.search.parse_query` refuses an unknown parameter, an unknown
sort, a non-numeric price or an unknown type at save time, with a 400 in front
of the person who can fix it. It is also what canonicalizes the stored form —
sorted, with the paging parameters dropped — so two searches built by the same
clicks in a different order are one search, and so an email is never silently
capped at whatever page size the user happened to be on.

**"Send now", per search.** Each card has a button that mails that one search
immediately. It is **out of band**: it touches neither `next_send_at` nor
`last_digest_cutoff`, because pressing it is not the daily digest arriving
early and must not make the next real one skip what it covered. It ignores
`email_enabled` too — "send this every day" and "send it to me now" are
different questions, and seeing what a search would mail before committing to
the daily one is most of why the button is there. A search matching nothing
sends nothing and says so on the page; an empty email is worse than a line of
text on the screen the button is on.

**The email is capped and the run is not.** The cap is a per-search dropdown
(5, 10, 20, 30, 50, 100) on the saved-searches page; opening a search shows
everything it matches. It sends **the whole result set, capped** — not "what is
new since last time". A saved search is a standing question and its answer is
what matches today; the digest's other two sections are about change and this
one deliberately is not. Where the cap bites, the section says so — "Showing 5
of 12 matches — see them all" — and links to the search.

**The sort is part of the search and the email is in it.** `search.run` applies
the saved sort and the rows are rendered in the order it returned them. An
email assembled by grouping or re-filtering a list it already had would come
out in whatever order the second query chose, which is the failure this was
most likely to have.

**Its rows link to our own item page, not to the vendor.** That is what was
asked for and it is the better link: the item page carries the price history,
the full gallery and a "View on vendor site" button, so the vendor is one more
click rather than the only destination. Titles are truncated at 80 characters
and descriptions at 160, on a word boundary, with a real "…".

**What it cost elsewhere.** `SORTS`, `apply_filters` and the search-term parsing
moved out of `api/items.py` into `services/search.py`. They had one caller and
now have two, and the two have to agree exactly — a saved search that returned
one set of listings in the browser and another in the email would be worse than
no saved search at all.

**Two things deliberately not done.** There is no sharing and no approval step:
a saved search is the user's own, every route is scoped to the current user,
and somebody else's id answers 404 rather than 403. And a saved search is *not*
scoped by the digest's site selection — one that names its sites says so in its
query, and one that does not is asking about the whole catalog on purpose. A
user with no sites selected but a mailing saved search now gets a digest, where
before they got nothing.

#### The rest of the search work

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

#### How effective the armory actually is — **measured**, and acted on

Measured over 4,562 active listings by re-deriving every field twice: the text
alone, then the armory on top, exactly as `_apply_catalog` does. The gap between
the two is the armory's contribution.

**What it was doing well, and what it was not.**

| contribution | listings | share |
| --- | --- | --- |
| caliber spellings normalized | 1,453 | 31.9% |
| blank country filled from the model | 474 | 10.4% |
| rifle/handgun settled by the model | 1,432 | 31.4% |
| …where that *changed* the text's answer | **1** | 0.0% |
| blank manufacturer filled | 83 | 1.8% |
| blank caliber filled | 64 | 1.4% |
| dealer's caliber kept over the model's | 141 | 3.1% |

Normalization is the real value and always was — it is what makes the browse
filter work. **Filling in blanks, the thing it is named for, was 1.5%.** The
kind refinement corrected the text exactly once in 1,432 opportunities: cheap
insurance, not a feature to invest in.

**The cause was not matching, it was content.** Of 359 approved and enabled
model rows, 240 have no caliber, 308 no maker, 200 no kind, 195 no country —
and **194 (54%) say nothing at all**. Over half the approved armory matches a
title and then contributes zero. Model coverage itself is 41.3% of listings
(51.0% of firearms), and a further 46 rows are approved but switched off.

**What shipped from it.**

- **The maker's country** (migration `0017`), the largest single lever: 1,247 of
  the 1,407 country-blank listings already carried a maker. Country coverage
  69.2% → **91.5%**. Weakest of the three answers and asked last — see
  README.md → "The armory".
- **A cartridge no longer supplies the maker** ahead of a firm the title names.
  133 corrected, 8 lost, 7 of those 8 also corrections.
- **Vendor shelf labels out of the discovery queue.** "LEO", "PD", "Trade-in"
  and friends were being read as part of a maker's name: five of eleven pending
  maker proposals were `LEO Trade-in Armalite`, `PD Trade Bushmaster`,
  `Trade-In Daniel Defense`, `Trade Rock River` and `River Arms LAR-15`. A
  designation now stops the walk too, which was proposing `Armalite M15`
  alongside `Armalite` from the same title.
- **The item page shows the match**, with the pattern's facts, the reference
  link and whether the row is actually approved.

**Not done, deliberately.** Family-level rows — a bare `Mosin-Nagant` beside the
M91/30, M44 and M38, and the same for Glock, Colt, Mauser and Smith & Wesson —
would have reached 1,057 of the 1,992 unmatched firearm listings and taken model
coverage to ~64%. Considered and declined: a family row cannot state a caliber,
and the fields it would fill are better filled by the maker's country above.

#### Where a price sits among the same gun — **Shipped**

The first thing in this application that answers "is this a good deal?", and it
is the armory's payoff rather than more of the armory: a listing matched to a
model and carrying a maker and a cartridge has peers, and **123 such groups
cover 1,220 active listings**. The item page draws where this one sits among
them. See README.md → "Is this a good deal?" for the design and the measured
reason the bar is scaled by rank rather than by dollars.

**And a correction to the section above.** It said filling in the 194 silent
model rows was "the largest remaining lever". Measured afterwards, it is not:
those rows match **275 listings between them**, and the fillable payoff is 57
listings gaining a caliber and 32 gaining a country. The number was asserted
without being checked, against this document's own rule. The largest remaining
lever is promoting the pending models — **+436 listings matched, 0
regressions** — which is one bulk action and no data entry at all.

Two more things that measurement turned up, both worth knowing before spending
an afternoon on model rows:

- Several "missing" calibers are not missing. Walther PP (98 listings), PPK
  (54), M1911A1 (33) and Colt SAA (28) each state *two* cartridges and so
  correctly say nothing. That is the armory working.
- The 46 approved-but-disabled rows are disabled on purpose — `Model 1911`,
  `M14`, `M16`, `P14` — and the silent rows are the same shape. For an
  ambiguous bare designation, disabling or merging is more correct than filling
  in, because one answer would be wrong for half the matches.

**Still open.**

- **Promote the 104 pending models.** +436 listings, one action.
- **Fill in the silent rows if convenient**, worth ~89 listings, top twenty
  worth 98 of the 275. The eye on each armory row opens the listings it accounts for,
  which is the check to make while doing it.
- **Fill in the 194 rows that say nothing.** The largest remaining lever and no
  code at all.

#### eBayonet — **Shipped**, and the first vendor with no storefront at all

**724 listings, every one priced, 721 with photographs**, $5–$3,800, median
$150. Bigger than all four police-surplus vendors put together, from five
hand-maintained files.

**A listing is a run of paragraphs, not one paragraph**, and that is the whole
site. The stock number and description open it, the photographs follow as their
own paragraphs, and the price is a paragraph of its own at the end. Reading only
the paragraph that opens a listing finds a price on **11%** of them — which was
the first measurement taken here, and it was wrong. Walking to the next stock
number finds one on **100%**.

**The photographs are text, not markup.** There is not one `<img>` tag in a
megabyte of HTML: the pictures are bare URLs typed into the prose. A count of
image tags says this site has no photographs; it has 3,099.

**Eleven stock numbers are duplicated on purpose.** A bayonet carried by two
countries is written out on both of their pages — once in full, once as
"15450 Mukden Mauser bayonet. SEE LISTING UNDER MANCHUKUO." The stock number is
the external key, so keeping both means one overwrites the other and which one
depends on the order the pages were read in. The marked ones are dropped, and
where there is no marker the row with a price and photographs wins over the
stub.

#### Joe Salter — **Shipped**, and the first vendor with no pictures on purpose

**320 listings across four sections, and every single one is priced** — which
no other vendor here manages. $10–$54,995, median $795. OpenCart, the seventh
platform, reached with nothing but `?limit=` and `?page=`.

**It ships without photographs, and that is the vendor's decision.** Their
robots.txt is four lines and two of them are `Disallow: /files` and
`Disallow: /image`. Every product photograph OpenCart serves lives under
`/image/cache/catalog/…`, so the whole gallery is out of bounds. This crawler
obeys robots.txt, so the listings arrive with prices, descriptions and calibers
and no pictures. The alternative was not building it.

**The shop's own count is larger than the shop's own pages.** "Showing 1 to 15
of 116" sits above a page carrying **fourteen**, and reading all eight pages of
that section yields **102**. Asking for `?limit=100` yields the same 102 — so
the missing fourteen are not lost in pagination, they are counted by the
storefront and not rendered by it. The first version of this scraper used the
stated total as its stopping condition and lost a page per section to it. The
total is now read only to report the shortfall, and an empty page is the end.

**The catalog tile is already a whole listing** — stock number, title, price,
truncated description — so the detail fetch only replaces the truncation, and a
product page that fails costs a description and nothing else.

#### What the other four measured, before anything was written

| vendor | finding |
| --- | --- |
| **MCT Defense** | **Unblocked.** Its WooCommerce **Store API** answers: 139 products with prices and stock as JSON. The category page really is priceless — no price is in the HTML at all — which is what made it look like a dead end. Sixth vendor filed as unreachable that had an endpoint |
| **GunPrime** | Rails behind Phusion Passenger. `/tags/police-trade-in` is 46 KB with 27 prices **in the HTML**, so it needs no endpoint. robots.txt disallows only `/api`, `/cart`, `/checkout` and friends |
| **Simpson Ltd.** | The way in is the shop-by-category links — `/products/category/<Category>/page/N?subcategory=<Sub>` — but those are 2.8 KB React shells. The catalog is in **Firestore** (project `simpsonltd-bfd2b`); its rules refuse an unauthenticated read and anonymous sign-in is disabled. Still needs the browser |
| ~~**Southern Tactical**~~ | **Dropped**, on review: 36 KB of page carrying three prices, no endpoint found behind it, and nothing to suggest the catalog repays the work |
| **DK Firearms** | Held back deliberately, pending a decision on whether it is worth building |

#### The modern shelf — **Shipped**, and the armory is no longer milsurp-only

The question this raised was whether a *milsurp* catalog should name a Glock at
all. It should: four vendors here sell a police trade-in shelf beside the
surplus, and the armory was blind to all of it — Officer Store 0 of 14, Recoil
Gun Works 8 of 229, AIM Surplus 11 of 180.

**56 models and 12 makers**, measured against the stored catalog before being
believed: Glock 17 through 48 one row per number, the Sig P-series, S&W's M&P
line and service revolvers, the Remington 870 and 700, Mossberg 500/590,
Beretta's 92FS/PX4/APX/96, Benelli M4, IWI Zion, Ruger Mini-14, and the AR-15
and AR-10 platforms. Makers: Mossberg, Bushmaster, Daniel Defense, Armalite,
Stag Arms, LMT, JP Enterprises, IWI, DPMS, Windham Weaponry, Benelli, Kimber.

**+341 listings matched, 0 regressions.** Model coverage 41.3% → 48.8%; country
91.6% → 93.3%; caliber 89.2% → 90.2%.

| site | before | after |
| --- | --- | --- |
| Recoil Gun Works | 8/229 | **165/229** |
| AIM Surplus | 11/180 | **129/180** |
| Officer Store | 0/14 | **14/14** |
| Legacy Collectibles | 504/992 | 523/992 |
| Centerfire Systems | 414/914 | 425/914 |

**What makes a modern row dangerous here, and it is not what it looks like.**
The risk is not that a Glock is out of scope — it is that modern designations
collide with real service rifles. A bare `G43` alias matched a **Walther Gewehr
43** ("WWII German Walther 'ac 44' G43 Semi-Auto Rifle 8mm Mauser") and a bare
`G36` matched a **Heckler & Koch G36**, both of which are in this catalog.
Neither was caught by reading; both were caught by measuring what each alias
hit that was *not* a Glock. Every bare `G<number>` is now qualified as
`Glock G<number>`, which still catches "Glock G23 Gen 4" — the shape the bare
form existed for. `backend/tests/test_modern_shelf.py` fails if one comes back,
and also fails if two rows that can both match claim one spelling.

**A row states a caliber only where the designation settles it.** A Glock's
number encodes its cartridge, so those state one; a P229 was sold in three and
an AR-15 in more than this catalog has rows for, so those state none rather
than picking. The same rule the rest of the armory runs on, and the reason the
blank-filling is worth anything.

**Israel became a country the classifier can name**, because 27 active listings
say Israel or Israeli and the armory had nowhere to put an IWI row's origin. 15
listings gain a country and 27 more are corrected off Germany — an IMI Uzi, a
Jericho 941 and a Desert Eagle are not German.

**Everything arrived pending**, as everything in the seed file does: nothing in
it has been checked by the person running the site, so nothing decides anything
until they promote it. The numbers above are what promoting them does.

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

1. **A reference source for realized prices.** Asking prices are what this
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

- **Shipped** — PostgreSQL as an alternative backend, and the rule that keeps
  it working. See the section below.
- **Planned** — Move scans to a real queue (Celery/RQ or `arq`) so the scheduler
  and the workers can be separate processes.
- **Planned** — Prometheus metrics endpoint: scan durations, item counts, error
  rates.
- **Planned** — Structured JSON logging, for log aggregation in production.
- **Shipped** — Database snapshots, taken by the application itself: SQLite's
  online backup API or `pg_dump -Fc`, `backups/` gitignored. Taken by the
  scheduler on the age of the newest snapshot rather than on a timer, so a
  restart does not skip a day.
- **Shipped** — **The schedule is an administrator's, not a file's.** Whether
  snapshots are taken, how often, and how many to keep moved out of
  `config.yaml` into a settings row (migration 0015, seeded from the file) and
  onto a Backups page: a switch, two dropdowns, a **Back up now** button, and
  the list of what is on disk with sizes and ages. The outcome of the last run
  is recorded on the row, so a backup failing quietly for a week is visible
  where the setting is rather than only in a log.

  What did *not* move is `backups.directory`. Where files land is a fact about
  the machine, and a text box that can point the writer at any path on the
  server is a worse idea than a default nobody can change from a browser.

  It also retired the rule that development never backs up. That was right when
  the only way to change the setting was to edit the server's config — a
  scratch database should not fill a working tree with copies of itself — and
  wrong once it is a switch on a page. The prompt was this installation:
  development mode, PostgreSQL, real price history, and no backups at all. The
  upgrade seeds the switch off in development so nothing starts writing files
  nobody asked for.
- **Shipped** — **Stop is heard while a scan is waiting.** Pressing Stop on
  Checkpoint Charlie's appeared to do nothing for minutes at a time. The flag
  was set the moment the button was pressed; the run was not looking at it. A
  scan spends most of its life asleep — the politeness delay between requests,
  which reaches five minutes on a host that has refused at every slower pace,
  and the backoff between retries of a failed request — and both were a plain
  `time.sleep`, which is deaf. Every wait in a scrape now goes through
  `ScrapeContext.sleep`, which wakes four times a second to look at the flag
  and raises `ScrapeCanceled` as soon as it is set. The photo loop had the same
  shape and got the same treatment: a host pacing photographs a minute apart
  leaves that batch asleep almost all of the time.
- **Shipped** — **A warning is for something that changed.** Two conditions
  were making sites permanently PARTIAL over facts nobody could act on, and a
  site that is always PARTIAL teaches whoever reads the scan list that PARTIAL
  means nothing. A photograph that had already run out of retries was re-warned
  every scan: Classic Firearms' four recorded runs were four PARTIALs, all of
  them one BM-59 photograph whose file their own CDN has 404'd since 7
  September while their product page still links it — the other eleven are
  here. And a product page a shop refuses was warned about every scan: one
  Bowman Arms parts kit sits in a category restricted to signed-in customers,
  and their server says so in as many words. Both are now *said* rather than
  warned; both still warn on the run where they first happen, a run of refusals
  still stops a walk, and a 500 or a 429 is still a fault worth reporting.
  `ScrapeError` carries the HTTP status so the distinction is made on a number
  rather than on the text of a message.
- **Shipped** — A photo URL that does not serve a picture is dropped rather
  than queued forever. DuPage Trading's theme lazy-loads behind a BigCommerce
  Stencil placeholder, `…/img/loading.svg`, so 23 listings each carried a row
  pointing at that one URL; it answers `image/svg+xml`, and every scan
  re-counted them into "23 photo(s) have failed 3 times — run
  `make photos-retry`", which cannot work: retrying re-queues the same dead URL
  for the same answer. The scrape-time filter now drops the placeholder, and
  `FetchResult.discard` drops a row whose URL is provably not a photograph.
  Distinct from `permanent`, which is about the retry budget — a 404 may come
  back and an over-sized image really is a photograph the shop published, so
  both keep warning. All 23 listings had their real photograph throughout.
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

### PostgreSQL, and the rule that keeps both engines working — **Shipped**

SQLite is right for one machine and stops being right the moment more than one
process wants to write. It is not being retired: it is what a development
checkout uses, what the test suite builds on every run, and what a small
deployment should keep. So the engine is one block in `config.yaml`, and above
the ORM there is no second code path.

**The rule, which is the part that matters more than the port:** every schema
change works on both engines, and every migration is idempotent. Written up in
README.md under "Two engines, one schema", and checked rather than
remembered — `backend/tests/test_database_portability.py` scans
every migration file for the dialect-specific mistake, round-trips the whole
chain up/down/up on SQLite everywhere and on a real PostgreSQL when
`MILSURP_TEST_POSTGRES_URL` names one, and CI's **Migrations** job is now a
matrix over both.

Writing that test found four things that were already wrong, three of which
only PostgreSQL would ever have complained about:

* `server_default=sa.text("0")` on three boolean columns (`0008`, `0011`,
  `0014`). SQLite has no boolean and takes it; PostgreSQL answers *column is of
  type boolean but default expression is of type integer* and the chain stops
  at revision 8.
* `Item.title.like(...)` in the browse search. SQLite's `LIKE` ignores ASCII
  case and PostgreSQL's does not, so a search for "enfield" would have silently
  stopped matching "ENFIELD SMLE" — which is how most of these vendors write a
  title. Now `ilike`, which means the same thing on both.
* `price_changed_at.desc()` for the "Price reduced" sort. The two engines
  disagree about where a NULL goes in a descending sort — SQLite last,
  PostgreSQL first — so that sort would have led with every listing whose price
  has never moved. Now `.nulls_last()`.
* And one that was broken on **SQLite**, found only because the test runs both
  ways: `0011`'s downgrade dropped `manufacturers.status` and
  `merged_into_id` without dropping their indexes, and Alembic's batch mode
  rebuilds a table from what it reflects — so it recreated an index over a
  column that had just gone and the downgrade failed. A down-then-up of the
  chain could not complete.

Also fixed while in there: `alembic/env.py` unconditionally overwrote
`sqlalchemy.url` with the application's own, so anything trying to point the
chain at a throwaway database went to the real one instead. It did exactly that
once, to the development database, while this work was being written. A URL set
by the caller now wins.

**The move itself is two steps, because a migration cannot be one.** Nothing in
`alembic/versions/` can carry rows from one server to another — a migration only
ever changes the database it is connected to. So `scripts/dbupdate.py` builds
the PostgreSQL schema from the same chain that built the SQLite one, and
`scripts/sqlite-to-postgres.py` (`make db-import`) copies the rows. It reads
both databases through the same SQLAlchemy table definitions, which is what
makes the conversions right, refuses to run unless both are at the same
revision and the target is empty, compares every table's count afterwards, and
winds each sequence past the ids it carried over.

Measured on the development database: **39,299 rows in 1.1 seconds**, every
count matching. The application then ran on it — browse, facets, keyword
search, item detail with photos and price history, the armory with its merges,
saved searches, `cli.py sites`, `cli.py passwd` — and `pg_dump` produced a
4.1 MB snapshot.

One thing the move does not fix on its own: the scheduler still runs scans
in-process. PostgreSQL removes the single-writer ceiling, but running scans on
more than one machine still wants the queue below.

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
