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

**Where this stands: twenty-eight vendors read, none queued, six dropped.**
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
| [Checkpoint Charlie's](https://checkpointcharlies.com/) | `checkpoint-charlies` | WooCommerce, a product *tag* rather than a category. Detail comes from the **Store API**, a page of listings per request |
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
| [GunPrime](https://gunprime.com/) | `gunprime` | **Spree on Rails** — the collector and police trade-in shelves; their six firearm categories are a modern gun shop and are left alone |
| [Simpson Ltd.](https://www.simpsonltd.com/) | `simpson-ltd` | **Firebase Cloud Functions** — the Luger, military rifle, antique, German trainer and bayonet shelves of a 19,201-item shop |

### Planned

**This list is now also in the application.** `app/scrapers/planned.py` carries
the one vendor still queued, and the Sites page shows it under **Coming
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
Checkpoint Charlie's especially, whose detail arrives through the Store API,
so a section there costs its category pages and one request per page of cards.

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
| ~~**GunPrime**~~ | `/tags/police-trade-in` | **Spree on Rails** (Passenger) | **Shipped.** "No standard cards" was wrong — it is Spree's own markup, `data-hook='products_list_item'` with `id='product_N'` and the price in a `content` attribute. Read from the tags rather than the categories; see the section below |
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

1. **The WooCommerce Store API is not a shortcut past the catalog, but it is
   the right way to read detail.** Every shop here publishes
   `/wp-json/wc/store/v1/products`. Replacing the *catalog* walk with it is what
   it looks like it should be good for and mostly is not: filtering to a
   category, or reading past the first ten products, needs a query string — and
   Collectors Firearms disallows `/*?*`, against a catalog of 207,000 products,
   so an unfiltered walk is not an alternative.

   Reading *detail* with it is a different matter, and better than the product
   pages on every axis measured. The card already carries the product id, so
   `?include=` fills in a page of listings in one request; on Checkpoint
   Charlie's that is 13 requests and 90 seconds down to 2 and 8. It also returns
   **more text than the product page does** — median 399 characters against 143
   — because the prose lives in the *short* description and the theme renders
   only part of it above the fold. That is a quiet data-loss bug this group has
   had all along, and nothing about the scraped pages would have shown it;
   `store_api_details = True` is the fix, one vendor at a time, each measured.
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
| — | **Checkpoint Charlie's** | `/product-tag/cr/` | **Shipped** | A product *tag*, which renders the same loop and paginates the same way. This entry read "shipped, but barely" for a long time: their pages answered 429 to any pace and any headers, and a full run took 56 minutes to walk 24 listings and save 5. It was never rate limiting — their CDN refuses one specific user agent string — and it is now the fastest shop here, with detail read a page of listings at a time through the Store API. See "Not rate limiting" below |
| ~~1~~ | ~~J&G Sales~~ | — | **Shipped** | The HTML observation was right and the conclusion drawn from it was wrong. The catalog is rendered client-side, but the same WordPress install publishes the WooCommerce **Store API** — the whole catalog as JSON, with prices, stock, galleries and descriptions, and no browser. See `scrapers/woo_store_api.py`. The lesson is the one this section already draws about platform inference: what the HTML looks like is not what a site *is* |
| — | ~~MCT Defense~~ | `/product-category/firearms/` | **Dropped: wholesale only.** The entry URL was found and the Store API answers; see below |
| — | ~~DK Firearms~~ | `/product-category/surplus/surplus-firearms/` | **Parked — Cloudflare** | Moved to the bottom of the list deliberately. Not a rendering problem and not a scraping problem: the site answers plain HTTP with a `cf-mitigated: challenge` interstitial, so what is being asked for is a way *around* a bot check the operator switched on. Everything else in the queue is a site that will simply answer. **Dropped** on review: asking for a way around a bot check the operator deliberately switched on is not work this project wants to do |

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
| **Spree (Rails)** | GunPrime | `data-hook` attributes throughout, `SpreePaths` in a script tag; behind Phusion Passenger. Its taxon block states each product's own categories, which is what does the filtering |
| **PrestaShop** | Atlantic Firearms | **Base class shipped** (`app/scrapers/prestashop.py`). The most-visited site on the list, and still a class of one — which is the arithmetic the BigCommerce group got wrong, so it is worth saying plainly. The class is small and the shop is worth reading; a second PrestaShop vendor would be nearly free |
| **OpenCart** | Joe Salter | `OCSESSID`; not Shift4Shop |
| **WooCommerce (blocked)** | ~~DK Firearms~~, ~~MCT Defense~~ | See Group A. J&G Sales was here and shipped through the Store API; MCT Defense is dropped — wholesale only |
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
| ~~DK Firearms~~ | Cloudflare answers plain HTTP with 403 | Still true. **Dropped** — see above |

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

- **Shipped** — A substring index for the search box, on **both** engines.
  Migration 0034, a generated `items.search_document` column, `pg_trgm` on
  PostgreSQL and an FTS5 trigram table on SQLite. Measured over 11,038
  listings: **43-190ms per query before, 4.5-6x faster overall**, with the
  common single-term queries 10-80x — and **0 differences in the answers**
  across 39 queries on PostgreSQL and 28 on SQLite.

  **The roadmap asked for FTS5 and FTS5 was the wrong answer**, which the
  measurement said before any of it was written. A word index tokenizes, and
  this catalog tokenizes badly: `M1911A1` is one token, so searching "1911"
  lost 86 listings; `K98k` is one token, so "k98" lost 59; "8mm" lost 108. And
  `S&W` reduces under PostgreSQL's English configuration to the single token
  `w`, which returned **1,736 listings instead of 211**. Token search cannot
  match inside a word, and matching inside a word is exactly what this search
  box has always promised.

  So: trigram indexes, which **accelerate the existing semantics instead of
  changing them**. Both engines have one natively — `gin_trgm_ops` serves
  `ILIKE '%x%'` directly, and FTS5's `trigram` tokenizer does the same for
  substrings — so the two dialects differ in how the index is asked, never in
  what it answers.

  **One document, not six indexes.** The six searched fields are concatenated
  into a generated column, joined by a **newline**, which is the detail that
  makes this equivalent rather than merely similar: a space would let the
  phrase "germany rifle" match a listing whose country is Germany and whose
  category is Rifle, and neither field contains the phrase. A newline cannot be
  typed into the search box.

  Three things found by measuring rather than reasoning:

  * **Two-character terms take the old path on purpose.** A trigram index
    cannot serve them, and PostgreSQL will *try* — scanning the GIN index,
    narrowing nothing, rechecking every row it visited, at 91ms against 47ms
    for the plain scan. On SQLite it is worse than slow: FTS5 indexes nothing
    shorter than a trigram, so a two-character MATCH returns **nothing at all**.
  * **The first SQLite version was wrong in a way only a corpus test finds.**
    Both terms of a two-word query carried the same bind parameter name, so the
    second overwrote the first and "mosin german" executed as "german AND
    german". Building the subquery through SQLAlchemy rather than `text()`
    gives each clause its own anonymous bind.
  * **The column has to be unwritable.** Mapped as an ordinary column it went
    into every INSERT, which a generated column refuses outright — 239 failing
    tests. `FetchedValue` is what says the database owns it.

  Degrades rather than breaks. A database between installing the release and
  running its migration, or a PostgreSQL whose role may not `CREATE EXTENSION
  pg_trgm`, falls back to the original six-column scan — which is the old
  behavior exactly, and therefore a safe thing to land on rather than an error
  to raise.
- **Shipped** — Price filter in the browse rail: a histogram, two handles and
  two number boxes. The roadmap line asked for a slider "rather than free-text
  min/max" and was wrong about the starting point — **there was no price
  control on screen at all.** `min_price` and `max_price` have been on the API
  since the beginning and nothing in the rail ever set them.

  **The scale is logarithmic, and that is the whole reason it works.** This
  catalog runs from a $2 clip pouch to a $750,000 Gatling gun, so on a linear
  axis every listing but a handful lands in the first column of the histogram
  and the first pixel of the track. Log-spaced, the shape is legible: a clean
  peak between $242 and $708 holding 3,582 of the 10,900 priced listings, with
  the tail visible and not dominating. The handles move linearly in pixels
  while the value moves by ratio, which is how prices are compared — $200 to
  $400 is the same kind of step as $2,000 to $4,000.

  **The histogram ignores the price filter itself**, for the reason the kind
  facet ignores the kind — and more sharply, because this one is a slider.
  Shaped by its own setting it would redraw as only the slice you chose, and
  there would be nothing left on screen to widen back towards.

  Native `<input type="range">`, two of them on one track, because a
  hand-rolled slider is a keyboard trap waiting to happen and these arrive with
  arrow keys, Home/End and a screen-reader contract already written. The number
  boxes stay and stay authoritative: they take a figure somebody already has in
  mind, and the slider is a faster way to the same two values rather than a
  replacement. Dragging commits on release, not per pixel.

  Three smaller decisions, each because the obvious version misleads. A handle
  at the end of the track means *no bound* rather than "the cheapest listing in
  the catalog today". Values are rounded to something a person would type —
  $417.8231 makes the box look broken — on a step that grows with the number.
  And listings with no price at all are counted in the note rather than
  silently excluded, because "call for price" is common in the trade and any
  range sets them aside.
- **Shipped** — "Similar listings" on the detail page. The price spectrum
  above it answers "is this a good deal?" and stopped one step short: it says
  *cheaper than 8% of them* and offered no way to reach the them, so a reader
  told their rifle was dear had to retype the model into the search box.

  **Graded, not boolean**, and every row says which band it came in on — the
  same model and cartridge, the same model in another cartridge, the same
  cartridge from the same country, the same cartridge. A list that mixed the
  same rifle at another vendor with a different rifle in the same round,
  unlabeled, would be worse than useful. The order is the value order, and the
  cartridge is the spine: it is nearly always stated, nearly always right, and
  a buyer will not cross it, so country and maker only ever narrow within it.

  Two things it took measuring to get right:

  * **The bands exclude each other in SQL**, rather than being deduplicated
    afterwards. They are nested by nature — every "same gun" row is also a
    "same cartridge" row — so a row the closest band's LIMIT cut off turned up
    in the next one wearing the wrong label: twelve K98ks and a limit of ten
    produced two K98ks announced as "the same model, another cartridge".
  * **Two slots are held back for the wider bands.** 3,978 of 8,690 active
    firearms — 46% — sit in a model-and-cartridge group of nine or more, so
    without it the list is *entirely* the same gun on nearly half the catalog.
    Held back rather than fixed: a gun nothing else resembles still gets a full
    list. A CZ75 page now offers six CZ75s by price and then a CZ85 and a
    CZ75BD.

  Accessories are excluded wholesale rather than band by band — a bayonet that
  fits an 8mm Mauser is not an alternative to the rifle, and the cartridge on
  it is the rifle's anyway.

### Watchlists and notifications

- **Shipped** — Per-user watchlist: star a listing, hear when its price moves
  or it sells, and name the price you would pay. A monitor you have to visit is
  half a monitor, and this is the half that was missing — the catalog could say
  what was on the shelves and whether a price was good, but not "tell me when
  *that one* moves", which is the question somebody has about the rifle they
  have decided they want and will not pay this week's price for.

  **What counts as news is defined once**, in `services/watchlist.py`, and used
  by both the digest that mails it and the page that shows it — two copies of
  that rule would disagree eventually, and the disagreement would be silent.
  Sold and de-listed outrank everything, then a target reached, then ordinary
  movement.

  **A target is a promise to stay quiet.** Naming $700 means "do not tell me
  until then", so a rifle drifting $900 → $925 says nothing — while a sale
  still does, because that is about whether there is a rifle at all rather than
  what it costs.

  It reuses the digest's own `since` watermark rather than storing a last-
  notified price. A second clock is one more thing to keep wound, and it would
  disagree with the digest's the first time an email failed to send.

  The star is a *state*, not an event: `PUT` rather than `POST`, so clicking
  twice leaves one watch, and the same call sets a target on something already
  starred. The watch travels on the item detail response rather than being
  fetched separately, so it paints in its true state — a second request means
  an empty star for a moment on a listing somebody is watching, which reads as
  having lost the watch.

  A watchlist is now reason enough to send a digest on its own: somebody
  following one rifle and no sites at all has asked a narrower question, not a
  smaller one. The section goes first in the email, above new listings and
  price reductions — those are the catalog talking, this is the answer to
  something the reader asked.
- **Shipped** — Price-target alerts that do not wait for the digest. A rifle
  reaching $700 an hour after the daily digest sends was news twenty-three
  hours later, and on a shelf where one rifle is one rifle that is often too
  late. Opt-in per watch, and offered only where a target is named: "tell me
  the moment it reaches nothing" is not a request.

  **The alert itself fetches nothing.** It reads the database on every
  scheduler tick (60s) and mails what it finds, so it is exactly as fresh as
  the price it reads. On its own that halved the worst case — from about 48
  hours (a day for a scan to notice, a day for a digest to mail) to about 24 —
  and the entry below closes most of the rest by re-reading watched listings
  every two hours instead of waiting for their catalog scan.
- **Shipped** — Watched listings are re-read on their own clock, every two
  hours, against catalogs scanned once a day. A watchlist is tens of listings,
  so this is a few requests an hour against shops that take thousands during a
  single scan — the cost is negligible *because it is one page per listing*.

  **The expensive part turned out not to be needed.** The plan was a
  single-product price parse per platform, nine of them. What the shops
  actually needed was **three generic layers on the base class**, because what
  a shop publishes depends on its *theme* rather than its platform — six
  BigCommerce shops publish schema.org and a seventh publishes only a meta tag,
  and Royal Tiger is not registered as a WooCommerce shop at all yet serves
  WooCommerce product pages.

  | layer | shops |
  |---|---|
  | schema.org `Product`/`Offer` | 12 |
  | Shopify per-product `.js` | +2 |
  | Open Graph / `itemprop` meta | +5 |
  | WooCommerce price markup | +3 |

  **Twenty-two of twenty-eight**, verified against a live product page from
  every shop: twenty-one matched the stored price exactly and the twenty-second
  was the poller working — Recoil Gun Works had reverted a sale after the last
  scan, and the check found $399.99 where the database still said $369.99.

  Two shops came free that were not expected. **Royal Tiger** needs a headless
  browser for its *catalog* and serves ordinary server-rendered WooCommerce
  product pages, so it can be polled over plain HTTP; **Checkpoint Charlie's**
  had merely been in cooldown during the first survey.

  **A shop that publishes nothing is skipped, not guessed at.** Those keep the
  freshness their scan gives them. Reading a price out of theme markup would
  eventually mail somebody about a rifle that is not on offer, which is worse
  than telling them a few hours late. Six are in that state, and two of them
  structurally: Hunter's Lodge has no product pages at all — its listings are
  OCR of one scanned magazine advertisement — and eBayonet is five
  hand-maintained pages of prose with no storefront behind them. AIM Surplus
  and Simpson Ltd. render their prices client-side; Empire Arms publishes
  `<font class="auto-style40">. . $695.</font>` and Joe Salter an unclassed
  `<h2>`, either of which could be parsed and neither of which could be
  trusted to keep meaning the same thing.

  **The WooCommerce layer earned its caution twice.** Royal Tiger first
  returned **$0.00** — the theme renders its header mini-cart with the very
  same CSS class, and an empty cart says zero. A zero would have read as the
  largest price drop in the catalog and been mailed to every watcher of that
  rifle. The same page also carries $29.99 and $199.99 in related-product
  headings. So the search is scoped to the product summary rather than the
  document, a zero is refused outright, and a discounted product's struck-
  through `<del>` price is passed over in favor of the `<ins>` one: reporting
  a price the shop is not charging is the one mistake that matters to somebody
  waiting on a number.

  It reads through `ScrapeContext` like everything else, so robots.txt, the
  cooldown register and the politeness delay all apply — this is now the most
  frequent thing the application does and would be the first to earn a block
  otherwise. A price it finds is stored in the same columns a scan writes, with
  a `PriceHistory` row carrying **no** `scan_run_id`: this did not happen
  during a scan, and inventing a run to point at would put a lie in the scan
  history to keep a foreign key company.

  Measured end to end against five live listings: five checked, four prices
  read and every one matching, one skipped, nothing failed.

  **The alert has its own watermark, and it is a price rather than a time.** It
  fires between digests and so cannot use `last_digest_cutoff` — without a
  memory of its own it would mail the same $650 on every scheduler tick until
  somebody bought the rifle. A price is the right shape because the question an
  alert asks is "is this a number I have not told you about", so a vendor who
  puts a price back up and drops it again has genuinely done something worth a
  second email, where a timestamp would have said "already mentioned".

  Out of band in the way "Send now" on a saved search is: it touches neither
  `next_send_at` nor `last_digest_cutoff`, because an alert is not the digest
  arriving early and moving the watermark would swallow the week's new listings
  to deliver one price. It ignores `enabled` too — that flag answers "send me a
  digest on a schedule", and asking to be told the moment a rifle hits $700 is
  a different request made per watch.

  Dispatched on the scan cadence rather than the digest one, since what makes
  an alert due is a price changing and that happens when a scan finds it. The
  watch is marked only after the send returns, so a failed email is retried on
  the next tick rather than recorded as delivered. Its subject names the
  listing and the price: "3 new listings" in a notification shade is not what
  somebody who asked to be interrupted at $700 needs to see. A sold listing is
  never alerted about — the digest carries it, but it is not a buying
  opportunity, and interrupting somebody to say they missed one is the wrong
  side of useful.
- **Fixed** — Checkpoint Charlie's, and it was never about them. The planned
  entry said to make it work or take it out, and offered three options — find a
  pace it tolerates, write to the dealer, or delete it. All three were wrong,
  because every one of them assumed the refusal had something to do with how
  much we were asking for.

  **The cause was our user agent.** They sit behind Hostinger's CDN, and the
  CDN was refusing one exact string: `X11; Linux x86_64` together with
  `Chrome/124.0.0.0`, which is the stock user agent of headless scraping
  tooling. Either half alone passed — Linux with a current Chrome was fine,
  Windows with Chrome 124 was fine — so it was a signature match, not a
  judgment about robots.

  Four measurements took it apart, and each one killed a theory:

  * **A single request was refused.** Not the tenth, not the hundredth: the
    first, with nothing before it. No pace can fix a limit that starts at one,
    which retired "find a pace it tolerates".
  * **The 429 had an empty body, no `x-powered-by` and no `x-litespeed-cache`
    header**, where the working pages had all three. It was generated at the
    edge. Their server never saw any of it, so writing to the dealer would have
    asked them about traffic they had no record of.
  * **The same URL answered 200 and 429 depending on the cache.** A cached
    category page came back 200; the identical URL with a cache-busting query
    came back 429. That is what made it look like a rate limit for months — the
    catalog was being served from cache and everything else was hitting the
    rule.
  * **Alternating user agents, seconds apart, on the same URL**: ours 429,
    Firefox 200, ours 429, Firefox 200.

  The agent now says what it is —
  `Mozilla/5.0 (compatible; MilsurpMonitor/1.0; +https://milsurpmonitor.com)`.
  Honest, it cannot go stale the way a pinned browser version does, and it
  gives a vendor something to allow or refuse deliberately and an address to
  complain to. **Verified against all 28 shops with the canary before the
  change was made**: every one answered, and Checkpoint Charlie's went from
  `RESTING` to `ok 3 in 1.3s`.

  `backend/tests/test_user_agent.py` pins it, including the sample config —
  which sets the value explicitly, so an installation copying it would get
  whatever that line says whatever the code default is.
- **Shipped** — Read Checkpoint Charlie's detail through the WooCommerce Store
  API instead of their product pages. A WooCommerce card already carries the
  product id — it is the `post-N` class the external key is built from — so a
  whole page of listings can be filled in with one `?include=` request instead
  of one product page each. `store_api_details = True` on a scraper turns it
  on; `WooCommerceScraper._detailed()` asks the batch first and falls back to
  the old path for anything it cannot answer.

  Measured against the live site, one section, the same twelve listings:

  | | requests | time | median description | images |
  | --- | --- | --- | --- | --- |
  | product pages | 13 | 89.9s | 143 | 152 |
  | **Store API** | **2** | **7.9s** | **399** | 152 |

  **The description is the part worth noticing, not the speed.** The prose these
  shops write lives in WooCommerce's *short* description, and the theme renders
  only part of it above the fold — so every description scraped from a product
  page has been quietly losing most of its text, on every WooCommerce vendor in
  the list, for as long as this has run. The scraper now takes whichever of the
  two fields is longer, which is the short one on this vendor and could be the
  other one elsewhere. Image totals are identical, which is the check that the
  two paths are reading the same thing.

  Only Checkpoint Charlie's has the flag on. It applies to most of the vendors
  here and each one should be measured the same way before being switched — the
  before-and-after this file asks of every other entry. `backend/tests/
  test_store_api_details.py` covers the batching, the longest-field rule, the
  per-listing fallback, and that a shop without the flag never calls it.
- **Fixed** — A product-page refusal can no longer end a scan. The cooldown
  register is keyed by **host**, and the evidence that fills it is often
  path-specific: a shop whose catalog answers 200 and whose `/product/` pages
  refuse publishes a host-wide pause, and the *next* section's first catalog
  page then raised `HostResting` — which `_stream` correctly treated as fatal,
  because a section that yielded nothing is a failure rather than a partial
  result.

  That is how Checkpoint Charlie's produced 9 failed scans against 1 partial
  while the scraper's own `MAX_DETAIL_FAILURES` logic was working exactly as
  designed. The user agent fix removed that trigger; this removes the
  fragility, for the next vendor that serves a catalog and refuses detail
  pages.

  `_walk` now catches `HostResting` and treats it as *our* decision rather than
  the vendor's refusal of that page: the section is marked not-read, the
  listings already collected are kept, and the walk moves on. A scan in which
  **every** section was skipped this way still fails loudly — with a message
  saying so, and saying that nothing was de-listed — because a silent empty
  scan is the outcome worth being afraid of. `backend/tests/
  test_resting_sections.py` covers both halves.
- **Shipped** — Web push notifications, as an alternative to email for the one
  thing worth interrupting somebody over. Migration 0035,
  `app/services/webpush.py` (the two RFCs), `app/services/pushnotify.py` (the
  application), a service worker, and a panel on the Security page.

  **Written against RFC 8291 and RFC 8292 rather than added as a dependency**,
  which is the call the two-factor code made against RFC 6238 and for the same
  reasons: the Debian package vendors everything, `pywebpush` brings a
  transitive tree for work that is a hundred lines of `cryptography` calls, and
  the subtle parts — the exact info strings, the record delimiter, the JOSE
  signature encoding — are subtle whoever writes them. The primitives are not
  hand-rolled: P-256, HKDF, AES-GCM and ECDSA all come from `cryptography`.

  **What makes that safe is the cross-check.** The tests seal a message with
  our code and open it with `http_ece`, an independent implementation of the
  same RFCs, held as a development dependency and never shipped. A round trip
  against ourselves would have agreed with whatever we had misread.

  **`cryptography` was not actually a dependency**, which is the trap that
  would have shipped. It was in every development virtualenv because semgrep's
  `pyjwt[crypto]` pin drags it in, so everything worked here — and `pip install
  -r requirements.txt` on a clean machine did not install it, so the package
  would have shipped a venv where every push raised ImportError. Now declared.

  Three decisions worth the words:

  * **A subscription belongs to a device, not an account.** The same person on
    a phone and a desktop has two, and a reinstalled browser has a new one.
  * **Either channel counts as delivered.** Push runs alongside the email
    rather than replacing it, and marking the alert on either means an
    installation with no SMTP can finally be told about a price — where before
    it would re-send the same alert on every tick forever.
  * **A dead subscription is deleted, not retried.** 404 and 410 are the push
    service saying the browser is gone and there is no second opinion worth
    having; anything else is counted, and eight consecutive failures ages it
    out, because a message sent into nothing forever is worse than a row nobody
    misses.

  `milsurp secrets` generates the VAPID pair, and **inserts the settings into a
  config file that predates them** — refusing would have made the command fail
  on every already-installed machine, which is all of them.

  The **Send a test** button is not a nicety. Four things must line up —
  browser support, a secure origin, permission, a registered service worker —
  and when one is wrong everything still looks right: the switch says On and
  nothing ever arrives. One notification landing is the only proof worth
  having.

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

#### Designations the queue could not see — **Shipped**

The catalog has grown past 10,900 listings and 8,774 firearms, of which **3,775
(43%) match an armory model**. Running the discovery pass over the other 4,999
proposed **ten**. Not because the armory is complete — because `DESIGNATION` was
written for `M91/30`, `K31` and `No.4 Mk.I` and is blind to how the collector
trade actually writes a gun. Four shapes were added after measuring each against
the live catalog:

- **One letter and two or three digits** — `C96`, `P38`, `G43`, `P210`. 98
  Mauser C96s sat unlinked because the letters branch wants two letters and the
  `P\.?\d{2}` branch could not reach three digits.
- **Letters, a space, digits** — `DSM 34`, `KKW 34`, `AB 63`, `ZFK 55`. The
  space is the whole point; `DSM-34` was the only form that matched. This one
  cost something: allowing the space turns any short capitalized word before a
  number into a designation, so `CASE 45`, `AUTO 22`, `LINE 32` and `WITH 2`
  joined the stop list.
- **A pattern year carrying its update** — `1896/11`, `96/11`, `06/24`. The
  slash is what makes it a designation rather than a date. A trailing-slash
  guard came with it: `WF BERN 96/11` was yielding `BERN 96`, because the
  letters branch starts further left and so wins.
- **The prefix vocabulary read case-insensitively**, plus `Modele`, `Modelo`,
  `Mle`, `wz.` and the American ordnance `Model *of* 1917`. 106 listings gained
  a designation, and the vendors who write a whole title in capitals are exactly
  the ones whose titles are terse enough to need it.

**And the bare year, which is not a shape at all.** The Swiss, Swedish and Luger
trades name a gun by the year its pattern was adopted and nothing else — `WF
BERN 1911`, `CARL GUSTAFS 1896`, `DWM 1906` — and 944 listings here are written
that way. A four-digit number has no shape that tells it from a date, so
`year_candidates` is context instead: the year must be one a gun could be
*named* for (1800–1945; everything later in this catalog is a date of
manufacture), a firm's name must sit immediately to its left by the same
walk-back the maker rule uses, no date word may follow it, and — as with a
maker — the same name must turn up in two different listings. That threshold
drops 207 one-off candidates and keeps 92. The maker stays in the proposed name
on purpose: a bare `1911` would match every Colt automatic in the catalog and a
bare `1896` would match a serial number.

Of the 4,999 unlinked firearms, **1,375 now offer a designation shape and
another 949 a corroborated maker-and-year**. One pass proposed 307 models, 27
makers and 2 calibers, all pending. See `services/discovery.py`.

#### Which firms build which model — **Shipped**

857 approved models and **743 with no maker at all**, because the table had
never been populated past the seed. The rule for what to attach was already
written, in `_model_rules`:

```python
manufacturer=(row.manufacturers[0].name if len(row.manufacturers) == 1 else None),
```

One firm fills the blank; several state nothing. So a Ruger 10/22 gets one row
and an AR-15 gets eight — Colt, DPMS, Rock River, Bushmaster, Ruger, Delaware
Machinery, Armalite, Wolf — and correctly declines to guess which built the one
in front of you. Populating it was the work, not designing it.

**The catalog answers it.** For each model, the maker is re-read from its
listings' own text — never the stored column, which may have been filled *from*
the model. Three rules, in order of confidence: the model's own name says it
(96 models); one firm is named in 60% of the listings that name anything and a
fifth of all of them (194); otherwise every firm named twice is a builder (22).
That leaves 292 for a human, all of them under eight listings — a long tail
rather than the main event.

**Three things in the manufacturer table had to go first**, or the pass would
have cemented them:

- **`Luger`, `Tokarev` and `SKS` were approved firms.** Luger's spellings
  included `P08`, Tokarev's `TT-33` — so the cartridge "9mm Luger" was naming a
  maker, which is how `CZ75` came out as `Luger 19, CZ 10`. SKS is a model. All
  three disabled rather than deleted, and **779 listings** stopped being
  attributed to Luger. DWM, Mauser and W+F Bern built those pistols.
- **`WF BERN` and `Bern` were two rows for one Swiss arsenal**, both with no
  country, which is why the K11 looked like it had two makers. Merged, renamed
  `W+F Bern`, country Switzerland.
- **The year rule made duplicate rows**, not aliases: four separate models for
  one 1929 W+F Bern, three for the Swedish m/96, and `Remington 1903` beside the
  M1903 Springfield that already knew everything. Merged by hand.

**By hand, and that is the finding.** The automatic version of the last one
grouped by (firm in the name, trailing year) and wanted to fold the Swiss
Vetterli M1878 into a Colt revolver, the Springfield Trapdoor into a Winchester
1873, and J.P. Sauer & Sohn into SIG Sauer. Same year is not the same gun, and a
merge is the one armory edit whose undo is an archaeology exercise.

Firearms now carrying each fact: **maker 8,027 of 8,781 (91%)**, caliber 95%,
country 93%, model 5,898 (67%).

#### Zero-listing models, and why most of them stayed — **Shipped**

66 approved models accounted for no listing at all. The split decided what to
do with them: **17 came from the shipped seed and state three or four facts
each** — Glock 29/32/33, S&W Model 19 and 36, Benelli M4, ZB26 — and are simply
guns nobody stocks this month, which is what a reference table is for. The other
**47 came from discovery and state nothing at all**.

37 of those are now disabled, under a rule worth stating because it is what
makes it safe: **every listing they match is already won by a better row**, so
switching them off changes no listing's answer. `M13` loses to `P7`, `RED 9` to
`C96`, `Model 49` to `FN-49`. Five more are named only by bayonets and
scabbards (`M8A1`, 21 accessories), and four are mangled names of the year
rule's own making — `Taylor's Company 1860` and `J.P Sauer Sohn 1913` match
nothing because the maker walk-back drops an ampersand.

Disabled rather than deleted, and the safety property was measured rather than
assumed: a disabled row spawns no duplicate on the next pass, adds nothing to
the pending queue, and still blocks the name being proposed again, because
`propose_model` looks a name up regardless of status.

**Ten were deliberately left alone**, because switching them off would have
cemented a wrong answer rather than a harmless one. Each is a *conversion* of
the pattern it was losing to — an 1871/84 is the repeating Mauser and an 1871
the single-shot, a 1909/47 is the Argentine rebuild, a VZ52/57 is the 7.62x39
conversion — and a conversion's designation always contains its base, so the
base matches too and wins the tie. They have their kind, country and cartridge
now, read off their own listings, and a `position` ahead of the base. Eleven
designations that resolved to the wrong row now resolve to the right one, and
the bases still win their own listings.

`Zastava M59/66` was the same shape without the slash: it and the generic `SKS`
both knew four things and both sat at position 1000, so the tie fell through to
the row id and the older, Russian `SKS` won — filing 14 Yugoslav carbines as
Russian.

**A maker who built both settles nothing** — fixed. `classify.stated_kind` read
the bare word "Mauser" as saying *rifle*, because the maker is in
`RIFLE_PATTERNS` and the fallback runs whenever a title carries no type noun.
787 titles were decided that way and **230 of them are handguns**. The cost was
not the flag but `_contradicted`: a Mauser pistol whose model row states a
handgun kind had the whole match discarded — caliber and maker with it — so
Model 1914s, HScs and M1910s came back carrying no model at all.

`_break_the_tie` already refused to let `_AMBIGUOUS_MAKERS` outvote a model
designation; `stated_kind` now applies the same rule at the other end, where
*unopposed* is not the same as *decisive*. It has one caller, `_contradicted`,
so the blast radius is exactly the bug. 58 listings gained a model they had
none for and 14 moved to a better one — `Mauser Model 1934` to `M1934`,
`MAUSER P.08 BYF 41` to `Luger P08`, `Model 1914/34` to its own row — and
nothing regressed.

#### The armory's three properties, re-measured and then pushed — **Shipped**

Re-running the measurement above over 10,886 active listings, then acting on
each of the three things the armory actually does.

| contribution | first measured | before this pass | after |
| --- | --- | --- | --- |
| caliber spellings normalized | 31.9% | 16.2% | 16.3% |
| blank country filled from the model | 10.4% | 13.1% | **22.1%** |
| rifle/handgun settled by the model | 31.4% | 28.9% | **46.7%** |
| …where that *changed* the text's answer | 1 | 3 | 4 |
| blank manufacturer filled | 1.8% | 0% | 0% |
| blank caliber filled | 1.4% | 7.5% | **11.6%** |
| model rows that say nothing at all | 54% | 44% | **3%** |

**Filling blanks, which the first measurement found at 1.5%, is now 33.7%** —
and the whole of that came from filling model rows rather than from matching
more of them. Model coverage barely moved (54.3% → 54.2%); what changed is that
a match now tells you something. 405 rows were given a kind, 402 a country and
435 a caliber, every fact read off the listings the row already accounts for and
only where they were unanimous. Form coverage went 76.2% → 79.9%.

**Two of the fills were overreach, and the repo's own tests caught both.**

- A caliber read off the listings is not the same claim as a caliber the
  *designation* settles, and for a modern civilian design the two come apart.
  Every AR-15 in this catalog happens to be 5.56; an AR-15 is 5.56, .223 Wylde
  or .300 Blackout depending on the upper. Nine such rows say nothing again.
- The shipped file requires that a row carrying a kind carries a country, on
  the reasoning that a kind cannot be guessed from a title and so marks a row
  somebody judged. 105 rows had gained a kind and no country. 60 found one —
  from their listings, or failing that from their maker, which is the weakest
  answer and asked last everywhere else — and **45 gave the kind back** rather
  than ship half-curated.

**The manufacturer fill is 0 and structurally so.** All 4,475 listings matched
to a single-maker model already name that maker in their own text, because the
model→maker links were derived from exactly the text `manufacturers.extract`
reads. The links earn their place in the armory UI and on listings yet to
arrive; they will never show up in this column, and reporting them as a
contribution would be taking credit for a circle.

**Normalizing was the property with the least headroom and still had some.**
310 active listings carried a caliber the table could not spell — and the cause
was not missing aliases but unfinished bookkeeping: `22 Caliber` and `22 CAL`
were marked merged into `.22 LR` without their spellings ever reaching it, so
272 Simpson listings sat in the browse filter as their own entry. Merging them
into `.22 LR` would also have been wrong: 213 of the 272 name nothing finer
than the bore. They are now `.22 Caliber`, a bore row with the bare forms as
aliases, which is what the "N Caliber" rule says to do when there is no dotted
base to merge into. With that, two duplicate rows folded away, a pending
`6.5x53mm Daudeteau` approved, `7.92x94mm Patronen` added and 34 alternate
spellings filled in, **310 unnormalized listings became 37** — and all 37 are
the cases previously ruled ambiguous on purpose (`30 Caliber`, `32`/`38
Centerfire`, `577/45`).

**A telescopic sight is written exactly like a metric cartridge.** "a bushmaster
4x32 scope mounted", "ajack 4x90 m/43 scope", "a nightforce nxs 2.5-10x32
scope" — 29 listings took one as their caliber. Nothing in the number separates
them, so `_metric_caliber` reads the word beside it: the real ones say "8x52r
*cartridge*". The window is twelve characters and deliberately not wider, because
at twenty it catches two more scopes and also throws away the Siamese Mauser's
8x52mm, whose description reads "cartridge, rear *sight* base". 29 down to 7,
and four of those seven were real cartridges the table simply did not know.

**Enfield and Mannlicher were tried on `_AMBIGUOUS_MAKERS` and backed out.**
Both are genuinely ambiguous — the No.2 Mk I is the British service revolver,
the Mannlicher M1894 a blow-forward pistol — but adding them changed **not one
model match**, because the eight unmatched Enfield revolvers have no armory row
to match in the first place. The cost was real: `\benfield\b` is the only rifle
signal in "British Enfield No.4 Mk.I .303", so 51 Lee-Enfield titles would have
stopped saying "rifle" and `_contradicted` would have lost its guard on them.
Zero benefit for a real cost is not a trade. Those revolvers want a model row.

#### The armory page keeps its place — **Shipped**

The eye on each armory row leaves the page, and the armory holds a tab, a
Showing filter, a sort, a search box and often a half-finished edit. Opening the
listings in a new tab was the obvious fix and does not work here: the bearer
token lives in `sessionStorage` — deliberately, so a forgotten session on a
shared machine dies with the tab — `sessionStorage` is per-tab, and a browser
copies it into neither a plain `target="_blank"` tab nor one opened with
`rel="noopener"`. Both were measured; both came back `null`, and the new tab
landed on the sign-in screen.

So the state went into the URL instead, where the tab and the Showing filter
already lived. The sort is now `?sort=key` or `?sort=-key` and the search
`?q=`, both derived from the address bar rather than mirrored into React state
— the property this page already insisted on, because a `useState` beside the
URL gives one fact two sources of truth and Back moves one of them. Two
consequences fell out for free: switching tabs drops the sort in the *same*
navigation, so one Back undoes the whole move, and each history entry now
carries the sort belonging to it, which is what an effect resetting the sort on
every tab change used to paper over. The search replaces rather than pushes, so
six keystrokes do not become six history entries.

#### A model's facts describe a gun — **Shipped**

`M1935` is a Beretta pistol in .32 ACP. It is also the Turkish and the Austrian
M1935 bayonet, and asking for .32 ACP in the browse filter returned blades. The
listings were typed correctly — not a rifle, not a handgun — and took the
pistol's caliber, maker, country and model link anyway.

**704 non-firearm listings were carrying an armory model**: 103 under the AK-47,
62 under the Luger P08, 41 under the M1917 Enfield. 240 of them had taken a
caliber from it, 189 a country and 105 a maker — a `GERMAN K98K BAYONET` filed
as a Mauser, a `TURKISH M1935 BAYONET` filed as a Beretta in Italy.

The rule already existed for the *kind* and is now the whole of `fill_in`: the
armory knows what a model is, it does not know whether this listing is selling
one. A listing that is not a firearm is offered nothing from the row it matches.
Its own caliber still comes back normalized, because that is spelling rather
than knowledge and a box of .32 ACP ammunition really is in .32 ACP.

Two things followed:

- **A bayonet has no caliber of its own.** The cartridge in its title is the
  rifle's — `1891 Carcano Bayonet`, `NORWEGIAN M1 GARAND BAYONET`, `CZECH VZ24
  MAUSER BAYONET` — and the classifier was reading it, which put 89 blades into
  the caliber list independently of the armory. A caliber the *vendor* put in a
  field of their own is still kept; a parts kit keeps its caliber either way,
  because a 9mm Sten kit really is 9mm.
- **`reclassify --recompute` can now clear a field, not only change one.** Every
  recomputed field but the maker ended in `or item.<field>`, so the wrong answer
  was the one thing a rebuild could never reach. The fields nobody names in
  `--fields` are still protected by the filter that puts the stored value back.

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
  which is the check to make while doing it — and the models under an expanded
  maker carry the same eye, so checking whether a firm really built something
  no longer means opening the row, reading its name, switching tabs and finding
  it again.
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

#### GunPrime — **Shipped**, and the vendor's own taxonomy does the filtering

**Spree on Rails, the eighth platform**, behind Phusion Passenger. No browser,
no endpoint hunting: `id='product_N'` is a stable key and the price is in a
`content` attribute rather than only in the rendered "$349.00".

**The scope is the two tags, not the six categories, and that is the decision
worth recording.** `/categories/firearms/*` is about 1,300 listings of Del-Ton
AR pistols, Kahr P9s, Mossberg Shockwaves and suppressors. Reading it would
repeat exactly what Arms Unlimited and Century Arms were backed out for — 97
listings that landed correctly and none of which belonged here.
`/tags/collectible` is a Colt Python, a matching Mauser P.08 Luger and a
Waffenamt Browning Hi-Power; `/tags/police-trade-in` is the shelf four other
vendors here are already read for.

**The police tag is 35% not-a-firearm** — ammunition, magazines, duty holsters,
a weapon light — and none of that had to be guessed from a title, which is how
bayonets ended up under Rifles elsewhere. Every product page states its own
taxons, in a block Spree hooks separately from the site navigation:

| taxon | what it is |
| --- | --- |
| `categories/firearms/pistols/semi-auto-pistols` | a gun |
| `categories/ammunition` | a box of cartridges |
| `categories/accessories/firearm` | a duty holster |

A listing is kept when its own categories put it under firearms, and the same
block hands over `manufacturer/glock` for the maker at no extra cost.

**The photographs need a configured exception, like Joe Salter's.** robots.txt
disallows `/rails/active_storage/*`, which is where every product image is
served from. The page also carries a presigned
`gunprime.s3.us-east-2.amazonaws.com` URL for each photo, on a host with no
robots.txt of its own — it answers 403, which this crawler reads as *off
limits*, not as permission. Taking those to sidestep the rule on the vendor's
own domain would be circumventing it, so the scraper reads the
`/rails/active_storage/` form and asks `ctx.allowed()`. Those URLs redirect to
the same S3 object and reissue the signature, which is the other reason to
prefer them: the S3 signature expires after seven days and a queued photo would
not survive a weekend.

#### MCT Defense — **Dropped: wholesale only**, and a note here was wrong

This sat in the queue as *"Unblocked: the WooCommerce Store API answers, 139
products with prices and stock as JSON, the same route J&G Sales shipped on."*
Half of that was right and the important half was never checked.

The Store API does answer. **But 257 product rows across all five categories
carry 0 prices between them** — every `prices.price` is the string `"0"`,
`is_purchasable` is false throughout, `price_html` is empty, and the product
pages carry no dollar figure anywhere. The rows are not individual guns either;
they are model groups: "Beretta 84 Model Pistols", "Israeli Surplus/Used
Pistols", "Zastava Yugo M72 RPK Rifles".

The reason is on every product page, in their own words:

> MCT Defense provides services to governments, militaries and law enforcement
> agencies, government contractors and sub-contractors, defense and homeland
> security companies, civilian wholesale importers and distributor gun dealers.
> **No sale to individuals.**

Same call as Century Arms and Arms Unlimited, and reached before anything was
written rather than after. **The lesson is narrower than "measure first", which
the roadmap already says: an endpoint answering is not the same as an endpoint
carrying what you need, and `200 OK` with a well-formed body is exactly what a
priceless catalog looks like.** Read the values, not the shape.

#### Simpson Ltd. — **Shipped**, and the "needs a browser" note was wrong

The recorded blocker was: *"the catalog is in Firestore (project
`simpsonltd-bfd2b`) and its rules refuse an unauthenticated read; anonymous
sign-in is disabled too. Needs the browser path."* Every word of that is true
and it is **the wrong door**. The React bundle does not read Firestore
directly — it calls Cloud Functions on the same project, and those answer a
plain unauthenticated GET:

```
https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/fetchDataByCategory_v3
https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/fetchSKU_Inventory
https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/searchWebItems_v3
```

**Seventh vendor filed as unreachable that had an endpoint**, and the second
this month whose roadmap note was written from the shape of a response rather
than from reading it — see the MCT Defense entry for the other. Their
robots.txt is `Disallow:` with nothing after it, and both the function host and
the image host 404 on robots.txt, so nothing here needs an exception.

**One request is very nearly a whole listing**: title, full description, asking
price, caliber, action, bore *and stock* condition graded separately, FFL
class. The gallery is the exception — the catalog gives two thumbnails
(`C75280AT.webp`) of the six to ten photographs a listing has, so
`fetchSKU_Inventory?sku=` fills it in. Note the lower-case parameter: `SKU=` is
answered with *"SKU parameter is required"*, which reads as a broken endpoint
rather than a misspelling.

**The scope is the decision worth recording.** Simpson list **19,201 items,
every one priced, pictured and in stock** — sold stock is simply not returned.
That is three times everything this application holds, and most of it is a
sporting catalog: 3,057 shotguns, with Winchester, Remington, Ruger, Savage,
Marlin and Anschutz beside them. What is read is about 5,200 listings across
nineteen shelves — Lugers (1,157) whole, German .22 Trainers (355) whole,
Antiques (371) whole, Military Rifles (1,658), Mauser, Walther, Swiss, P-38,
Webley, Star, Czech, Hi Power, FN, and Bayonets (280). `SOURCES` holds what is
taken and `NOT_READ` holds what is not, so widening it is an edit to one tuple.

**The category endpoint takes `page` and `limit`, not `currentPage` and
`itemsPerPage`.** Those are what `searchWebItems_v3` beside it takes, and this
one *accepts* them, echoes `currentPage` back unchanged and serves page one
every time. The first version of this scraper used them and collected ten
listings per shelf — 190 against 5,200 — while making 116 requests per shelf to
do it, because nothing in the response says the parameter was ignored: the row
count and `totalPages` both look right. The names came out of the React bundle
in the end (`&page=…&limit=…`), which is where they should have come from
first. `limit` caps at 100.

#### What the other two measured, before anything was written

| vendor | finding |
| --- | --- |
| **Simpson Ltd.** | The way in is the shop-by-category links — `/products/category/<Category>/page/N?subcategory=<Sub>` — but those are 2.8 KB React shells. The catalog is in **Firestore** (project `simpsonltd-bfd2b`); its rules refuse an unauthenticated read and anonymous sign-in is disabled. Still needs the browser |
| ~~**Southern Tactical**~~ | **Dropped**, on review: 36 KB of page carrying three prices, no endpoint found behind it, and nothing to suggest the catalog repays the work |
| ~~**DK Firearms**~~ | **Dropped** on review. The blocker was never technical: the site answers plain HTTP with a `cf-mitigated: challenge`, so building it would mean working around a bot check its operator switched on deliberately |

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
- **Shipped** — Filter the browse page by the finer kinds. A **Form** facet
  beside Caliber, holding revolver, carbine, shotgun, percussion revolver and
  the rest of `FirearmKind`. It is a *second* question from the five Types,
  which partition the catalog and cannot express "show me the revolvers" — a
  flintlock pistol and a percussion revolver are both Handguns there — so the
  two compose: `?kind=pistol&form=revolver`.

  The note above said "the data is there through the model link; only the
  reading of it is missing", and that was half right. Reading it through the
  join would have worked and would have thrown away the better source on the
  shelves the armory does not reach: Simpson Ltd. state a type per listing.
  So it is resolved once and stored on `items.kind` (migration 0021) — the
  model's kind first, because it is curated and the finer of the two, then the
  vendor's word — and facets then tally a column like every other one.

  **6,623 of 10,964 listings carry one**: 2,769 pistols, 2,416 rifles, 994
  carbines, 276 revolvers, 78 shotguns, 42 percussion revolvers, 40 percussion
  rifles, 8 flintlock rifles. The 4,341 with none are a state rather than a
  gap, and nothing sweeps them into a bucket. Labeled server-side from the
  armory page's own `KIND_LABELS`, so the two pages cannot drift.
- **Shipped** — A third source for that kind: the listing's own title. The two
  above are the curated model and `items.stated_kind`, which is the vendor's
  *category* column — so nothing read the title, and 1,548 active firearms sat
  with no kind while 835 of them said "Revolver", "Carbine" or "Rifle" in plain
  text. `classify.form_in_title` reads it, and **untyped firearms went 1,548 →
  683, 17.8% → 7.9%**.

  It ranks last on purpose. Measured against the 7,146 listings that already
  had a kind, the title agreed 1,338 times and disagreed 268 — and the
  disagreements run both ways: "M95 Steyr Mannlicher Carbine" was stored as a
  rifle and the title is right, while "German K98 8mm Rifle" is a Karabiner and
  the model row is. So it fills blanks and never overrules.

  Two rules earn their keep. **`.30 Carbine` is a cartridge**, and it is the
  only one in the catalog whose name contains a form word (114 listings) — so
  an occurrence a number introduces is discounted, and one that is not is kept:
  a Ruger Blackhawk in .30 Carbine is a revolver, an M1 Carbine in it is still
  a carbine. And **ignition sharpens the form**, because `FirearmKind` is
  really ignition by form: "Percussion Revolver" lands in `percussion_revolver`
  rather than `revolver`. `flintlock_pistol` went 0 → 20, `percussion_pistol`
  1 → 17, `percussion_carbine` 0 → 4.
- **Shipped** — Edged weapons and suppressors stop being rifles.
  `_HEAD_NOUN_ACCESSORIES` had listed swords, sabers, cutlasses, suppressors
  and silencers from the start, and every one was a dead letter: that constant
  filters a word the scan has *already found*, and the scan runs over
  `_ACCESSORY_NOUN`, which held none of them. So the veto that outranks the
  vendor's category never got a word to veto — and a Civil War cavalry saber
  filed under "M1 Garand & U.S. Rifles" was a rifle, as was a Gemtech
  suppressor under "Used & Collectible Firearms".

  Two guards came out of measuring it against all 11,038 listings. A saber
  bayonet is a **bayonet**, so the sword half must not match first — without
  that, "Model 1841 Mississippi Rifle … with Saber Bayonet Lug" became an edged
  weapon. And a muzzle device is named by its bore rather than counted: the
  bare `22` in "Gemtech SeaHunter 22 Suppressor" was read as a count of
  suppressors, which stripped the only noun in the title. The dotted spelling
  was safe all along, since a leading `.` fails the introducer's lookbehind.

  Exactly 4 listings changed, all of them wrong before and right after, with
  no collateral anywhere in the catalog.
- **Shipped** — A second discriminator for a shared designation: who built it.
  `_contradicted` already settled "Model 1917 is a Colt revolver and an Enfield
  rifle" by asking what *kind* the listing says it is. It cannot settle two
  rows of the same kind — a Mauser Model 1910 and an FN Model 1910 are both
  pocket pistols — so whichever sorted first took the match, and its caliber,
  country and maker with it.

  **Decided by distance, not by presence.** The firm a title means to attach to
  a designation stands next to it; a cartridge is elsewhere in the sentence:

      Astra Model 900 7.63x25mm Mauser   -> Astra
      FN Model 1910 in 7.65mm Mauser     -> FN

  Both read the same way round, and a rule asking only *whether* each name
  appears cannot separate them — each title names a rival and its own, so
  neither is vetoed and sort order decides. Half those answers would be wrong,
  and the wrong half is silent.

  **It fires on nothing today, deliberately.** Rivals are built only from
  makers on *other* rows claiming the same spelling, so a row nobody competes
  with carries no guard at all. That restraint is the design: a maker named in
  a title is a far noisier signal than a type word — it may be a cartridge
  ("Astra Model 900 7.63x25mm Mauser"), and a row may simply not list the firm
  that built it (17 of 20 measured cases). Either, turned into an absolute
  veto, would lose matches that work.

  Measured: 219 approved rows are named by nothing but a bare designation
  ("Model 1910", "Type 53", "Model 1"), and exactly three spellings were
  claimed twice — all three one gun under two names. Those were merged
  (`M44` into `Mosin-Nagant M44`, `M91/30` into `Mosin-Nagant M91/30`), so no
  designation is contested now. With a discovery queue proposing more bare
  designations every scan, the collision is a question of when; building the
  discriminator first costs one pass at cache-build time, and building it after
  means first noticing that a listing quietly took the wrong model's facts.

  **The maker back-fill that was meant to go with this did not survive the
  data.** 480 maker links are implied by listings and missing from rows, and
  filtering the cartridge trap the same way (`CZ75 + Luger` is the 9mm Luger
  cartridge, 18 listings) leaves 52 — of which roughly a third are still wrong,
  and wrong in a way no heuristic here can catch: `CARL GUSTAF 1896 + Mauser`
  (64 listings) is the designer, not the builder. That is the distinction
  `FirearmModel.country` already exists to keep — "where the pattern comes
  from", explicitly not the firm — so inferring makers from listings cannot be
  done safely and the links stay a curation job.
- **Shipped** — The armory tables fit, rather than scrolling sideways. The
  models table overflowed its container by about forty pixels, and only when
  the data happened to be long — so the horizontal scroll appeared and
  disappeared with the rows. A browser with overlay scrollbars draws nothing
  until you are already scrolling, so what sat past the edge did not look like
  it was there: the eye and the trashcan were reported as simply missing, and
  the actions cell is `justify-content: flex-end`, so "Merge…" stayed put while
  the two icon-only buttons beside it went over.

  Fixed by letting the table shrink rather than by pinning what fell off it.
  Four things, each found by measuring rather than guessing:

  * **Headers and cells wrap.** `white-space: nowrap` on a `th` is what let
    "ALSO WRITTEN AS" and "CHAMBERED IN" set a floor no free space could go
    under.
  * **A name is a button, and `.btn` is `nowrap`** — so one long designation
    held the whole Name column open at 339px for rows reading "04/43", and
    took 119px of sideways scroll with it. This was the pending queue, the
    default view and the one most worked in.
  * **"Also written as" moved under the name it belongs to.** It was the widest
    column on the page, 182px of 1114, and "M91/30" is a way of writing
    "Mosin-Nagant M91/30" rather than a separate fact about it.
  * **The controls give up padding before the data gives up room.** At 1024 the
    actions cell was the widest in the table at 197px — more than the names.

  Verified at 1440, 1280, 1100 and 1024 across all three tabs, on the pending
  queue as well as production: zero overflow. The test asserts header-to-cell
  counts too, because removing a column from one of the two tables and not the
  other is the easy way to get this wrong — which is exactly what happened
  first time, silently misaligning the manufacturers table.
- **Shipped** — `armory tidy`, and a correction to what it was meant to fix.
  The residue of approving a discovery queue wholesale was reported as "91
  unqualifiable bare designations, 86 saying nothing at all". **56 of those
  were already switched off by hand** — the count had been taken over approved
  rows without checking `enabled`, so retired rows were being reported as
  outstanding work. Live, it was 34 bare rows and 10 silent ones. `qualify` had
  the same blind spot and would have renamed retired rows; it now requires
  enabled as well as approved, because a switched-off row has been ruled on.

  What the command does is **retire** a row that says nothing, holds no
  listing, and was proposed by a scan rather than shipped in the armory file —
  switched off rather than deleted, because `propose_model` looks a name up
  regardless of status, so a surviving row is a tombstone that stops the name
  coming back while a deleted one returns on the next scan. That is the same
  rule the page's trashcan already states in `comesBack()`. One row qualified.

  It also **fills a blank country** from a row's own listings, and the
  interesting part is that this fires on nothing. Three things had to be
  learned to get there:

  * **One listing is not agreement.** "SOHN 38H" — itself a truncation of
    "J.P. Sauer & Sohn 38H" — would have learned it was Swiss from a single
    listing whose country came through "Sauer"; the firm is German. "X400" is
    a Surefire weaponlight, and its one listing is a rifle sold *with* one.
    Both were unanimous by construction. The floor is two.
  * **The kind cannot be machine-written**, however fillable it looks.
    `TestTheShippedFileNamesItsCountries` takes a kind as the marker of a row
    somebody has judged — "it cannot be guessed from a title" — and requires a
    country beside it on that basis. Filling six kinds falsified the premise
    and tripped the invariant: six judged-looking rows naming nowhere.
  * **The rows still silent are silent for a reason.** "M1896" holds fourteen
    listings across Sweden, Germany, Switzerland and Finland, because that
    designation names different guns in different places. That is the
    bare-designation problem itself, and picking one would be inventing an
    answer rather than finding it.
- **Shipped** — `armory qualify`: a bare designation is renamed to name the
  firm already on it. "10/22" becomes "Ruger 10/22", "M1849" becomes "Colt
  M1849", "Type 53" becomes "Mosin-Nagant Type 53". 119 rows renamed, and
  **not one listing changed its model link** — the old name is kept as an
  alias, so a rename can only widen what a row answers to, never narrow it.

  **Nothing is inferred**, which is the whole safety argument: the firm is
  already on the row and already vouched for, and this only moves it into the
  name so the page and the matcher can both see it. Of 399 bare names, 122
  qualified. The other 277 are refused rather than guessed: 178 have a country
  but no maker, 86 have neither, and 13 have several — nine firms built the M1
  Carbine, and "Inland M1 Carbine" would be a lie about the other eight.

  Approved rows only, because discovery proposes bare designations on every
  scan and renaming the pending queue would churn the list somebody is reading.

  **The country answers where no firm can.** 178 of the 280 bare names carried
  a country and no maker at all, so the pass falls back to the nationality:
  "Model 1896" becomes "Swedish Model 1896", "Type 30" becomes "Japanese Type
  30". A firm still wins where there is one — "Ruger 10/22" narrows more than
  "U.S. 10/22" — and several makers or an unusable one fall through to the
  country rather than to nothing, which is how "CO M1864" would have become
  "U.S. M1864" had the firm not been fixed outright.

  The adjectives are checked rather than trusted: every one of the 27
  round-trips through `classify.extract_country`, because after this pass a
  model's *name is a title the classifier will read*, and an adjective it did
  not recognize would be a row teaching the classifier the wrong thing about
  itself. A country with no entry keeps its bare designation.

  **188 renamed in the second pass, 0 listings lost a model.** 91 approved rows
  are still bare and every refusal is principled: 86 have neither a country nor
  a usable maker, 4 have several makers and no country.

  Two of the 122 were caught by a guard worth keeping: **"CO" was in the maker
  table as an approved firm with eight listings**, read out of "SPENCER
  REPEATING RIFLE *CO* M1865" and "Spencer *Co.* Boston". A junk firm is
  survivable in a column; baked into a model's name it is not, because the name
  is what the page shows and what the matcher compiles. So a firm that is only
  a legal suffix — co, inc, ltd, gmbh, & sons — is refused, as is one that is
  pending or *disabled*: "CO" was approved and switched off, already dealt with
  by hand, and a pass reading only `status` would have quietly undone that.

  It has since been fixed at the source rather than worked around. "CO" reached
  five models and eight listings, and what it was standing in for was three
  firms nobody had written down — **Joslyn**, **Triplett & Scott** and
  **Cugir** (whose listings spell it "Cujir" as often as not). Two of the
  models were truncations as well: `TTC 7` and `PSL 7`, where discovery took
  the head of "TTC 7.62x25mm" and "PSL 7.62x54R" for the designation.

  And M1864 turned out to be the contested-designation case for real, not in
  theory: a **Joslyn carbine** and a **Triplett & Scott rifle**, both sold as
  "M1864", both in this catalog. It is now two rows, both answering to the bare
  spelling, told apart by the maker discriminator above — the first live use of
  it, and it reads each title correctly. `test_modern_shelf.py` was tightened
  to match: a shared spelling is allowed, but only where the rows carry firms
  that no rival shares. Two rows with overlapping makers, or none, are back to
  a coin toss and still fail.

  The shipped `app/seed/armory.yaml` was regenerated with it: 119 added, 119
  removed, every addition a rename of a removal, and the maker and caliber
  lists untouched. Without that a fresh install would re-seed "10/22" beside
  "Ruger 10/22" and manufacture the very collision the maker discriminator
  above exists to resolve.
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
- **Shipped** — …but both of those patterns turned out to be **already fixed**,
  and the entry was stale. Measured before touching anything: 7.65 beside
  "Luger" reads as 7.65 Parabellum on all five live listings, and a bare 8mm is
  held back and weighed against the designation — 244 of 249 correctly Mauser,
  the other five Lebel. The `MODEL_CARTRIDGES` / `_AMBIGUOUS_BORES` split had
  done it and nobody updated this.

  What the measurement found instead was the gap underneath them. Nothing
  claimed a bare 8mm *for Lebel*, so the Mauser fallback took it with the word
  "Lebel" sitting in the title: `French Lebel Model 1886 Rifle 8mm` read as 8mm
  Mauser. The designation table knew Berthier and St Etienne and not the rifle
  the cartridge is named after. Added, and isolated against the whole catalog:
  **zero listings change**, because the nine Lebel listings are already right
  and three of them are bayonets the accessory rules keep uncalibered.

  **A scare this also produced, and the correction to it.** 32 firearms were
  found holding a caliber that `extract_caliber` declines to re-derive — titles
  ending "with bayonet" or "W/HOLSTER" — and that was written up here as 32
  listings about to lose their caliber on the next scan. **That was wrong.**
  The scan fills gaps and does not overwrite: `item.caliber = item.caliber or
  derived["caliber"]`, so a stored value is never replaced by a heuristic. None
  of those listings is at risk.

  Two things were wrong with the diagnosis as well as the conclusion. Only 20
  of the 32 reach `_accessory_leads` at all; the other twelve stop somewhere
  else. And the headline examples — `SWISS K11 W/BAYONET`, the Berthier — are
  in the `accessory_leads=False` group, so the veto was never their reason.
  `SWISS K11 W/BAYONET` states no cartridge and names no designation that
  implies one; its caliber comes from the armory's model match, which is the
  system working.

  What remains is smaller and still real: `_COMES_WITH` exists to tell "rifle
  w/ bayonet" from a bayonet, `_is_a_bayonet` uses it and `_accessory_leads`
  does not. A fix was attempted and **backed out** — guarding on the inclusion
  word rescued the *scabbard* in "Lebel cruciform bayonet with scabbard" and
  turned a genuine bayonet into a rifle, because `_BUNDLED_ACCESSORY` contains
  scabbards and not bayonets. Worth doing with `_BUNDLED_ACCESSORY`,
  `_is_a_bayonet`, `_ACCESSORY_COMPOUND` and `_is_the_head_noun` read together
  first; not worth doing from a wrong model of which one fires.
- **Shipped** — Better maker candidates, though not in the direction this
  entry expected. It proposed reading descriptions as the next signal; measuring
  the queue first said that was the wrong way.

  **Eleven candidates stood over the whole catalog and about one was a real
  firm** — `LUGER`, `TOKAREV`, `SKS`, `Fusil Gras`, `CO`, `Ordnance`, `Weapons
  Micro Galil`. Not "two in three" any more, and for a good reason: approving a
  maker is what stops it being proposed again, so the real firms have been
  taken and what reaches a human now is the residue. The problem is precision,
  and reading descriptions would have added recall — more candidates, the same
  junk fraction, more attention spent.

  Two vetoes, both measured rather than imagined:

  * **A name the caliber tables read as a cartridge is not a firm.** The
    positional rule cannot tell a maker from a designer or a pattern name;
    `extract_caliber` already can. Removes TOKAREV, SKS, Fusil Gras.
  * **A name with nothing in it but a corporate suffix is a fragment** — what
    is left when the leftward walk stops at a comma. Removes CO and Ordnance,
    and keeps "Delaware Machinery" and "Springfield Armory", where the suffix
    is part of a real name.

  **Eleven to six, with the real firm kept.** Deliberately stopped there: the
  obvious next veto — "the name appears in an armory model name" — would reject
  **Mauser**, which is both a firm and a model word.
- **Shipped** — Record whether a stored field was **stated by the vendor or
  derived by the rules**. Migration 0031, four columns on `items` and
  `app/services/provenance.py`.

  That single missing fact was what made `reclassify recompute=1` unusable as a
  maintenance step: scoped to nothing but the caliber it changed **3,187 of
  11,038 listings**, 2,251 of them to nothing at all, because it could not tell
  a caliber the rules guessed from one the dealer printed. A Carl Gustafs 1896
  stated as 6.5x55mm Swedish came back 8mm Mauser; a Carcano carbine whose own
  title reads "6.5X52" came back 7.35x51mm. The scan had always known which it
  had — `item.caliber = scraped.caliber or item.caliber` and then
  `item.caliber = item.caliber or derived["caliber"]`, two lines that knew the
  answer and threw it away.

  Four sources, and the gate is a whitelist: `derived` and `catalog` may be
  rebuilt, `vendor` and `override` may not, and **neither may a value nobody
  recorded**. That last is the important half — every row written before this
  existed has no source, and treating those as fair game reproduces exactly the
  damage. Verified against the real catalog: the same command that changed
  3,187 listings now changes **0**, reports `caliber: 11038` left alone, and a
  four-field comparison over all 11,038 rows confirms nothing moved.

  **A spelling is not a source.** The armory normalizes ".32 ACP" and "7.65mm
  Browning" into one answer and the maker table spells "S&W" as "Smith &
  Wesson"; neither is a new opinion about the gun, so both go through
  `respell`, which changes the value and leaves the source alone. Recording
  them as the catalog's would hand a rebuild permission over the vendor's own
  fields — the original bug wearing a hat.

  **The `override` source closes a hole that predates the module.**
  `reclassify` never read the override table at all, so a rebuild quietly undid
  a person's correction until the next scan put it back.

  Shown on the item detail page under each derived value — "from the shop",
  "read from the listing", "from the armory", "corrected by hand" — because it
  is the difference between a value worth correcting and one worth trusting,
  and the person deciding whether to override cannot tell without being told.
  Nothing is shown for an unrecorded origin: the honest answer there is
  silence.

  **Deliberately not backfilled**, so it earns nothing on the day it ships. A
  backfill would have to guess which values were the vendor's, and that guess
  is the thing being fixed. It fills in as each site's next scan rewrites its
  rows; every site scans daily.
- **Planned** — Have `catch-up` run a provenance-scoped recompute on upgrade,
  so a rule fix reaches stored listings without anybody remembering. The gate
  above makes this safe rather than merely possible — but **not yet measured**,
  because with every source still unrecorded it would decline all 11,038 rows
  and prove nothing. It wants a scan cycle's worth of sources first, and then
  the same before-and-after count the rest of these entries carry.
- **Shipped** — Carrying a curated armory off a running instance. The armory is
  edited on a live instance and *shipped* from `backend/app/seed/armory.yaml`,
  so the two drift the moment somebody approves a model in production — and the
  only way back was a shell on the server, which an administrator using the web
  pages does not have.

  Two buttons on the Armory page. **Download armory** is a plain link, which
  works only because the session is a cookie; **Email it to me** sends the file
  attached, to the requesting admin's own address and no other, because this is
  the whole curated catalog and a box that could send it anywhere is a way to
  take it out with one stolen session. Both are the same bytes `milsurp armory
  export` writes, and there is a test that what comes out of the browser goes
  back in through `armory sync` with a zero-change plan.

  **The file's own header had been wrong for some time.** Every export told the
  reader to run `milsurp catalog export` and `milsurp catalog sync` — neither
  is a command this CLI has, so anyone following the instructions in the file
  got `invalid choice: 'catalog'`. Now `armory`, pinned by a test, since the
  header is the only instruction most people will ever see.

  The email says what to do in prose rather than as a command line. The steps
  are the same on every checkout; the commands are not — branch, remote and
  whether there is a review step are all site policy, and a message that
  guessed would be wrong on somebody's machine while looking authoritative.
  Naming the file to replace is the part nobody can guess.
- **Shipped** — An armory edit says what it cost the catalog. Approving a
  model, adding an alias to a cartridge, switching a row off or deleting one
  re-matches every listing whose text mentions any of the spellings involved —
  which is the point of the table, and is also several hundred listings
  changing while somebody looks at one dialog.

  **The count was already being computed and thrown away.** `reprocess()` has
  returned it since it was written and the maker endpoints have reported theirs
  throughout; the caliber and model writes dropped it, so the two most
  consequential edits on the page were the two that said nothing. Each now
  answers *"3 listing(s) re-matched."* Deleting returns a body rather than 204
  for the same reason: a dialog that closes on success tells an admin nothing
  about the rows that just moved underneath it.

  Scoped to the armory's own reach — the model link and the caliber. Country,
  maker and kind are settled by rules that live elsewhere, and re-deriving them
  from here would duplicate `_apply_catalog` in a second place, which this
  codebase has already done twice.
- **Shipped** — Undo for an armory edit. Migration 0032,
  `app/services/armoryundo.py`, and an **Undo** button on the audit log.

  **The audit log could not drive it as it stood**, which the planned entry had
  been optimistic about. It recorded *that* a row changed — who, when, which
  fields — and never what those fields held, so it could say "somebody edited
  the K31's aliases at 14:02" and not what they were at 14:01. That answers
  "who did this" and not "put it back", which is the question somebody actually
  has on seeing *412 listing(s) re-matched* under a dialog they have just
  closed.

  So the log gained one column holding JSON. Not a table of its own: an undo
  belongs to the event that needs undoing, it is read exactly when that event
  is read, and a parallel history would be a second thing to write and prune in
  step with the first. Unstructured on purpose — the shape differs per target,
  and a column per field would be a schema change every time an editable field
  is added, for a value nothing ever queries.

  **A delete comes back with a new id, and that turns out not to matter.** The
  listings pointing at a deleted row were unlinked when it went, so restoring
  it cannot restore them by id — but the armory matches by *spelling*, so
  re-reading every listing that mentions the restored names links them to the
  new row and the count comes back where it was. There is a test for exactly
  that, because it is the claim the feature rests on. (The id is deliberately
  not asserted either way: SQLite may hand back the same one, and the feature
  works regardless precisely because nothing depends on it.)

  The button appears only where the server says the change is revertible — an
  armory edit or deletion that recorded a before-state. Everything logged
  before this migration has nothing to restore, and a button that answers with
  an error is worse than no button. A revert is itself logged and is not
  revertible: undoing an undo is the same operation on a newer event, which is
  what somebody means by "actually, put it back again".
- **Shipped** — Admin UI for the rest of the classification heuristics.
  Migrations 0029 and 0030, three tables and one page with three tabs:
  **38 countries, 52 caliber designations and 43 keywords** — the 21 accessory
  words and the two lists that veto them, 8 promotional phrases and 14 firearm
  words. All of it used to be tuples and regular expressions in
  `app/services/classify.py`. Teaching the application that "Ishapore" means
  India, or that a Mauser ES340 is a .22 trainer, was a code change, a review
  and a deploy — for a fact about rifles the operator knows and the programmer
  does not.

  **They could not follow the maker list exactly, and the difference is the
  interesting part.** A maker is matched by `manufacturers.extract(session, …)`,
  called from the scan where a session exists. These three are matched inside
  `classify.enrich`, which *scrapers* call — and a scraper has no database
  session and should not be given one: it runs against somebody else's website,
  and the moment it can write to the database it is a different kind of
  program. So each list is a process-wide registry that loads once and is
  dropped when the table changes, and every write in the API calls
  `invalidate()`. Forgetting that is the failure this shape of code has: the
  edit saves, the page shows it, and nothing classifies differently until the
  process restarts, with nothing on screen to say why. There is a test for it
  on every one of the three.

  **Literal text, never patterns.** A regular expression typed into a form is
  both a way to hang the process and a way to match something nobody meant. So
  a rule is a list of spellings, matched on word boundaries, and the three
  things the regexes could say that a spelling cannot are three columns:

  * `requires` — a second list, also literal. Eleven of the forty-eight caliber
    patterns were "these two things co-occur" rules written `X.*Y|Y.*X`, which
    is how the table says "Mauser and 8mm in the same listing".
  * `whole_word` — the difference between "walther pp", meant to catch a
    Walther PPK, and "ak", which must not catch Krakow. The original drew this
    line with `\b` on some rules and not others; the column makes it visible.
  * `match` on a keyword — `word`, `suffix` or `substring`. The accessory words
    were substring tests, and one was quietly wrong for every Springfield in
    the catalog: "spring" is inside "Springfield", so a Springfield Model 1903
    was an accessory and never got a caliber, 23 of the 28 in the database.
    They are whole words now. `suffix` is the one deliberate exception, for an
    optic, which is named by what it is on the end of. The two veto lists stay
    `substring`, faithfully: "gun" reaching "shotgun" is the point of writing
    it that way, and narrowing them is a change to make on purpose and measure.

  **Seeded from the constants, and measured against them.** The countries table
  is byte-for-byte equivalent: *11,038 listings compared, 0 differences* — which
  took three tries. Seeding each country's own name as a spelling looks
  obviously right and moved 38 listings, because the pattern it replaced for
  Finland was `\bFinn(?:ish)?\b` and never matched the word "Finland". The
  seed carries the spellings the code had and no more; adding "Finland" is now
  a one-line edit on a page, which is the whole feature.

  The caliber table is **not** byte-equivalent, and here is exactly where it is
  not. Measured end to end through `extract_caliber` across all 11,038
  listings: **23 change, every one of them from wrong or absent to right.**

  * `requires` is unordered where three of the original patterns were
    one-directional. `swiss.*rifle` wanted "Swiss" *before* "rifle", which no
    W+F Bern listing writes. Eleven Swiss rifles and a Chatellerault Gras that
    state their identity plainly were getting no caliber at all. The seven
    rules the author wrote both ways round say what was meant; the three
    written one way round are where the hand slipped.
  * The `.22 Long Rifle` rule now accepts the spelling without the leading stop
    and is tried before the Swiss rule. Twelve more, six of them positively
    wrong rather than blank: a Mauser ES340, a Model 410, a Mauser 107 and a
    625B training rifle are .22 rimfire sporters that the `mauser` + `8mm` rule
    was filing as 8mm Mauser, and a Tikka M91 trainer was filed as 7.62x54R.

  Nothing loses a caliber it had, and the part-or-gun verdict is identical on
  all 11,038.

  **The three keyword lists live in one table because their order is the
  rule.** A gun sold *with* an accessory is a gun; a title that names a gun is
  a gun; only then do the accessory words get a say. Split across three tables
  and three tabs, somebody could edit half of a rule, so they are one tab that
  says the order on the page and one registry that applies it.

  **Two things deliberately left alone.** Ordering within the designations is a
  number an operator types, not a drag handle: the first match wins and the
  list is 52 long, so a gap-of-ten scheme that survives an insertion beats a
  gesture that renumbers everything. And nothing on this page rewrites the
  catalog — a rule change reaches stored listings only through `make reclassify
  recompute=1 fields=…`, scoped, because an unscoped recompute also clears the
  makers the vendors supplied. An edit that silently touched eleven thousand
  rows is not something to find out about afterwards.
- **Shipped** — Manual override fields on an item, preserved across re-scrapes.
  Migration 0028, `item_overrides`, one row per listing, applied **last** — after
  the vendor's own fields, after the heuristics, after the armory.

  The pipeline is built to be recomputed, which is what lets one rule fix reach
  eleven thousand listings and exactly what made a correction typed into the
  database last until the next scan. An override outranks all of it, and is
  narrow on purpose: caliber, country, manufacturer, model and kind — the
  derived fields. Price, title and URL are the vendor's own words, and
  disagreeing with those is not a correction.

  **A blank field means "no opinion", never "clear it"**, so correcting a
  caliber does not assert that the country is unknown — the API uses
  `exclude_unset` and an explicitly empty field removes that one override.
  It records who and why: an override nobody can explain is one nobody can
  safely undo, and the person reading it will not be the person who set it.

  In its own table rather than as columns on `items`, so `reclassify
  --recompute` — whose whole job is to rebuild derived fields — cannot mistake
  one for derived data. Clearing an override deliberately does *not* restore
  the derived value: what that should be is the scan's business, and guessing
  from this side would be a second implementation of the pipeline.
- **Shipped** — Vendor boilerplate taken off the end of descriptions.
  `app/services/boilerplate.py`, applied where the scan stores the text so
  every reader — detail page, digest, the classifier reading prose for facts —
  sees the same thing. **1,067 of 10,775 descriptions trimmed, 3.6% of the
  characters.**

  Conservative by construction, and each guard is there because an earlier
  version did the harm it prevents:

  * **Only from the end, whole sentences, stopping at the first that is not
    boilerplate** — so a policy sentence mid-description is never touched.
    "Shipped to my FFL in 1962" is part of a story about a gun.
  * **A cap on how long a removable sentence may be.** Parts-kit contents lists
    have no full stops, so one arrives as a single 700-character chunk; an
    incidental match inside it removed a real description from four listings,
    59% each.
  * **A cut at a mid-text `DISCLAIMER:` marker rather than dropping the chunk
    containing it.** Dealers write condition notes with no punctuation either,
    so the notes and the disclaimer arrive as one sentence — and removing the
    sentence removed the condition report, which is the part a buyer reads.
  * **A floor and a share limit.** `Description **C&R FFL OK**` is 26
    characters and all of them useful: C&R eligibility is a fact about the gun.

  The rule throughout is that leaving boilerplate in is a small harm and
  cutting a description short is a large one, so every judgment call goes the
  same way.
- **Parked** — Optical character recognition of proof marks from photos. Fun,
  but a long way from paying for itself.

### Calibers as a managed list, like makers — **Shipped**

Built as specified. `calibers` is a table with a display name, aliases one per
line, a position, an `enabled` switch and the same approval gate the makers have,
and it is edited from the **Calibers** tab of the armory. An edit re-files every
listing it reaches and reports how many moved, through the same `reprocess`
machinery the manufacturers page uses. It was seeded from
`CALIBER_NORMALIZATIONS`, so nothing was lost.

**The bare-bore case is what it turned out to be for.** The plan guessed this,
and a day of curation proved it: the percussion end of the catalog is written as
a number and nothing more. A Colt Dragoon is `.44`, a Colt 1849 Pocket is `.31`,
a Colt 1851 Navy is `.36` — 137 listings between those three — and each is an
honest answer rather than a gap, because a ball is a diameter and not a
cartridge. What the table adds is the ability to say *which* of them is a
diameter and which is a cartridge wearing one as a name.

**What curating it actually found.** 44 merges, 26 renames and roughly 1,100
listings re-filed, and the interesting part was not the tidying:

- **Two condition grades were live matching rules.** `.30 Luger` carried the
  alias `8/10` and `.30 Mauser` carried `1/10`, so a vendor writing "bore rated
  8/10" got a cartridge out of it. Nothing had been hit yet.
- **`7.62x25mm Tokarev` claimed `7.63x25mm Mauser` as an alias**, and they are
  different cartridges — the Mauser round is safe in a Tokarev chamber and not
  the reverse. Every C96 spelled that way was mis-filed.
- **One row held two cartridges more often than expected.** `8x50mmR` was Steyr
  Mannlichers *and* a Lebel; `7mm` was 7×57 Mausers, 7mm pinfires, four Baby
  Nambus and seven Arisaka Type 99s that are 7.7; `.30 Caliber` was twenty-one
  Lugers, a C96, an M1 Carbine and a Brazilian Mauser. None of these is
  reachable by pattern-writing — each listing had to be read.
- **A vendor's own word beats every heuristic.** Simpson Ltd. state a type per
  listing and leave it blank on accessories, which is what `Item.stated_kind`
  now carries. It cut their untyped listings from 1,051 to 284.

**Both lessons from the maker work held.** Position decides ties and is used —
`Steyr M95/30` sits at 999 so it is tried before the ambiguous `Steyr M95`,
which carries both its cartridges and therefore fills neither. And a name
claimed by two rows identifies neither: `.22 LR` carried `.22`, `22 CAL` and
`22 Long` as aliases and swallowed every other .22 rimfire, including a
cartridge — `.22 Long` — that is not it.

**What is left is judgment, not machinery.** Roughly twenty listings name a bore
and nothing else (`7mm`, `11mm`, `14mm`, `10.3MM`, `16x42`), and no rule will
settle whether a "MONDRAGON FSLK 15" is 7×57 or 7.5×55. Those want somebody who
knows the guns, which is exactly what the table exists to let them express.

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

- **Shipped** — Market view. `app/services/market.py`, `GET /api/market?by=`,
  and a page at `/market` open to every signed-in user: what each kind of gun
  is being asked for across every shop at once, by caliber, country or maker.
  The detail page answers "is this a good deal?" for one listing by placing it
  among others of the same model; this is the same question one level up, which
  is the one somebody has *before* they have a listing in front of them.

  **Four decisions, each of which the naive version gets wrong.**

  * **The median, not the mean.** One dealer listing two hundred parts kits at
    forty dollars drags a mean and leaves a median where it was.
  * **Firearms only, by default.** A caliber's listings mix six-hundred-dollar
    rifles with forty-dollar bayonets, magazines and parts kits, and a median
    across those describes nothing that exists.
  * **The tenth to ninetieth percentile, not the range.** A single mislabeled
    $750,000 Gatling gun sets the maximum for .45-70 and says nothing about the
    .45-70s anybody will buy.
  * **A minimum sample**, reported rather than silently applied: 60 bands shown
    out of 161, with the 101 too thin and the 184 listings in them counted on
    the page. Below a handful a median is an anecdote with a decimal point.

  **The finding came out of building it: most bands are one dealer.** ".22
  Caliber" is a single shop, 6.5x55mm Swedish 98% one shop, 7.5x55mm Swiss 93%,
  Switzerland 92%, Sweden 96%. A median from one shelf is that shop's pricing
  and not the market's, so every band carries the number of shops behind it and
  the share held by the largest, and anything at or above 70% is marked. A page
  that did not say so would be inviting exactly the wrong conclusion.

  **No line chart, and the roadmap line that asked for one was wrong about the
  data.** A `price_history` row is written only when a price *changes* — the
  right storage, since a row per scan would be eleven thousand duplicates a day
  — so a series has to be reconstructed rather than read. That is
  straightforward and is not the problem: there are 10,968 price points across
  10,910 listings over eight days, which is 1.005 points each. There is no
  series to reconstruct yet.

  The obvious substitute — comparing what is on the shelf against what has left
  it — was built, measured and removed. Across the whole catalog at most three
  calibers have both a live and a sold sample worth the name, and their gaps
  run from −39% to +33%: noise wearing a percent sign. The unweighted version
  looked far better and was worse, reporting an 85% gap for 9mm Luger that was
  entirely a difference in *which dealers* turn over stock.
- **Fixed** — *Unknown timezone 'America/Indianapolis'* when saving the digest
  settings on production. Debian 12 and Ubuntu 23.04 moved the IANA
  backward-compatibility links into a separate `tzdata-legacy` package that
  nothing installs by default; every development machine had it and production
  did not. The settings page offers the device's own zone as its first option
  and `Intl.DateTimeFormat()` still reports the legacy alias on some systems,
  so for that person the page simply could not be saved.

  Fixed by depending on the `tzdata` package, which carries the links whatever
  the host has — `zoneinfo` searches `TZPATH` first and falls back to it, so a
  host with a more current database keeps using its own. The regression tests
  run with `TZPATH` pointed at an empty directory: without that they pass on
  any developer's machine whatever the fix is, which is what let this reach
  production in the first place.
- **Planned** — Price bands over time, once there is enough history to
  reconstruct a series. The page above is the snapshot; this is the axis it
  deliberately does not draw, and it wants a few months of `price_history`
  before it can say anything a reader should act on.
- **Shipped** — CSV / JSON export of a filtered result set. `GET
  /api/items/export` takes the same query parameters as the list endpoint, so a
  browse URL becomes an export by changing the path — which is the only way the
  promise "what you are looking at" can be kept, and there is a test asserting
  the exported row count equals what the list endpoint reports for the same
  query.

  No pagination: an export is the whole answer or it is not an export. Bounded
  at 25,000 rows instead, and it **refuses rather than truncating** — a file
  that quietly stops looks complete and is not.

  The buttons are plain links, and that only works because of the session-cookie
  change above: a bearer token in `sessionStorage` could not authenticate a
  navigation, so this would have needed fetching as a blob and handing back to
  the page. The browser attaches the cookie itself.

  The filter arguments are spelled out twice rather than shared through a dict.
  A dataclass dependency was tried first and is not a FastAPI idiom — it bound
  the filter object as the response — and a shared `**kwargs` dict defeats
  mypy's check on fifteen arguments, which is a worse trade than repeating
  them.
- **Shipped** — "What changed" across all sites, distinct from the per-user
  email. `app/services/changes.py`, `GET /api/changes?days=`, and a page at
  `/changes` open to every signed-in user.

  **It is a page rather than a message, and that is the distinction.** The
  email digest is a shopping list: each person's sites, each person's price
  floor, capped per site so it fits in a preview pane. This is the other
  question — *what happened to the catalog* — and it has the same answer for
  everybody, so mailing it to each user separately would be sending the same
  page twenty times.

  Three things in it are not in the digest, and they are the reason it exists:

  * **What left.** A digest is about arrivals, so a listing that sold or was
    taken down is invisible in it. Half of what happens in a week is
    departures, and until now nothing counted them.
  * **Which shops were quiet.** Every *enabled* site is in the per-site table
    whether or not it had news, because a shop that reported nothing all week
    is either a slow vendor or a broken scraper, and nothing else in the
    application puts those two next to each other and makes you look. Failed
    scans in the window are counted in the same row, which is what tells them
    apart. A *disabled* site appears only if it had activity — a shop switched
    off on Wednesday still had a Monday, and the headline numbers count those
    rows, so the table has to as well.
  * **What the catalog learned.** Calibers, countries and makers whose
    *earliest* listing anywhere is inside the window. Asked that way round
    deliberately: "a recent listing carries this value" would name every
    caliber in the catalog every week. Usually it is new stock; sometimes it is
    a classification rule that has started matching something it should not,
    which is the other reason to look.

  **The window is closed at both ends**, because "since a week ago" moves while
  you read it and double-counts against a page somebody reloads. Bounded at 90
  days: the queries are unbounded scans over `items` and the page is reachable
  by every signed-in user, and a year of this is a report, not a page.

  Arrivals are ranked by price rather than by recency — "newest" is what the
  browse view already answers, and answers better. A reduction under $5 is not
  news: the catalog is full of rounding and shipping recalculations. The
  reduction test matches what the digest means by a price drop, so the two
  never disagree in front of somebody comparing them.

---

## 4. Platform and operations

- **Shipped** — PostgreSQL as an alternative backend, and the rule that keeps
  it working. See the section below.
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
- **Shipped** — The restore drill, done rather than described. A backup nobody
  has restored is not a backup; the snapshots above had been opened by the
  tests and never put back into service. So one was: the newest bundle pulled
  off the NAS, restored into a clean PostgreSQL 18, migrated forward, and then
  driven by the application. 20 tables, 11,093 listings, 77,754 photo rows, 28
  sites; `armory.match` compiled 808 rules from the restored table and still
  answered `Mosin-Nagant M91/30`. `deploy/RESTORE.md` is what was actually run.

  **Two things only a real attempt finds.** The first restore produced 218
  errors from `permission denied for schema public`, because the obvious
  `--role=milsurp` switches to a role that PostgreSQL 15 and later no longer
  grant `CREATE` on `public` — so every `CREATE TABLE` failed and the two
  hundred errors after it were constraints for tables that were never made.
  Restoring as the superuser and letting the dump carry its own ownership
  works. Worse than the error is its manners: `pg_restore` prints the failures
  and **still exits 0**, so a restore that created nothing looks from the shell
  like a restore that worked. The runbook counts tables afterward for that
  reason.

  The second: the bundle was dumped at Alembic `0024` and the code wanted
  `0026`. That is not a mistake, it is the normal case — backups are older than
  deployments — and it means `scripts/dbupdate.py` is part of restoring rather
  than a step after it. The quick recipe in `deploy/cron/README.md` had omitted
  it and would have left whoever followed it with a database the application
  refuses to start against.

  Still unproven, and recorded as such: the GPG-encrypted variant, a rebuild of
  a bare machine rather than a container, and reading the image mirror back.
- **Shipped** — Off-machine copies of those snapshots. Ten backups on the same
  disk as the database survive a bad UPDATE, which is what they were written
  for, but not a lost disk — and production is one VM in a house.

  `scripts/offsite-backup.sh` runs nightly as the `milsurp` account, takes a
  fresh snapshot, bundles it **with `config.yaml`**, sends it over ssh and
  verifies the byte count on the far side before pruning to ten.
  `scripts/offsite-images.sh` mirrors the photo store weekly with rsync.
  `deploy/cron/README.md` is the runbook.

  **The config travels with the dump, and that is the point.**
  `security.password_pepper` is HMAC'd into every password and now also
  derives the key that decrypts the TOTP secrets, and it is stored nowhere but
  that file. A database restored without it has no working logins, including
  the administrator's. A database-only backup looks complete and is not.

  **It says when it stops.** A cron job that quietly fails announces itself on
  the day the backup is needed, so the script writes a stamp beside the
  snapshots after its own byte-count check passes, and `milsurp canary` reports
  the age of it — two days, which is two missed nights, because complaining
  about one would teach whoever reads that email to skim it. The stamp is read
  rather than the far side: asking the application to check a NAS would mean
  giving it credentials for the one place a compromised application must not
  reach. A deployment that never set the job up is not nagged about a choice it
  made.

  It runs as `milsurp` rather than root or a login account: the snapshot
  directory is 0700 and `config.yaml` is 0600, both owned by it, so any other
  account would need those loosened. The key lives in `/etc/milsurp` rather
  than the account's home, which is `/opt/milsurp` — dpkg owns that and an
  upgrade rewrites it.

  **Three bugs surfaced in the ten minutes between writing it and trusting
  it**, and every one would have failed silently at 03:10 with the first sign
  being an empty directory on the day it was needed:

  * a default `NAS_PATH` of `/volume1/backups/milsurp` — a Synology-shaped
    guess about somebody else's filesystem, which a mistyped variable fell back
    to. Now required, like `NAS_TARGET`;
  * "cannot reach *host*" reported about a machine that had just answered:
    reaching the far side and being able to write there were one check, and are
    now two with two messages;
  * `-p` for the port, which means that to `ssh` and *preserve times* to
    `scp` — so scp read the port number as a filename. Now `-o Port=`, which
    means the same to both.

  That is the argument for running a backup by hand, and then once under cron,
  before believing in it.
- **Shipped** — `milsurp catch-up`, run from the postinst on every upgrade, so
  a rule change reaches rows already stored without anybody remembering to do
  it. A release changes how text is read, and nothing re-reads the catalog on
  its own: a scan only re-derives what it touches, so a fix reached the shelf a
  vendor happened to restock and no further. That left every upgrade depending
  on a manual pass, on every machine — the kind of step that gets skipped and
  then looks exactly like the fix never working.

  Every step is idempotent, which is what lets it run unattended: 11s for a
  first pass over 11,038 listings, under a second for a second pass. That is a
  property each step has to *keep*, not a hope — `reclassify` without
  `--recompute` only fills blanks, and `armory qualify` matches on the name it
  is about to change. Ordered, too: the armory is renamed before the listings
  are re-read, so the pass that reads them sees the finished table.

  Safe in the postinst for three reasons. The service is stopped for the
  duration — `dh_installsystemd`'s preinst does that on upgrade — so no scan is
  competing for the rows. Only a current schema gets there at all. And it is
  never fatal: a data pass that fails is a reason to look, not a reason to
  leave dpkg half-configured, which is the same argument the migration block
  beside it already makes.
- **Shipped** — Image store housekeeping on a schedule. `milsurp-prune.timer`
  runs `prune-images` nightly at 04:20 with jitter and `Persistent=true`, so a
  machine that was off at the hour catches up rather than skipping a day.

  The packaging holds the trap worth remembering: a unit belonging to package
  `milsurp` but *not named after it* must be installed as
  `debian/milsurp.<unit>.service`. Named `debian/milsurp-prune.service`,
  debhelper reads it as belonging to a package called `milsurp-prune`, finds
  none, and ships nothing — silently. Three attempts went into fixing the
  *enablement* before anyone checked whether the files were in the package.
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

- **Fixed** — The sign-in throttle could be used to exhaust the machine's
  memory, without credentials and without tripping anything.

  Failed sign-ins are counted in memory per `(username, address)`, which is the
  right key: it stops one attacker locking a real user out by guessing at their
  name from elsewhere. But the username half is a string the *attacker* writes,
  and the register was a plain dict that only ever pruned the key being looked
  at — writing the pruned list back even when it was empty:

  ```python
  recent = [t for t in _attempts.get(key, []) if now - t < LOCKOUT_SECONDS]
  _attempts[key] = recent          # an empty list, kept forever
  ```

  So a guess against a name nobody would guess twice stranded an entry that
  nothing would ever revisit, and nothing swept. Varying the username also
  means the per-key lockout never fires, so the counting worked perfectly while
  the structure doing it grew without limit. Measured at **171 bytes an entry**:
  2 MiB a day from a single address at nginx's own ceiling of ten sign-ins a
  minute, and **2.3 GiB a day from a thousand addresses** — an unremarkable
  botnet — with nothing in the logs but failed sign-ins.

  `app/ratelimit.py` now holds the invariant both call sites kept getting
  wrong: the register never exceeds `max_keys`, 50,000 by default, about 8 MiB.
  Stale keys are swept when it grows; if a sweep cannot get under the ceiling —
  that many *live* attackers at once — the least recently touched are evicted
  and **the eviction is logged**, because being at the ceiling is itself the
  thing worth knowing. Evicting weakens throttling for one key, which is the
  right way round: unbounded growth takes the site down for everybody.

  The access-request register had the identical bug and is on the same class.
  It is keyed by address alone, so a flood costs an attacker an address per
  entry rather than a keystroke — the same defect, one order of magnitude less
  cheap to exploit.

  **The first version of the fix was worse than the bug.** Evicting exactly one
  key per insert ran an `O(n log n)` sort on *every request* once the register
  was full — a CPU cost paid under precisely the flood it defended against.
  Cutting back to a low-water mark instead amortizes it: 18x on the suite, and
  `test_a_full_register_does_not_pay_a_sort_per_insert` pins it, because that
  is not a regression anything else would notice.
- **Fixed** — The migration chain could switch off the application's own
  logging. `alembic/env.py` called `logging.config.fileConfig`, which defaults
  to `disable_existing_loggers=True` and so disables every logger that already
  exists and is not named in `alembic.ini`. That file names three; the
  application has twenty-six `milsurp.*` loggers, all created when their modules
  import.

  It was not happening on a production boot — that was checked directly rather
  than assumed — but it *was* happening in the test suite, which migrates a
  throwaway database through the same chain. The same footgun landing somewhere
  harmless, and the distance between harmless and not is one import moving.

  Worth a fix and a test of its own because of how it fails: nothing raises and
  nothing is missing. The loggers still exist and still accept every call, and
  discard them. A failed sign-in would be recorded exactly as carefully as
  before and land nowhere — and the first you would know is going looking for
  an attack in a log that had been empty for months. Found by a test that kept
  passing alone and failing in company, which is usually a flaky test and this
  time was the test being right.

- **Shipped** — Two-factor authentication (TOTP). The admin sign-in is
  reachable from the internet through haproxy and a password was the only thing
  in front of it.

  **Written against the standard library rather than adding `pyotp`**, because
  the Debian package vendors every wheel it ships and this one would not have
  earned the build machinery. That trade is only defensible if the arithmetic
  is right, so it is tested against all six of RFC 6238's published vectors: if
  those pass, every authenticator app on every phone agrees with it.

  **The secret is encrypted at rest**, keyed from `security.password_pepper` —
  the same secret that is already HMAC'd into every password and lives in the
  config file rather than the database. A stolen dump that handed over both
  factors at once would make the second one decorative.

  Three decisions are about locking the owner out rather than keeping an
  attacker out, which is the likelier failure for a self-hosted thing:

  * **Enrollment is two steps.** The secret is issued and shown; only a code
    typed back from the phone turns it on. Collapsing them means a mistyped
    secret or a closed tab locks the account out.
  * **Ten recovery codes**, Argon2-hashed because one of them alone is the
    whole second factor, and with no I, O, 0 or 1 because they are read off
    paper by somebody already having a bad day. Accepted at the same prompt as
    a TOTP code, not behind a second link.
  * **`milsurp twofactor NAME --disable`** for when the phone and the codes are
    both gone. It bumps `token_version` too: somebody who lost control of a
    phone may have lost a session with it.

  Signing in is two exchanges. An account with two-factor gets a **200** saying
  `two_factor_required`, not a 401 — nothing has gone wrong, and a 401 would be
  indistinguishable from a wrong password to the page and to the logs. The
  throttle counter is deliberately left alone at that point: counting "the
  password was right and I have not asked yet" as a failure would lock somebody
  out halfway through their own sign-in. The code is checked only after the
  password is known good, so the response cannot be used to discover which
  accounts have it turned on.
- **Shipped** — One-time password reset links, sent by an administrator. This
  entry used to sit below as *deliberately not built*: self-service reset needs
  an unauthenticated endpoint that issues tokens to anybody who names an
  address. Admin-initiated keeps the **issuing** side authenticated, which was
  the whole of that objection, and leaves only redeeming open — which needs
  thirty-two random bytes.

  It is not new power. An admin could already set another account's password
  outright through `PATCH /api/users/{id}`; what changes is that the admin
  never learns the new one. The old flow's failure mode was "set it and tell
  them what it is", after which two people know it and it has been said aloud
  over whatever channel was to hand.

  Single use, an hour long, superseded by the next one issued for the account —
  an admin who presses the button twice because the first mail did not arrive
  must not leave two live credentials in a mailbox, the older being the one
  nobody is watching for. Hashed with Argon2, because while it is live the
  token *is* the password. Redeeming signs out every open session.

  **It does not walk past two-factor.** An account with an authenticator still
  needs it afterwards; a reset link that skipped the second factor would make a
  compromised mailbox enough to defeat it.

  When mail cannot be sent the link is handed back to the admin instead, so a
  deployment without SMTP has a working button rather than one that silently
  does nothing.
- **Shipped** — Audit log of administrative actions. User creation, edits and
  deletion, role changes, reset links issued, sites enabled and disabled, and
  sessions revoked — readable at **Audit log** in the admin navigation, with a
  filter that offers only the actions that have actually happened.

  **Three properties make it a record rather than a decoration.** It is
  append-only: nothing in the application edits or deletes a row, because a log
  somebody can tidy answers a different question from the one it appears to.
  The actor is kept twice, as an id and as a name, and the foreign key is `SET
  NULL` — deleting an account cannot erase what it did, and the row most worth
  reading is usually the one written by somebody who is no longer here. And
  recording can never break what it records: `audit.record` swallows its own
  failures, because an audit write that raised would turn "the log is full"
  into "nobody can create a user".

  A role change gets its own action so it can be filtered for, and the detail
  says `role normal -> admin` rather than "role changed" — noted before the
  edit, since afterwards there is nothing left to compare against.
- **Shipped** — Session management. Where this account is signed in, on the
  Security settings page, with per-session revoke and "sign out everywhere
  else".

  It needed the stateless token to grow a row. `token_version` retires *every*
  token at once — right for a password change, useless for closing the laptop
  you left at work without also signing yourself out of your phone — and
  nothing could answer "where am I signed in?" because nothing was written
  down. A login now writes a `user_sessions` row and the token carries its id;
  the cost is one primary-key lookup per request, beside the one already
  loading the user.

  Which session is *this* browser is labeled, because it is the first thing
  anybody looks for and signing yourself out by accident is the obvious
  mistake. "Sign out everywhere else" deliberately keeps the one asking:
  logging yourself out as a side effect of securing your account reads as the
  button having gone wrong.

  A token with no session id stays valid — one minted by a script, or issued
  before this existed. It was valid when it was handed out, and
  `token_version` is still what retires those.
- **Shipped** — The session is an `HttpOnly`/`Secure`/`SameSite=Strict` cookie
  with a double-submit CSRF token, instead of a bearer token in
  `sessionStorage` that any script on the page could read.

  The CSRF defense is the price, exactly as predicted, and it is checked in
  `get_current_user` where every authenticated route already passes. A request
  carrying an `Authorization` header is exempt, which is the same argument in
  reverse: a header has to be set deliberately and a forged request cannot set
  one. The header also wins when both arrive — explicit beats ambient, and
  anything with a cookie jar (`requests.Session`, the test client) ends up
  sending both.

  **Not "entirely" out of reach, and the difference is worth stating.** The
  login response still carries the raw token, because nothing else can obtain
  one and both scripts and the test suite need to. An XSS already running and
  able to intercept the sign-in can read that. What the cookie ends is the far
  larger exposure: a token sitting in storage for the whole session, readable
  at any moment.

  `Secure` is off in development, because it means HTTPS-only and development
  runs on plain http — a Secure cookie there is set and never sent back, which
  looks exactly like being signed out at random.

  Two things fell out of it. Signing out needs a server round trip now, so
  `POST /api/auth/logout` exists; the old sign-out only made the page forget a
  string, which a cookie ignores. And the armory's eye links navigate in the
  current tab for a reason that has now expired — `sessionStorage` was per-tab
  and a new tab landed on the sign-in screen; cookies are shared across tabs,
  so that is a preference now rather than a constraint, and the comment says
  so.

---

## 6. Testing and tooling

- **Shipped** — Recorded HTTP fixtures, so a parser can be tested against the
  markup it parses without asking the vendor. **25 of the 28 shops**, replayed
  by `backend/tests/test_recorded_scrapers.py`; the other three are listed in
  `NOT_RECORDABLE` with their reasons, and a scraper added without either fails
  the suite rather than quietly never being exercised.

  Recording happens at `ScrapeContext.get_text`, the single door every scraper
  goes through, so `scripts/record-fixtures.py` captures a whole scan without
  any scraper knowing about it. It runs the real context — robots.txt, the
  cooldown register and the politeness delay all apply — and stops through the
  application's own cancellation. It is the only thing in the repository that
  deliberately fetches from a vendor, and it is a target an operator runs.

  **The tests assert shape, never contents.** A recording is a photograph of a
  shop on one day; asserting it still sells a particular Mosin is a test that
  fails when somebody buys it. What is pinned is that listings come back, that
  each carries the key the database matches on, that no two share one, and that
  a price is absent or positive. Verified by breaking a parser on purpose: a
  one-character change to eBayonet's stock-number pattern turned four of these
  red.

  Royal Tiger is the exception that proves the seam: its catalog is drawn by
  JavaScript, so no server response contains it. Its fixture is one page the
  browser built, captured once and parsed directly by `test_royal_tiger.py`.
  Two independent guards keep it out of the replay set — the manifest's `kind`
  and the scraper's own `requires_browser` — because the first version trusted
  the label alone and the suite went off to open Chrome and fetch from the
  shop, which is precisely what these tests exist to stop.

  **It found something on the first run.** Two shops publish `$0.00` for a
  listing nobody has priced — a restricted launcher sold on enquiry, a Walther
  frame marked unavailable — and the scan stored the zero. Nothing rejected it,
  and zero is not a price: it reaches the deal comparison and the watchlist as
  the best offer anyone ever made. Fixing it took two edits, because there are
  two `parse_price` functions matching different patterns and BigCommerce
  reaches for the other one — which is itself the kind of thing only a test
  against real markup finds.
- **Shipped** — The browser is found where Ubuntu actually puts it. `apt
  install chromium-browser` reports success, installs a working browser, and
  leaves Selenium reporting "Unable to obtain driver for chrome" — because on
  Ubuntu that deb is a transitional shim for a **snap**, and the binary lands
  at `/snap/bin/chromium`, which Selenium Manager never tries. It looks for
  "chrome" and "google-chrome", and the machine has neither.

  The old message said "Install Google Chrome", which sends whoever reads it to
  reinstall the thing they already have — and did, on the production VM the
  first night the canary ran there. `browser.py` now tries a list of real
  paths, real Chrome first and the snap after, and says what it looked for when
  it finds nothing. The configuration still wins where it is set: an install
  that names its own paths has made a decision. `debian/control` recommends
  `chromium-driver` rather than the shim.
- **Shipped** — The canary stops blaming a vendor for our own politeness. A
  host the cooldown register is pacing gets a gap of up to a minute between
  requests, so two requests cannot fit in a ninety-second budget and never
  will: checkpointcharlies.com, on a 60s gap after refusing a run of photo
  fetches, was reported as a **timeout** on the first production sweep. The
  budget now grows by that gap, and a timeout on a paced host says whose
  waiting it was.

  Both of that night's failures were the same shape — the canary reporting our
  own side as a vendor fault. A monitor whose false alarms all point outward is
  one you learn to ignore, which is the failure that matters most for something
  meant to be read once a night.
- **Shipped** — A nightly canary against every enabled site, which fails loudly
  when a vendor stops answering *or* when its markup moves. `milsurp canary`,
  `make canary`, and `milsurp-canary.timer` at 06:10.

  The probe is the real scrape, stopped after three listings. A scraper is a
  generator, so consuming three and breaking closes it where it stands — which
  exercises robots.txt, the session's identity, the politeness delay, the
  catalog fetch and the parser for about a page of work per shop. Twenty-seven
  shops took 100 seconds. It writes nothing: a canary that stored listings
  would be a scan, and an abandoned scan de-lists everything it never reached.

  The early stop only helps a scraper that yields as it reads. Royal Tiger
  drives all of its sections through Chrome and collects them into a dict
  *before* its first yield, so a probe there cannot reach listing one until the
  whole grid pass is done — 507s measured, against real scans of 512–572s. It
  gets its own 720s budget and the unit gets 2G rather than 768M, because a
  canary killed by its own stopwatch or its own cgroup reports a working site
  as broken, and nothing teaches somebody to ignore an alarm faster.

  Five verdicts rather than one "failed", because the repairs are different
  files. `REFUSED` is a conversation with the vendor — an address, an identity,
  a rate. `EMPTY` is our parser being wrong about their page. `RESTING` is our
  own cooldown register. `TIMEOUT` and `BROKE` are the rest.

  Why it earns a place at all: the failure is silent. A vendor that starts
  refusing us and a vendor whose markup moved both end in a scan that stores
  nothing, and that is indistinguishable from a shop with empty shelves. Six of
  the twenty-eight answer 403 to a request they dislike, and one datacenter IP
  earned it from all six at once.

  The first sweep found two real problems nothing else had reported, both since
  fixed:

  **The cooldown sawtooth.** `checkpoint-charlies` had failed three days
  running, at `refusals=8` where every refusal sets the one-hour ceiling. The
  cause was that a success *deleted* the register row outright, so eight
  refusals of accumulated evidence were erased by one photograph arriving — and
  the pace learned from a 429 lived in a per-process dict, so the next
  `fetch-photos` opened at full speed and was refused within the second. Now a
  success decays the count by one and lifts only the pause, and `pace_for()`
  turns whatever is left into a gap every fetcher honors, across processes.
  That is the half of "the pace a scan learns used to die with the process"
  that the original stop/go register never covered. Recovery went from never to
  about a minute.

  **robots.txt answering 403.** `hunters-lodge` keeps its whole catalog in one
  flyer image on `static.wixstatic.com`, which answers 403 to `/robots.txt`
  permanently — so the flyer could never be fetched, masked only because the
  unchanged-flyer short circuit returned before trying. 401 and 403 now mean
  "no readable rules, so none to honor", per RFC 9309 §2.3.1.3, instead of "off
  limits for now". This is the second time that reading cost listings: one
  Cloudflare 403 on J&G Sales had already de-listed 64 of them.

  After both, 26 of 27 answer, and the 27th recovers on its own inside a minute.
- **Fixed** — `scripts/security.sh` reporting a network outage as a
  vulnerability. `npm audit` exits non-zero both for "you have vulnerabilities"
  and for "I could not reach the registry", and the script read the second as
  the first — failing the scan with *"npm audit found vulnerable packages"*
  over a report file that said `audit endpoint returned an error` in as many
  words. Told apart on the message now, and reported as skipped, which is what
  the script's own header already promises for a tool it cannot run. A scan
  that cannot reach its data has not found anything, and saying it has teaches
  people to ignore the real ones.
- **Fixed** — A browser failure on production that diagnosed itself as the
  wrong thing. Royal Tiger reported *"Service /snap/bin/chromium.chromedriver
  unexpectedly exited. Status code was: 46"*, and the message that followed
  named six search paths and two config keys — every one of which was already
  correct. The browser was found and correctly paired with the only driver that
  can drive it.

  A snap is not an ordinary executable: `snap-confine` builds the sandbox
  first, using privileges it takes from file capabilities, and
  `NoNewPrivileges=true` in the shipped unit is precisely a promise that no
  executable ever will. `RestrictNamespaces=true` denies the mount namespace
  the sandbox is made of, and `SystemCallFilter=@system-service` covers neither
  `mount` nor `pivot_root`. Three independent directives, any one of them
  fatal.

  So the two cannot both be right, and the hardening is the half worth keeping
  — a scraper runs a stranger's JavaScript and is the last process on the
  machine that should be able to escalate. The fix is a non-snap browser, which
  needs no configuration at all. What shipped is the *diagnosis*: the process
  reads `NoNewPrivs` from `/proc/self/status`, and when the only browser found
  is under `/snap/` it says so, names the directives, and says plainly that
  nothing in `config.yaml` can bridge it.
- **Fixed** — The same afternoon lost twice, to the same file. With the snap
  ruled out and Google Chrome installed from its `.deb`, Royal Tiger still
  broke: *"Service /usr/bin/chromedriver unexpectedly exited. Status code was:
  1"*, with a real driver sitting unused at `/usr/local/bin/chromedriver`.

  On Ubuntu `/usr/bin/chromedriver` is a shim for the snap — **which the
  module's own comment had said for months** while the preference list below it
  still reached for that path first. The knowledge was in the prose and not in
  the code.

  Two fixes, because the ordering alone would only have moved the trap. The
  packaged Chromes now try `/usr/local/bin/chromedriver` first: that is where an
  administrator puts something on purpose, and on this question their deliberate
  act outranks whatever apt left behind. And a snap driver is skipped outright
  for a browser that is not itself a snap — `is_snap_driver` resolves symlinks
  into `/snap/` and reads the small wrapper scripts that exec it, stating the
  module's founding invariant once in code rather than trusting it to the order
  of a dictionary. Anything unreadable or large is taken at face value, since a
  false "this is a snap" would hide a working driver, which is the worse
  mistake of the two.
- **Shipped** — Email when a *scan* fails, not only when the nightly canary
  does. `app/services/scanalerts.py`, hooked into the one place every run is
  closed out, after the commit — a message describing a scan that was then
  rolled back would be worse than no message.

  The canary probes every shop at 06:10 and mails what it finds, which covers a
  vendor changing its markup. It is a separate probe, though, and that left two
  gaps: a scan dying at 02:00 waited four hours to be noticed, and the canary
  stops after three listings, so a failure on page nine — a pagination change, a
  detail page that started 404ing — passed it while every real scan failed.

  **A change of state, never a standing condition**, which is the whole
  discipline and the reason it is worth having. A site broken for a fortnight
  must not mail every night for a fortnight: by the third night it is a rule in
  somebody's mail client and by the fifth the next real failure lands in the
  same folder unread. So the question asked is not "did this scan fail?" but
  "is this different from last time?" Recovery is reported for the same reason
  failure is — somebody told a shop went quiet is owed the sentence saying it
  came back.

  Three verdicts that deliberately say nothing. `PARTIAL` is some pages or
  images failing while the catalog came through, which is a warning on the
  scan's own record and not a vendor gone quiet. `CANCELED` is an administrator
  pressing stop, and it does not count as the previous verdict either — or a
  cancel between two failures would make the second look like news. And a
  first-ever scan that *works* is not news: nobody needs telling that a thing
  did what it was installed to do.

  Never raises. Alerting that can break a scan turns every mail outage into a
  scraping outage, and the failure it reports is its own.
- **Fixed** — CodeQL #41, *clear-text logging of sensitive information*, High,
  `services/audit.py:98`. The line is `log.exception("Could not record audit
  event %s", action)`, and the "sensitive information" was the action name —
  because one of them was `USER_PASSWORD_RESET = "user.password_reset_sent"`.

  **The third tool to read that constant as a credential.** Ruff's S105 and
  bandit's B105 had both flagged it, and both had been suppressed inline for
  months; CodeQL simply found the same name by the same heuristic and followed
  it to a logging call. No password was within reach of any of them: the value
  is the name of something that happened.

  So the constant is renamed to `USER_RESET_LINK_SENT` / `user.reset_link_sent`
  — named for what it is, a link being mailed, rather than for the thing the
  link eventually lets somebody change. **Verified locally rather than
  assumed**: with the two suppressions deleted and the old name restored, ruff
  and bandit each flag it again; with the new name and no suppressions, both
  fall silent. That is the heuristic identified directly, which is as close to
  running CodeQL as this machine gets. Migration 0033 rewrites the rows already
  written so the action has one spelling, and the audit page keeps a label for
  the old string for a database restored from an older snapshot.

  A test now walks every upper-case string constant in the module and fails on
  any that reads as a credential, so the next action somebody adds cannot
  quietly bring the problem back.

  The same pass removed a flag argument that put a password-named value on the
  path into the audit log: `_what_changed(..., password_set: bool)` used it
  only to append a constant string, so the caller appends it instead. A boolean
  is not a secret, but a static analyzer is right to look twice at that shape.
- **Planned** — Visual regression tests on the screenshots `make screenshots`
  already produces.
- **Shipped** — Raise the coverage floors. **Backend 65% → 83%** against a
  measured 88.0%, **frontend 65% → 76%** statements and 77% lines against
  81.2% and 81.9%, with branches 50% → 70% and functions 55% → 73%.

  The suite had been sitting twenty-three points above its own gate, which
  means a floor that number could not fail anything short of deleting a
  module. Each is now set a few points under the measured figure: far enough
  not to fail a new module that is honestly thinner than the average, close
  enough that a real regression cannot pass. A gate two dozen points below
  reality is not a gate.
