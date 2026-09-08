"""Legacy Collectibles (legacy-collectibles.com).

BigCommerce, and the reason this scraper exists at all is a correction: it was
listed for months as a WooCommerce site on the strength of its URL shape, which
the roadmap warned was a guess. Its cookies say otherwise, and nothing in its
markup parses as WooCommerce.

Their theme is close to stock Stencil and carries ``data-entity-id`` on every
card, so listings keep their identity through a rename — see
:meth:`BigCommerceScraper.key_for` for why that matters.

The categories are the firearm ones. They also sell collectible gun *parts*
and a great deal of gear -- holsters, pouches, binoculars, uniforms -- which
the roadmap's rule leaves alone.

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
        "High-end WWI and WWII collector pieces. Their handgun and long-gun "
        "catalog is read; their gear, parts and modern retail sections are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Their catalog, which is very nearly all of it in scope.
    #:
    #: This list was three narrow sections for a long time and that was a
    #: mistake worth writing down. It read **127 of their 977 listings** --
    #: thirteen percent -- and what it skipped was not modern stock but a
    #: Commercial Mauser C96, a Swiss Bern 1906/29 Luger, a Kriegsmarine Mauser
    #: 1934 rig, a 1902 American Eagle Luger, Walther PP and P.38 rigs, an
    #: Izhevsk M91/30 and a Robbins & Lawrence Mississippi Rifle. The "Modern
    #: Handguns"/"Modern Long Guns" sections this scraper still declines are
    #: different and much narrower sections than these two.
    #:
    #: Measured: ``/hand-guns`` and ``/rifles`` are 976 unique listings, 860 of
    #: them new, classifying 406 handguns / 444 rifles / 10 other. Not one
    #: title in either begins "SOLD" -- this shop moves a sold listing into
    #: ``/recently-sold-items``, so leaving these sections really does mean
    #: gone.
    #:
    #: The type-named sections come first, because the vendor's section name
    #: outranks the classifier's reading of a title and "Hand Guns" says what
    #: "US Military" does not. The four narrow ones follow, and each is here
    #: only for what the first two do not carry: 4 antique handguns, 6 antique
    #: long guns, 16 US-military rifles (a Springfield 1873 with its socket
    #: bayonet, a Krag Jorgensen carbine, two National Match 1903s) and 4
    #: Walther PPKs (an RZM rig, an SS-contract gun).
    #:
    #: **Two of their sections are deliberately absent.** ``/discounted-items``
    #: is 57 listings this cannot reach otherwise and 55 of them are gear --
    #: Luger holsters, a K98 bayonet, binoculars, a Luftwaffe overcoat, a book
    #: -- which the standing rule refuses. And ``/new-firearms`` is a rolling
    #: new-arrivals feed whose only unique listing was one already sold: with
    #: the catalog itself read there is nothing left for it to add, and reading
    #: it was actively harmful, because a listing that ages off a feed looks
    #: exactly like a listing that has been withdrawn. It de-listed 142
    #: listings in a day, of which a sample of 24 found only 5 genuinely sold.
    sources = (
        {"category": "Hand Guns", "url": f"{SITE_BASE}hand-guns/"},
        {"category": "Long Guns", "url": f"{SITE_BASE}rifles/"},
        {"category": "Antique Handguns", "url": f"{SITE_BASE}antique-handguns/"},
        {"category": "Antique Long Guns", "url": f"{SITE_BASE}antique-long-guns/"},
        {"category": "US Military", "url": f"{SITE_BASE}us-military/"},
        {"category": "Walther PPK", "url": f"{SITE_BASE}walther-ppk/"},
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
