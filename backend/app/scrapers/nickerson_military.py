"""Nickerson Military (nickersonmilitary.com).

An FFL in Warren, Pennsylvania whose military firearms are one hand-edited
WordPress page, "MILITARY FIREARMS FOR SALE": a line per gun, a price at the
end of each, grouped under bold era headings ("WORLD WAR II RIFLES", "WWII
PISTOLS"). Measured 2026-09-28: 30 priced lines, 29 of them firearms, and
"UPDATED 09/18/2026". Garands, M1 Carbines, M1917s, a Krag, a Reising, a No. 4
(T), a PU sniper.

**The weakest source here, and the reason is worth stating.** There are no
photographs, no links and no ids: each listing is a sentence and a price. So:

* **A listing's key is its own title**, slugged. The shop could not be asked
  for anything more stable, because it publishes nothing more stable. If they
  edit a line's wording, that reads as one gun gone and another listed, and
  the price history does not carry across the edit.
* **A line that disappears is the only sign of a sale**, and it is read the
  way a vanished listing is read everywhere: de-listed. The guard against
  de-listing a large share at once still applies, so a page rewritten
  wholesale is held for a look rather than emptied.
* **Every listing links to the page itself**, as at Empire Arms.
* Two identical lines would share a key, so a repeat gets ``-2``, ``-3``.

The heading a line sits under is its category. Lines with no price (the
"UPDATED" date, blank paragraphs) are not listings. **One kind of line is left
out:** an air rifle ("Daisy Model 853 ... Air Rifle U.S. Property Marked"),
which is a collectible trainer and not a firearm. The display-only Maxim stays;
the classifier decides what a non-firing gun is, as for every shop.

Their "Military Surplus" page is gear and their "Hunting & Target" page is
sporting guns, so neither is read. robots.txt disallows only /wp-admin/. The
site has no mailing list; its only other outlet is an eBay store.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from .base import ScrapeContext, ScrapedItem, ScrapeError, SiteScraper, normalize_whitespace
from .storefront import parse_price

SITE_BASE = "https://www.nickersonmilitary.com/"
PAGE = f"{SITE_BASE}military-firearms-for-sale/"

#: "Colt 1911 2nd Year of Production 1913 Mfg. $3,500": the price ends the line.
_LINE = re.compile(r"^(?P<title>.+?)\s*\$\s?(?P<price>\d[\d,]*(?:\.\d{2})?)\s*$")
_UPDATED = re.compile(r"\bupdated\s+(\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_NOT_A_FIREARM = re.compile(r"\bair\s+(?:rifle|gun|pistol)\b|\bBB\s+gun\b|\bpellet\b", re.I)

#: Heading words kept as written when the heading is title-cased.
_KEEP_CAPS = frozenset({"I", "II", "WWI", "WWII", "US", "U.S.", "WW1", "WW2"})
_SMALL = frozenset({"a", "an", "and", "of", "the", "or"})


def heading(text: str) -> str:
    """ "SPANISH-AMERICAN WAR / WORLD WAR I RIFLES" as "Spanish-American War /
    World War I Rifles", keeping WWII and the Roman numerals."""
    words = []
    for position, word in enumerate(text.split()):
        if word in _KEEP_CAPS or not word.isupper():
            words.append(word)
        elif position and word.lower() in _SMALL:
            words.append(word.lower())
        else:
            words.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(words)


def key_for(title: str) -> str:
    """A listing's key: its title, lowercased, punctuation to hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:200] or "untitled"


def _is_heading(paragraph: Tag) -> bool:
    """A paragraph that is all bold, and not a priced line."""
    bold = paragraph.find(["strong", "b"])
    text = normalize_whitespace(paragraph.get_text(" ", strip=True))
    return bool(
        text
        and bold is not None
        and normalize_whitespace(bold.get_text(" ", strip=True)) == text
        and not _LINE.match(text)
    )


def parse_page(html_text: str) -> tuple[list[tuple[str, float | None, str]], str | None]:
    """``([(title, price, heading), ...], "09/18/2026")`` from the page."""
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.select_one(".entry-content")
    if body is None:
        return [], None
    lines: list[tuple[str, float | None, str]] = []
    section = ""
    updated: str | None = None
    for paragraph in body.find_all("p"):
        text = normalize_whitespace(paragraph.get_text(" ", strip=True))
        if not text:
            continue
        if _is_heading(paragraph):
            section = heading(text)
            continue
        if (found := _UPDATED.search(text)) and not _LINE.match(text):
            updated = found.group(1)
            continue
        match = _LINE.match(text)
        if match is None:
            continue
        lines.append((match.group("title").strip(), parse_price(match.group("price")), section))
    return lines, updated


class NickersonMilitaryScraper(SiteScraper):
    slug = "nickerson-military"
    shipping_note = "No shipping or policy page found on the site"
    name = "Nickerson Military"
    base_url = SITE_BASE
    newsletter_url = None
    newsletter_note = (
        "No signup found on the site; its only other outlet is an eBay store. Checked 2026-09-28"
    )
    description = (
        "Warren, Pennsylvania dealer whose military firearms are one hand-kept "
        "price list: Garands, M1 Carbines, M1917s, Krags, snipers. No photos, "
        "and a line that disappears is de-listed."
    )
    requires_browser = False
    default_interval_minutes = 1440

    def scrape(self, ctx: ScrapeContext) -> Iterator[ScrapedItem]:
        ctx.log("Reading Military Firearms for Sale…")
        lines, updated = parse_page(ctx.get_text(PAGE))
        if not lines:
            raise ScrapeError("the military firearms page listed nothing with a price")
        if updated:
            ctx.log(f"The page says it was updated {updated}.")
        seen: dict[str, int] = {}
        left_out = 0
        for title, price, section in lines:
            if _NOT_A_FIREARM.search(title):
                left_out += 1
                continue
            key = key_for(title)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key = f"{key}-{seen[key]}"
            yield ScrapedItem(
                external_key=key,
                url=PAGE,
                title=title,
                price=price,
                category=section or "Military Firearms",
            )
        ctx.log(f"{len(lines) - left_out} listing(s) read; {left_out} air gun(s) left out.")
