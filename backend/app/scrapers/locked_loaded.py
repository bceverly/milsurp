"""Locked & Loaded (www.lockedloaded.com).

A gun shop asked for on 2026-10-20 for concealed carry pistols and revolvers:
in-stock handguns in the carry calibers (:func:`carry.is_carry_caliber`), the
shop's own shelf and its distributors' alike.

**Read from the shop's price feed, since 2026-11-18.** The shop left Coreware
for a storefront of its own in November 2026 -- the Meilisearch catalog the
old scraper read (:mod:`app.scrapers.coreware_search`) was gone, and the site
moved to ``www.``. Its category pages are plain HTML, 48 products a page, but
robots.txt forbids ``?page=`` and ``&page=`` to everyone but Googlebot and
Bingbot, so only the first page of each category may be read. What it does
leave open is the feed it publishes for gun.deals, ``/gun-deals-feed.php``
(disallowed for Googlebot only, "for the marketplaces, not the index"): one
XML document of every in-stock product, about 69,000 offers and 42 MB,
of which about 13,700 are firearms, each with its title, link, price, UPC,
brand, one photograph, and a ``<firearm>`` block naming its type and caliber.

One request a scan, then, in place of the hundred-odd the HTML would take --
and it is the document the shop has written for exactly this.

* **Handguns only**: ``<type>`` ``handgun`` or ``revolver``, as before; the
  rifles, shotguns, parts, ammunition and reloading gear are left.
* **A price the shop hides is still its price.** About one firearm in five
  carries ``hide="MAP"``, ``"Email for price"`` or ``"Add to Cart for best
  price"`` on ``<price>``: the shop does not print it on the grid, but sends
  it to gun.deals for listing, so it is kept, as the Magento shops' offer
  price is.
* **New keys.** The feed carries no product id -- the old ``cw-<id>`` keys
  were Coreware's, and the new site renumbered everything; its redirects from
  old links land on near neighbors, not the same gun (an old "Shadow 2 Target"
  goes to a "Shadow 2"), so they cannot carry a listing over. The key is the
  product's own path on the new site. The listings stored under the old keys
  are retired by one scan with de-listing accepted; see ROADMAP.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from urllib.parse import urlsplit

from lxml import etree

from ..services import carry
from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace

SITE_BASE = "https://www.lockedloaded.com/"
#: The price feed the shop publishes for gun.deals.
FEED = f"{SITE_BASE}gun-deals-feed.php"
#: The feed's firearm types that are handguns.
HANDGUN_TYPES = frozenset({"handgun", "revolver", "pistol"})
#: Seconds to wait between bytes of the feed: it is 42 MB, built on request.
FEED_TIMEOUT = 120


def _text(node: etree._Element, path: str) -> str:
    return normalize_whitespace(node.findtext(path) or "")


def _price(raw: str) -> float | None:
    try:
        value = float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def offers(document: bytes) -> list[etree._Element]:
    """Every ``<offer>`` in the feed.

    Parsed with entity resolution and network access off: this is somebody
    else's XML, and nothing in a price feed needs either.
    """
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True
    )
    try:
        root = etree.fromstring(document, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ScrapeError(f"{FEED} is not readable XML: {exc}") from exc
    if root is None or root.tag != "offers":
        raise ScrapeError(f"{FEED} is not the offers feed it was")
    return list(root.iter("offer"))


def item_from_offer(offer: etree._Element) -> ScrapedItem | None:
    """One handgun in a carry caliber, or None for anything else."""
    firearm = offer.find("firearm")
    if firearm is None:
        return None
    kind = _text(firearm, "type").lower()
    caliber = _text(firearm, "caliber")
    if kind not in HANDGUN_TYPES or not carry.is_carry_caliber(caliber):
        return None
    if _text(offer, "availability").lower() != "in stock":
        return None

    title = _text(offer, "title")
    link = urlsplit(_text(offer, "url"))
    path = link.path.strip("/")
    if not title or not path or link.netloc.removeprefix("www.") != "lockedloaded.com":
        return None
    image = _text(offer, "image")
    return ScrapedItem(
        external_key=f"ll-{path}",
        # The tracking parameters the feed adds for gun.deals are left off.
        url=f"{SITE_BASE}{path}",
        title=title,
        price=_price(_text(offer, "price")),
        category="Handguns",
        caliber=caliber,
        manufacturer=_text(offer, "brand") or None,
        stated_kind=kind,
        image_urls=[image] if image else [],
        extra={
            key: value
            for key, value in {
                "upc": _text(offer, "upc"),
                "mpn": _text(offer, "mpn"),
                "model": _text(firearm, "model"),
                "action": _text(firearm, "action"),
                "shipping": _text(offer, "shippingInfo"),
            }.items()
            if value
        },
    )


class LockedLoadedScraper(SiteScraper):
    slug = "locked-loaded"
    name = "Locked & Loaded"
    base_url = SITE_BASE
    description = "Gun shop with a distributor's catalog: carry pistols and revolvers, new."
    sells = "mixed"
    #: The shop's own caliber and maker, from its feed.
    states_facts = True
    requires_browser = False
    default_interval_minutes = 1440
    #: The whole catalog arrives before the first listing: one 42 MB document.
    canary_budget = 240.0
    newsletter_url = SITE_BASE
    newsletter_note = '"Join Our Mailing List" form in the footer of every page'
    shipping_note = (
        "Shipping is per listing in the shop's price feed, $24.99 on most handguns "
        "(checked 2026-11-18)"
    )
    shipping_source = f"{SITE_BASE}shipping.php"

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        return self._stream(ctx)

    def _stream(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        # The feed declares UTF-8, so it is read as that rather than guessed
        # at, which over 42 MB costs minutes for nothing.
        text = ctx.get_text(FEED, encoding="utf-8", timeout=FEED_TIMEOUT)
        found = offers(text.encode("utf-8"))
        ctx.log(f"Price feed: {len(found)} offer(s).")
        seen: set[str] = set()
        for offer in found:
            ctx.check_stop()
            item = item_from_offer(offer)
            if item is not None and item.external_key not in seen:
                seen.add(item.external_key)
                yield item
        if not seen:
            raise ScrapeError("The price feed listed no in-stock handguns in a carry caliber.")
        ctx.log(f"{len(seen)} in-stock handgun(s) in a carry caliber.")
