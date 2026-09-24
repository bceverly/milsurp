"""Where a stored field's value came from.

Everything this application knows beyond a vendor's own words is derived, and
the pipeline is built to be recomputed: that is what lets one rule fix reach
eleven thousand listings. It has always had one thing missing, and the gap has
a measured cost.

**Nothing recorded whether a stored value was the vendor's or the rules'.** So
``reclassify --recompute`` could not tell a correction from a demolition. Run
over the catalog scoped to nothing but the caliber it changed **3,187 of 11,038
listings** -- 2,251 of them to nothing at all -- because it discards the stored
value by design and re-derives from the title. That is right for a caliber the
rules guessed and wrong for one the dealer printed: a Carl Gustafs 1896 stated
as 6.5x55mm Swedish came back 8mm Mauser, and a Carcano carbine whose own title
reads "6.5X52" came back 7.35x51mm.

So each derived field now carries a source beside it, written at the moment the
value is, by whichever of the three steps put it there:

``vendor``
    The shop published it -- a structured field on their own catalog page.
    Never re-derived. Sixty years of surplus is full of rebarreled and
    rechambered guns and the vendor has the thing in their hand.
``derived``
    :mod:`app.services.classify` read it out of the title or the description.
``catalog``
    The armory filled it from the model the listing names.
``override``
    A person corrected it, knowing what the rules said. The strongest of the
    four and the only one a human wrote.

And a fourth state that is not a value: **NULL means nobody knows**, which is
every row stored before this was written. It is treated exactly like
``vendor`` -- protected -- because the whole failure this fixes was a guess
about provenance, and guessing again in the other direction is the same
mistake. Rows correct themselves as each site's next scan rewrites them.

**A spelling is not a source.** The armory normalizes ".32 ACP" and "7.65mm
Browning" into one answer, and the maker table spells "S&W" as "Smith &
Wesson"; neither is a new opinion about the gun, so both go through
:func:`respell`, which changes the value and leaves the source alone. Getting
this wrong would quietly relabel most of the catalog as ``catalog``-sourced and
hand the recompute permission over the vendor's own fields -- which is the
original bug wearing a hat.
"""

from __future__ import annotations

from ..models import Item

#: The shop published it. Never re-derived.
VENDOR = "vendor"
#: The classifier read it out of the listing's text.
DERIVED = "derived"
#: The armory filled it from the model the listing names.
CATALOG = "catalog"
#: A person corrected it. See app/services/overrides.py.
OVERRIDE = "override"

SOURCES = (VENDOR, DERIVED, CATALOG, OVERRIDE)

#: The sources a recompute is allowed to overwrite. Deliberately a whitelist:
#: a value added later with no thought about provenance is protected by
#: default, which is the safe direction to be wrong in.
#:
#: ``override`` is excluded, and that closes a hole that predates this module:
#: ``reclassify`` never read the override table at all, so a rebuild quietly
#: undid a person's correction until the next scan put it back. A correction is
#: made *knowing* what the rules said, which makes the rules the last thing
#: entitled to argue with it.
RECOMPUTABLE_SOURCES = frozenset({DERIVED, CATALOG})

#: field -> the column holding its source. The four fields `reclassify` can
#: rebuild; price, title and URL are the vendor's own words throughout and
#: have no provenance question to answer.
SOURCE_COLUMNS: dict[str, str] = {
    "caliber": "caliber_source",
    "country": "country_source",
    "condition": "condition_source",
    "manufacturer": "manufacturer_source",
}


def source_of(item: Item, field: str) -> str | None:
    """The recorded source, or None when the row predates this."""
    return getattr(item, SOURCE_COLUMNS[field], None)


def fill(item: Item, field: str, value: str | None, source: str, *, adopt: bool = False) -> bool:
    """Set *field* only if it is empty, recording who set it.

    Returns whether anything was written. This is the shape every one of the
    three steps already had -- ``item.caliber = item.caliber or derived`` --
    made explicit so the source cannot drift away from the value it describes.

    ``adopt`` records the source of a value that is already there, of unknown
    origin, and identical to the one this step just produced. Without it no
    row written before migration 0031 ever gained a source -- this returns
    early on a filled field -- and a recompute, which refuses unknown origins,
    could never reach them. The caller passes it only for a vendor whose
    scraper states none of these facts itself, where "the rules produce exactly
    this" is the whole of how the value can have got there.
    """
    if not value:
        return False
    current = getattr(item, field)
    if current:
        if adopt and current == value and source_of(item, field) is None:
            setattr(item, SOURCE_COLUMNS[field], source)
        return False
    setattr(item, field, value)
    setattr(item, SOURCE_COLUMNS[field], source)
    return True


def respell(item: Item, field: str, value: str | None) -> bool:
    """Rewrite the value, keeping the source.

    For a normalization: the armory's caliber spelling and the maker table's
    canonical name are the same answer written once rather than twice, and
    neither is an opinion about the gun. A vendor who states "S&W" is not being
    argued with, they are being spelled -- so the field still says ``vendor``.
    """
    if not value or getattr(item, field) == value:
        return False
    setattr(item, field, value)
    return True


def claim(item: Item, field: str, value: str | None, source: str) -> bool:
    """Set *field* whatever it held, recording the new source.

    The one honest overwrite, and the only caller is the recompute itself --
    which has already asked :func:`may_recompute` for permission. Kept separate
    from :func:`fill` so that permission is never accidental.
    """
    if getattr(item, field) == value:
        # Still worth restating the source: a row whose value the rules would
        # have produced anyway is one the rules own, and saying so is what
        # lets the *next* fix reach it.
        setattr(item, SOURCE_COLUMNS[field], source)
        return False
    setattr(item, field, value)
    setattr(item, SOURCE_COLUMNS[field], source)
    return True


def may_recompute(item: Item, field: str) -> bool:
    """Whether a rebuild is allowed to overwrite this field.

    False for a value the vendor stated **and for a value of unknown origin**.
    The second is the important half: every row written before this existed
    has no source, and treating those as fair game would reproduce exactly the
    damage this module was written to prevent.
    """
    return source_of(item, field) in RECOMPUTABLE_SOURCES
