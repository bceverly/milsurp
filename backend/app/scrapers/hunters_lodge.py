"""Hunter's Lodge Corporation — a vendor whose entire catalog is one picture.

Hunter's Lodge publishes no product pages. It runs a full-page advertisement in
*Firearms News*, scans it, and posts that scan on its home page with a line of
text above saying which issue it is from. Every rifle, pistol, bayonet and
blanket the company is selling this month is inside that one image.

So this scraper does not crawl. It:

1. finds the flyer and the issue line on the home page;
2. stops immediately if neither has changed since the last scan;
3. downloads the flyer at full resolution;
4. hands it to :mod:`.flyer`, which segments, reads and crops it;
5. emits one listing per product, each carrying its own crop of the scan.

**On accuracy.** The listings come out of OCR of a dense, ruled, two-column
magazine advertisement — the hardest kind of page to read automatically.
Measured against a real July 2026 flyer this recovers around twenty listings
with their names and prices, which is most but not all of the page, and a few
of them take a neighbouring panel's price. That is worth having and it is not
worth pretending otherwise: every listing carries the crop it was read from, so
the flyer itself is always one click away, and the description keeps the raw
OCR text rather than a tidied summary of it. Treat the prices as a prompt to go
and look, not as a quotation.

**On politeness.** A new flyer appears every month or two. The default cadence
is weekly, and a scan that finds nothing new finishes in one request.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag
from PIL import Image

from . import flyer as flyer_reader
from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

log = logging.getLogger("milsurp.scraper.hunters_lodge")

SITE_BASE = "https://www.hunterslodge.com/"

#: Wix serves every image through a transform path:
#:
#:     .../media/<id>~mv2.jpg/v1/fill/w_600,h_844,.../Some%20Name.jpg
#:
#: Everything from ``/v1/`` onwards is a resize of the original. Cutting it off
#: gives the untouched upload, which for this flyer is 4813x6774 rather than
#: the 600x844 the page displays — the difference between OCR that works and
#: OCR that returns nothing.
WIX_TRANSFORM = re.compile(r"/v1/[^\s\"']*$")

#: The media id inside a Wix URL. It changes when a new file is uploaded, which
#: makes it the most reliable "is this a different flyer?" signal available.
WIX_MEDIA_ID = re.compile(r"/media/([A-Za-z0-9_]+~mv2)\.(?:jpg|jpeg|png|webp)", re.I)

#: The line above the flyer, e.g. "Issue from Firearms News for  for July  2026".
ISSUE_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\b[^0-9]{0,12}(20\d{2})",
    re.I,
)

#: Images that are furniture rather than the flyer.
IGNORED_IMAGE_HINTS = ("logo", "icon", "favicon", "button")

#: A flyer is a big portrait scan. Anything much smaller is a logo.
MIN_FLYER_PIXELS = 1_000_000


class HuntersLodgeScraper(SiteScraper):
    slug = "hunters-lodge"
    name = "Hunter's Lodge"
    base_url = SITE_BASE
    description = (
        "Publishes no catalog: one scanned magazine advertisement, replaced every "
        "month or two. Listings are recovered from the image by OCR."
    )
    requires_browser = False
    #: True, and it took two goes to earn that.
    #:
    #: A listing's description is whatever OCR read near it, which used to
    #: include the panel next door: hand-woven blankets came back chambered in
    #: 8mm Mauser, the cartridge of the Spanish M43 rifles advertised beneath
    #: them. The first answer was to distrust the whole description for this
    #: vendor, which stopped the wrong answers and threw away the right ones
    #: with them — "SPANISH 1916 SHORT RIFLES 7x57" then had no caliber either,
    #: because the 7x57 is in its own description.
    #:
    #: flyer.only_this_listing() now trims each description to the part that is
    #: about its own listing, so there is nothing left to distrust.
    #: Weekly. A new flyer appears every month or two, and a scan that finds the
    #: same one does a single request, so there is nothing to gain from asking
    #: more often and a real cost to the vendor in asking much more.
    default_interval_minutes = 60 * 24 * 7

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        html = ctx.get_text(SITE_BASE)
        soup = BeautifulSoup(html, "html.parser")

        image_url = self._find_flyer(soup)
        if not image_url:
            raise ScrapeError(
                "No flyer image found on the Hunter's Lodge home page. The site "
                "may have been redesigned; the scraper needs updating."
            )

        original = WIX_TRANSFORM.sub("", image_url)
        media = WIX_MEDIA_ID.search(original)
        flyer_id = media.group(1) if media else original.rsplit("/", 1)[-1]
        issue = self._find_issue(soup)
        # The signature goes into every external_key and into the stored image
        # filenames, so it is slugified rather than left as "July 2026".
        signature = f"{flyer_id}-{issue.lower().replace(' ', '-')}" if issue else flyer_id
        ctx.log(f"Flyer {flyer_id}" + (f", issue {issue}" if issue else ""))

        # The catalog is derived from the flyer, so if the flyer is the one we
        # already read, there is nothing to derive. The signature is baked into
        # every key, so asking whether anything is stored under it asks whether
        # this flyer has been read at all.
        if ctx.already_seen(f"{signature}-"):
            ctx.report_unchanged(
                "Flyer and issue are unchanged since the last scan; nothing to re-read."
            )
            return

        page = self._download_flyer(ctx, original)
        ctx.log(f"Flyer downloaded: {page.width}x{page.height}. Reading…")

        listings = flyer_reader.read_flyer(page)
        ctx.log(f"OCR recovered {len(listings)} listing(s) from the flyer.")
        if not listings:
            # Better a single item saying "there is a new flyer, go and look"
            # than a scan that reports success and shows nothing.
            ctx.warn("Could not read any listings from the flyer; keeping it whole.")
            yield self._whole_flyer(signature, issue, page, image_url)
            return

        taken: dict[str, int] = {}
        for index, listing in enumerate(listings, start=1):
            yield self._to_item(signature, issue, index, listing, page, image_url, taken)

    # -- the page -----------------------------------------------------------
    def _find_flyer(self, soup: BeautifulSoup) -> str | None:
        """The largest content image on the page, which is the flyer.

        Chosen by the dimensions the page itself declares rather than by
        position or class name: Wix regenerates its class names, but a scan of
        a magazine page is always by far the biggest picture on the site.
        """
        best: tuple[int, str] | None = None
        for tag in soup.find_all("img"):
            if not isinstance(tag, Tag):
                continue
            src = tag.get("src")
            if not isinstance(src, str) or not src.startswith("http"):
                continue
            haystack = f"{src} {tag.get('alt') or ''}".lower()
            if any(hint in haystack for hint in IGNORED_IMAGE_HINTS):
                continue
            try:
                area = int(str(tag.get("width") or 0)) * int(str(tag.get("height") or 0))
            except ValueError:
                area = 0
            if best is None or area > best[0]:
                best = (area, src)
        return best[1] if best else None

    def _find_issue(self, soup: BeautifulSoup) -> str | None:
        """The month and year of the current advertisement, if it is stated.

        Read from the whole page rather than from a specific element: the line
        has been phrased at least two ways ("Issue from Firearms News for  for
        July  2026"), and any month-and-year on a page that shows one flyer is
        that flyer's.
        """
        match = ISSUE_PATTERN.search(normalize_whitespace(soup.get_text(" ")))
        if not match:
            return None
        return f"{match.group(1).title()} {match.group(2)}"

    def _download_flyer(self, ctx: ScrapeContext, url: str) -> Image.Image:
        response = ctx.get(url)
        data = response.content
        if len(data) < 10_000:
            raise ScrapeError(f"Flyer at {url} is too small to be a scan ({len(data)} bytes).")
        try:
            page = Image.open(io.BytesIO(data))
            page.load()
        except Exception as exc:
            raise ScrapeError(f"Could not decode the flyer at {url}: {exc}") from exc
        if page.width * page.height < MIN_FLYER_PIXELS:
            raise ScrapeError(
                f"Flyer at {url} is {page.width}x{page.height}, too small to read. "
                "The full-resolution original may no longer be reachable."
            )
        return page

    # -- listings -----------------------------------------------------------
    def _to_item(
        self,
        signature: str,
        issue: str | None,
        index: int,
        listing: flyer_reader.FlyerListing,
        page: Image.Image,
        flyer_url: str,
        taken: dict[str, int],
    ) -> ScrapedItem:
        key = self._key_for(signature, listing.title or f"listing {index}", taken)
        crop = flyer_reader.crop_for_listing(page, listing.box)
        description = listing.description
        if issue:
            description = f"{description}\n\nFrom the {issue} Firearms News advertisement."
        return ScrapedItem(
            external_key=key,
            # There is no per-product page to link to; the home page is where
            # the flyer this came from is shown.
            url=SITE_BASE,
            title=listing.title or f"Hunter's Lodge listing {index}",
            price=listing.price,
            description=description,
            category="Flyer",
            generated_images=[(f"{key}.png", crop)],
            extra={"flyer_url": flyer_url, "issue": issue or "", "ocr_lines": listing.lines},
        )

    @staticmethod
    def _key_for(signature: str, title: str, taken: dict[str, int]) -> str:
        """A key that follows the product rather than its place on the page.

        It was the ordinal — "…-013" — which is stable only while the reader
        is. Improving the reader by one listing shifted every key after it onto
        a different product, which the scan service read as the whole lower
        half of the flyer changing price at once: one such change produced
        seventeen price changes and ten drops, none of which had happened, and
        a price-drop email is worth nothing if it can do that.

        Derived from the title, so a listing keeps its identity and its history
        while it keeps its name, and a listing we now read differently is
        honestly a different listing. Duplicates within one flyer are numbered,
        which is the one case where position is the only thing telling two
        listings apart.
        """
        digest = hashlib.sha256(" ".join(title.lower().split()).encode("utf-8")).hexdigest()[:10]
        taken[digest] = taken.get(digest, 0) + 1
        suffix = "" if taken[digest] == 1 else f"-{taken[digest]}"
        return f"{signature}-{digest}{suffix}"

    def _whole_flyer(
        self, signature: str, issue: str | None, page: Image.Image, flyer_url: str
    ) -> ScrapedItem:
        """One item carrying the entire flyer, for when OCR recovers nothing."""
        key = f"{signature}-whole"
        whole = flyer_reader.crop_for_listing(page, (0, 0, page.width, page.height), padding=0)
        return ScrapedItem(
            external_key=key,
            url=SITE_BASE,
            title=f"Hunter's Lodge advertisement{f' — {issue}' if issue else ''}",
            price=None,
            description=(
                "A new flyer has been published, but no individual listings could be "
                "read from it. The full advertisement is attached."
            ),
            category="Flyer",
            generated_images=[(f"{key}.png", whole)],
            extra={"flyer_url": flyer_url, "issue": issue or ""},
        )
