"""Legacy Collectibles (legacy-collectibles.com).

BigCommerce, and the reason this scraper exists at all is a correction: it was
listed for months as a WooCommerce site on the strength of its URL shape, which
the roadmap warned was a guess. Its cookies say otherwise, and nothing in its
markup parses as WooCommerce.

Their theme is close to stock Stencil and carries ``data-entity-id`` on every
card, so listings keep their identity through a rename — see
:meth:`BigCommerceScraper.key_for` for why that matters.

The categories are the firearm ones. They also sell collectible gun *parts*,
which the roadmap's rule leaves alone.

**They publish no prose description, on any of their 258 listings**, and for a
while that meant 258 listings arriving with nothing in the description at all.
What they publish instead is a specification table -- BigCommerce's stock
custom fields -- and it is better than prose would be, because it is the vendor
*stating* the things this application otherwise guesses at from a title:

    Year: 1911-15   Maker: Mauser   Type: C96
    Caliber: 7.63mm Mauser   Bore: 9/10   Condition: ~94-95%

Every one of forty sampled pages carried Maker, Type, Caliber, Bore and
Condition, and thirty-five also carried Year. Measured against what was stored
for those forty: **17 gained a caliber, 13 gained a maker, all 40 gained a bore
grade, and 13 calibers and 13 makers were corrected** -- among them a Sig P320
and a Krieghoff Luger whose manufacturer had been read as "Luger", a Beretta
Mod 96 whose ".40 S&W" had made it a Smith & Wesson, and a Spanish Model 1893
filed as 8mm Mauser when it is 7x57. Nothing was reclassified as a different
kind of firearm; nothing lost a value it had.

The cost is spellings. They write "S&W", "6.5 Creedmore", "5.56x45" and
"9mm Luger" where this catalog has settled on other forms, so their listings
propose those to the armory as new calibers and makers to approve or merge.
That is the armory's job and there is no way to take a vendor's stated value
without it.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://legacy-collectibles.com/"


class LegacyCollectiblesScraper(BigCommerceScraper):
    slug = "legacy-collectibles"
    name = "Legacy Collectibles"
    base_url = SITE_BASE
    description = (
        "High-end WWI and WWII collector pieces. Their antique and new-arrival "
        "sections are read; their modern retail and parts sections are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Their three collector sections, and not their two modern ones.
    #:
    #: "Modern Handguns" and "Modern Long Guns" are what those names say: Glock
    #: 17s, Sig P365s, Kimber 2011s, FN SCARs. Forty-three of them landed on the
    #: first run and not one was surplus. This is the same call already made
    #: about Arms Unlimited, and for the same reason — a catalog that mixes
    #: current retail stock into the surplus is worse at the job than one that
    #: does not.
    #:
    #: "New Firearms" stays despite carrying some of the same, because it is
    #: their new-arrivals feed rather than a category: a Springfield 1903, a
    #: Portuguese-contract Mauser Luger and a Finnish-marked Tula M1891 all
    #: appear there first, and nowhere else.
    sources = (
        {"category": "New Firearms", "url": f"{SITE_BASE}new-firearms/"},
        {"category": "Antique Handguns", "url": f"{SITE_BASE}antique-handguns/"},
        {"category": "Antique Long Guns", "url": f"{SITE_BASE}antique-long-guns/"},
    )

    #: Their spec table, mapped onto the columns it answers.
    #:
    #: A vendor-stated value outranks a derived one throughout this
    #: application, and these are stated. That matters most for the maker: fed
    #: the table as prose instead, the classifier read "Magnum Research Desert
    #: Eagle, Caliber: 9mm Luger" and reported the manufacturer as **Luger**.
    #: Naming the field is what makes the difference between using their data
    #: and guessing at it.
    #:
    #: "Type" is deliberately not mapped. It is the model -- C96, P.08, 1917 --
    #: and this application has no model column on a listing; the armory works
    #: that out for itself, and it does so from the description below.
    custom_field_map = (
        ("caliber", "caliber"),
        ("maker", "manufacturer"),
        ("bore", "condition"),
    )

    def description_from(self, fields: dict[str, str]) -> str | None:
        """Their table, restated as the description they do not write.

        **This is for the reader, not for the classifier.** Measured on the
        same forty: with it and without it the armory matches a model on the
        same 14, nothing is classified differently, and exactly one listing
        gains a country. The fields above do the work.

        What it is worth is Year and Type -- 1911-15, C96 -- which have no
        column to go in and which a detail page would otherwise not show at
        all, on 258 listings that show nothing today. Their own words in their
        own order, so nothing here is invented.

        ``Bore`` is left out: it is on the row already, as the condition, and
        repeating it in the prose only gives the bore grader something to
        re-derive.
        """
        said = [
            f"{label.title()}: {fields[label]}"
            for label in ("year", "maker", "type", "caliber", "condition")
            if fields.get(label)
        ]
        return ". ".join(said) + "." if said else None
