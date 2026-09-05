"""Empire Arms (empirearms.com).

Hand-authored FrontPage HTML with no product pages and no markup structure worth
selecting on. Every listing is laid out as a thumbnail image followed by loose
prose:

    <img src="02248-1.jpg">
    <P><strong>TITLE</strong> description ...
       <a href="02248.jpg">PHOTOS</a> ... $1,250  [SOLD]</P>

So the page is split on the thumbnail images -- whose filenames always end in
``-<n>.jpg`` -- and everything from one thumbnail to the next is treated as a
single listing. The thumbnail's base filename doubles as the stable item key,
which is the only identifier the site offers.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from ..services import classify
from .base import ScrapeContext, ScrapedItem, SiteScraper, normalize_whitespace

SITE_BASE = "https://www.empirearms.com/"

SOURCES = (
    {"category": "Rifle", "url": "https://www.empirearms.com/rifles.htm"},
    {"category": "Handgun", "url": "https://www.empirearms.com/pistols.htm"},
)

# A product thumbnail filename: 02248-1.jpg, S102719-1.jpg, 321681-2.jpg.
THUMB_RE = re.compile(r'src\s*=\s*"?([^\s">]+-\d+\.jpg)', re.IGNORECASE)
# Any .jpg link in a block: these are the larger "PHOTOS" images.
JPG_HREF_RE = re.compile(r'href\s*=\s*"?([^\s">]+\.jpg)', re.IGNORECASE)
PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*)")
SOLD_RE = re.compile(r"\bSOLD\b", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")

# A parenthetical is a caliber when it *starts* with an inch caliber (.303,
# .30-06), a metric "AxB" caliber (7.62x54R, 8x57) or a millimeter caliber
# (9mm). On this site the caliber always follows the serial number.
CALIBER_QUALIFIES = re.compile(
    r"^\s*(?:\.\d{2,3}(?:-\d+)?|\d{1,2}(?:\.\d+)?\s*x\s*\d+\s*R?|\d{1,2}(?:\.\d+)?\s*mm)",
    re.IGNORECASE,
)
PAREN_RE = re.compile(r"\(([^)]{1,28})\)")


def _clean_text(fragment: str) -> str:
    return normalize_whitespace(html_lib.unescape(TAG_RE.sub(" ", fragment)))


def _item_key_from_thumb(thumb_filename: str) -> str:
    """``images/02248-1.jpg`` -> ``02248``."""
    name = thumb_filename.rsplit("/", 1)[-1]
    name = re.sub(r"\.jpg$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"-\d+$", "", name)
    return name.strip().lower()


def _detect_caliber(description: str) -> str | None:
    for content in PAREN_RE.findall(description):
        if CALIBER_QUALIFIES.match(content):
            cal = content.split(",")[0].strip()
            cal = normalize_whitespace(cal)
            # Collapse "7.62 x 54 R mm" to "7.62x54R".
            match = re.match(r"^(\d{1,2}(?:\.\d+)?)\s*x\s*(\d+)\s*(R?)\s*mm?$", cal, re.IGNORECASE)
            if match:
                cal = f"{match.group(1)}x{match.group(2)}{match.group(3).upper()}"
            # 7.65mm Browning is the same cartridge as .32 ACP.
            if cal.lower() in ("7.65mm", "7.65 mm"):
                return ".32 ACP"
            return cal
    return None


def parse_page(html_text: str, category: str, source_url: str) -> list[ScrapedItem]:
    """Parse one inventory page into listings."""
    items: list[ScrapedItem] = []
    matches = list(THUMB_RE.finditer(html_text))

    for index, match in enumerate(matches):
        # Start just past this <img> tag's closing '>' so the image markup does
        # not leak into the title text.
        gt = html_text.find(">", match.end())
        start = gt + 1 if gt != -1 else match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html_text)
        block = html_text[start:end]

        thumb_rel = match.group(1)
        thumbnail_url = urljoin(SITE_BASE, thumb_rel)
        item_key = _item_key_from_thumb(thumb_rel)
        if not item_key:
            continue

        image_urls = [urljoin(SITE_BASE, href) for href in JPG_HREF_RE.findall(block)]
        if thumbnail_url not in image_urls:
            image_urls.insert(0, thumbnail_url)

        text = _clean_text(block)
        if not text:
            continue

        price_match = PRICE_RE.search(block)
        price = float(price_match.group(1).replace(",", "")) if price_match else None
        sold = bool(SOLD_RE.search(text))

        # Page furniture (headers, FFL notices) has neither a price nor a SOLD
        # marker; a real listing always has one or the other.
        if price is None and not sold:
            continue

        # Title runs up to the price or the first sentence break.
        title = text.split("$", 1)[0]
        title = re.split(r"(?<=[a-z])\.\s|\bbolt-action\b|\bsemi-?auto", title, maxsplit=1)[0]
        title = title.split(" # ", 1)[0]
        title = title.strip(" .,-")[:200] or text[:120]

        caliber = _detect_caliber(text)
        derived = classify.enrich(title, text, price, caliber=caliber)

        items.append(
            ScrapedItem(
                external_key=f"{category.lower()}:{item_key}",
                url=source_url,
                title=title,
                description=text,
                price=price,
                category=category,
                is_sold=sold,
                image_urls=image_urls,
                caliber=derived["caliber"],
                country=derived["country"],
                manufacturer=derived["manufacturer"],
                condition=derived["condition"],
            )
        )
    return items


class EmpireArmsScraper(SiteScraper):
    slug = "empire-arms"
    name = "Empire Arms"
    base_url = SITE_BASE
    description = "Collector-grade military surplus rifles and handguns (static HTML catalog)."
    requires_browser = False
    default_interval_minutes = 720

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        items: list[ScrapedItem] = []
        for source in SOURCES:
            ctx.check_stop()
            ctx.log(f"Fetching {source['category'].lower()} listings…")
            try:
                html_text = ctx.get_text(source["url"])
            except Exception as exc:
                # One failed page should not lose the other; the run is marked
                # PARTIAL rather than FAILED.
                ctx.warn(f"could not fetch {source['url']}: {exc}")
                continue
            parsed = parse_page(html_text, source["category"], source["url"])
            ctx.log(f"Parsed {len(parsed)} {source['category'].lower()} listings.")
            items.extend(parsed)
        if not items and ctx.warnings:
            from .base import ScrapeError

            raise ScrapeError("every Empire Arms page failed to fetch")
        return items
