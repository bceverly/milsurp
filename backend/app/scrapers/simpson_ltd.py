"""Simpson Ltd. (simpsonltd.com).

**The roadmap had this filed as needing a browser, and that was wrong.** The
recorded finding was: "the catalog is in Firestore (project simpsonltd-bfd2b)
and its rules refuse an unauthenticated read; anonymous sign-in is disabled
too." Every word of that is true and it is the wrong door. The React bundle
does not talk to Firestore directly -- it calls **Cloud Functions** on the same
project, and those answer a plain unauthenticated GET::

    https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/fetchDataByCategory_v3
    https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/searchWebItems_v3

This is the seventh vendor filed as unreachable that had an endpoint, and the
second one this month where the note in the roadmap was written from the shape
of a response rather than from reading it. Their robots.txt is ``Disallow:``
with nothing after it -- everything is permitted -- and both the function host
and the image host answer 404 for robots.txt, so nothing here needs an
exception.

**One request is very nearly a whole listing.** The category response carries
the title, the full description, the asking price, the caliber, the action, the
bore and stock condition and the FFL class -- everything except the gallery,
where it gives two thumbnails (``D36066AT.webp``) out of the six to ten
full-size photographs the listing actually has. ``fetchSKU_Inventory?sku=`` has
the rest, so there is a detail fetch, but it costs only pictures: a listing
whose detail fails is complete in every other respect, and the two thumbnails
are converted to their full-size names rather than stored as thumbnails.

**The scope is the milsurp shelves, and this vendor makes that decision
matter.** Simpson list **19,201 items, every one of them priced, pictured and
in stock** -- their sold stock is simply not returned. That is three times the
size of everything this application currently holds, and most of it is a
sporting-goods catalog: 3,057 shotguns, and Winchester, Remington, Ruger,
Savage, Marlin and Anschutz sections beside them. What is taken is listed in
``SOURCES`` below and what is deliberately left is in ``NOT_READ``, so widening
this is an edit to one tuple rather than a rewrite.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote, urlencode

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper

SITE_BASE = "https://www.simpsonltd.com/"
API = "https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/fetchDataByCategory_v3"
#: One listing's full gallery. Note the lower-case parameter: ``SKU=`` is
#: answered with "SKU parameter is required", which reads as the endpoint being
#: broken rather than as a spelling being wrong.
SKU_API = "https://us-central1-simpsonltd-bfd2b.cloudfunctions.net/fetchSKU_Inventory"

#: Detail requests that may fail before the rest of the scan gives up on them.
MAX_DETAIL_FAILURES = 5

#: The shelves worth reading. A whole category where the whole category is on
#: subject -- Lugers, the German .22 training rifles, the antiques -- and one
#: entry per subcategory where it is not.
#:
#: Counts are from 11 Sep 2026 and are here to show the shape, not as a
#: promise: about 5,200 listings, against 19,201 in the whole shop.
SOURCES: tuple[dict[str, str], ...] = (
    # Whole categories.
    {"category": "Lugers"},  # 1,157 -- the reason this vendor is worth having
    {"category": "German 22 Trainers"},  # 355 Wehrmacht training rifles
    {"category": "Antiques"},  # 371
    # Long guns, by subcategory: their "Long Guns" is 7,806 and 3,057 of those
    # are shotguns.
    {"category": "Long Guns", "subcategory": "Military Rifles"},  # 1,658
    {"category": "Long Guns", "subcategory": "Mauser"},  # 174
    {"category": "Long Guns", "subcategory": "Assault Type Rifles"},  # 71
    {"category": "Long Guns", "subcategory": "Fabrique National"},  # 54
    {"category": "Long Guns", "subcategory": "Steyr"},  # 29
    # Handguns, likewise: 3,115 in total and most of it Colt, Smith & Wesson
    # and Hi Standard.
    {"category": "Hand Guns", "subcategory": "Military"},  # 164
    {"category": "Hand Guns", "subcategory": "Walther"},  # 321
    {"category": "Hand Guns", "subcategory": "Swiss"},  # 173
    {"category": "Hand Guns", "subcategory": "Mauser"},  # 152
    {"category": "Hand Guns", "subcategory": "Hi Power"},  # 96
    {"category": "Hand Guns", "subcategory": "Fabrique National"},  # 63
    {"category": "Hand Guns", "subcategory": "Star"},  # 49
    {"category": "Hand Guns", "subcategory": "P-38"},  # 41
    {"category": "Hand Guns", "subcategory": "Webley"},  # 20
    {"category": "Hand Guns", "subcategory": "Czech"},  # 13
    # Bayonets only. Their Edged Weapons is 830 and 364 of those are
    # non-military knives.
    {"category": "Edged Weapons", "subcategory": "Bayonets"},  # 280
)

#: What is deliberately not read, so the decision is reviewable rather than
#: implied by an absence. Roughly 14,000 listings.
#:
#: * ``Long Guns`` -- Shotguns (3,057), Winchester, Remington, Ruger, Savage,
#:   Stevens, Marlin, Browning, Husqvarna, Anschutz, Modern Reproduction,
#:   Modern Blackpowder, Drilling & Combination, English & European Rifles:
#:   a sporting catalog. BRNO (284) is the closest call -- they built military
#:   vz.24 Mausers -- but the section is their post-war sporting rifles.
#: * ``Hand Guns`` -- Colt, Smith & Wesson, Hi Standard, Ruger, SIG, Beretta,
#:   Browning, Glock, Remington, Springfield Armory, Modern Reproduction.
#: * ``Militaria`` (1,501), ``Printed Materials`` (975), ``Firearm
#:   Accessories`` (1,976), ``Other Items`` (482): gear, books, grips, stocks,
#:   optics, watches and pool cues. The standing rule here is firearms and
#:   parts kits.
#: * ``Edged Weapons`` apart from bayonets: swords, daggers and kitchen knives.
NOT_READ = (
    (
        "Long Guns: Shotguns, Winchester, Remington, Ruger, Savage, Stevens, "
        "Marlin, Browning, Husqvarna, Anschutz, BRNO, Modern Reproduction, "
        "Modern Blackpowder, Drilling & Combination, English & European "
        "Rifles, Other Manufacturers"
    ),
    (
        "Hand Guns: Colt, Smith & Wesson, Hi Standard, Ruger, SIG, Beretta, "
        "Browning, Glock, Remington, Springfield Armory, Modern Reproduction, "
        "Assault Type Handguns, Modern Blackpowder, Other Manufacturers"
    ),
    "Militaria, Printed Materials, Firearm Accessories, Other Items",
    "Edged Weapons: Swords, Daggers, Knives, Non-Military Knives",
)

#: A hundred, which is this endpoint's ceiling -- ask for 250 and it returns a
#: hundred.
#:
#: **The parameters are ``page`` and ``limit``.** ``currentPage`` and
#: ``itemsPerPage`` are what ``searchWebItems_v3`` beside it takes, and this
#: one accepts them, echoes ``currentPage`` back unchanged, and serves page one
#: every time. The first version of this scraper used those names and read ten
#: listings per shelf -- 190 in total, against 5,200 -- while making a hundred
#: and sixteen requests per shelf to do it. Nothing in the response says the
#: parameter was ignored; the row count and ``totalPages`` both look right.
PAGE_SIZE = 100

#: A guard, not a claim: the largest shelf here is 1,658 listings, or 17 pages.
MAX_PAGES = 60


#: How the thumbnail names its full-size original: ``D36066AT.webp`` is the
#: thumbnail of ``D36066A.jpg``. Worth deriving rather than fetching, so a
#: listing whose detail request fails still has real photographs.
def full_size(url: str) -> str:
    if url.endswith("T.webp"):
        return url[: -len("T.webp")] + ".jpg"
    return url


def product_url(sku: str) -> str:
    return f"{SITE_BASE}products/{quote(str(sku))}"


def endpoint(source: dict[str, str], page: int) -> str:
    query: dict[str, Any] = {
        "category": source["category"],
        "page": page,
        "limit": PAGE_SIZE,
    }
    if source.get("subcategory"):
        query["subcategory"] = source["subcategory"]
    return f"{API}?{urlencode(query)}"


#: Subcategory names that Simpson use under more than one category. "Mauser"
#: is a shelf of rifles *and* a shelf of pistols, and so is "Fabrique
#: National"; filing both under the bare name puts 440 listings behind one
#: browse facet that mixes the two. Worked out from SOURCES rather than listed
#: by hand, so a shelf added later cannot quietly collide.
_AMBIGUOUS_SUBCATEGORIES = {
    name
    for name in {source.get("subcategory") for source in SOURCES}
    if name
    and len({source["category"] for source in SOURCES if source.get("subcategory") == name}) > 1
}


def label_of(source: dict[str, str]) -> str:
    """What a listing is filed under here.

    The subcategory where there is one, because "Military Rifles" says more
    than "Long Guns" and the browse facet is the poorer for the broader name --
    but qualified where the subcategory alone would be ambiguous, so that
    "Long Guns / Mauser" and "Hand Guns / Mauser" stay apart.

    Short names are kept where they are unique. A category facet reading
    "Mauser" would also be answering a question the manufacturer filter already
    answers better, and answering it worse: it would cover this vendor's
    Mausers and not the two hundred from everybody else.
    """
    subcategory = source.get("subcategory")
    if not subcategory:
        return source["category"]
    if subcategory in _AMBIGUOUS_SUBCATEGORIES:
        return f"{source['category']} / {subcategory}"
    return subcategory


def _price(record: dict[str, Any]) -> float | None:
    """The asking price.

    ``Wants`` is what they are asking today: on a reduced listing it already
    holds the reduced figure, with ``OriginalPrice`` keeping the old one. Zero
    means no price rather than free.
    """
    for field in ("Wants", "ReducedPrice", "OriginalPrice"):
        value = record.get(field)
        try:
            price = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


def _condition(record: dict[str, Any]) -> str | None:
    """Their own grading, which is per-part rather than a single word.

    "Bore: good, Stock: fair" is more than this application's single condition
    field can hold, so the bore wins -- it is what the classifier's own bore
    grading reads elsewhere, and it is what a collector asks first.
    """
    bore = (record.get("Bore") or "").strip()
    return bore or None


def item_from_record(record: dict[str, Any], label: str) -> ScrapedItem | None:
    """One listing, complete. There is no second request for this one."""
    sku = str(record.get("SKU") or "").strip()
    title = (record.get("Title") or "").strip()
    if not sku or not title:
        return None
    return ScrapedItem(
        external_key=sku,
        url=product_url(sku),
        title=title,
        price=_price(record),
        description=(record.get("Description") or "").strip() or None,
        category=label,
        caliber=(record.get("Caliber") or "").strip() or None,
        condition=_condition(record),
        # Their own word for it: "Pistol", "Rifle", "Revolver", "Shotgun",
        # and *blank on accessories* -- 112 of the 129 accessory-sounding
        # titles in the first 500 Lugers carry no Type at all. So a value here
        # is a positive claim and the blank is an answer, which is what makes
        # it safe to outrank the heuristics. See Item.stated_kind.
        stated_kind=(record.get("Type") or "").strip() or None,
        is_sold=bool(record.get("Sold")),
        image_urls=[full_size(url) for url in (record.get("imageUrls") or []) if url],
        # Two of six to ten. with_detail() fetches the rest.
        images_are_complete=False,
    )


class SimpsonLtdScraper(SiteScraper):
    slug = "simpson-ltd"
    name = "Simpson Ltd."
    base_url = SITE_BASE
    description = (
        "Galesburg, Illinois collector dealer, read through the Cloud "
        "Functions its own site calls. The Luger, military rifle, antique and "
        "German trainer shelves; their sporting catalog is left alone."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def __init__(self) -> None:
        self._detail_failures = 0
        self._gave_up_on_details = False

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        """Yielded one at a time rather than returned as a list.

        This shelf list is about 5,200 listings and each one wants a gallery
        request, so a scan of this vendor runs for over an hour. The scan
        service commits after every item it is handed, so yielding means the
        catalog lands as it arrives and an interrupted run keeps what it had;
        building the list first would write nothing at all until the end, and
        lose every bit of it to one timeout in the ninetieth minute.
        """
        seen: set[str] = set()
        count = 0

        for source in SOURCES:
            ctx.check_stop()
            label = label_of(source)
            ctx.log(f"Reading {source['category']} / {label}…")
            for item in self._walk(ctx, source, label):
                if item.external_key in seen:
                    # A Luger filed under both Lugers and Hand Guns is one gun.
                    continue
                seen.add(item.external_key)
                yield self.with_gallery(ctx, item)
                count += 1

        if not count:
            raise ScrapeError("no listings were returned by any Simpson Ltd. shelf")

    def _walk(
        self, ctx: ScrapeContext, source: dict[str, str], label: str
    ) -> Iterable[ScrapedItem]:
        """Every page of one shelf."""
        total_pages: int | None = None
        for page in range(1, MAX_PAGES + 1):
            ctx.check_stop()
            url = endpoint(source, page)
            try:
                document = self._page(ctx, url)
            except ScrapeError as exc:
                # One shelf of twenty is not the catalog. The run reports
                # PARTIAL rather than losing the other nineteen.
                ctx.warn(f"could not read {label}: {exc}")
                return

            records = document.get("data") or []
            if not records:
                return
            for record in records:
                item = item_from_record(record, label)
                if item is not None:
                    yield item

            if total_pages is None:
                total_pages = document.get("totalPages") or None
            if total_pages is not None and page >= total_pages:
                return
        ctx.warn(f"{label} stopped at the {MAX_PAGES}-page ceiling.")

    def _page(self, ctx: ScrapeContext, url: str) -> dict[str, Any]:
        raw = ctx.get_text(url)
        try:
            document = json.loads(raw)
        except ValueError as exc:
            raise ScrapeError(f"GET {url}: expected JSON, got something else ({exc})") from exc
        if not isinstance(document, dict):
            raise ScrapeError(f"GET {url}: expected an object, got {type(document).__name__}")
        return document

    def with_gallery(self, ctx: ScrapeContext, item: ScrapedItem) -> ScrapedItem:
        """The full-size photographs, which the category listing truncates.

        Everything else about the listing is already in hand, so a failure here
        costs pictures and nothing else -- and the two derived full-size names
        from the catalog survive it.
        """
        if not ctx.needs_detail(item.external_key) or self._gave_up_on_details:
            return item
        try:
            document = self._page(ctx, f"{SKU_API}?{urlencode({'sku': item.external_key})}")
        except ScrapeError as exc:
            self._detail_failures += 1
            if self._detail_failures >= MAX_DETAIL_FAILURES:
                self._gave_up_on_details = True
                ctx.warn(
                    f"{self._detail_failures} gallery requests failed; taking the rest of "
                    f"this scan from the catalog thumbnails only. Last error: {exc}"
                )
            return item

        record = document.get("data") or {}
        gallery = [url for url in (record.get("imageUrls") or []) if url]
        if gallery:
            item.image_urls = gallery
        item.images_are_complete = True
        return item
