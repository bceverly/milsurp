"""Whether a listing is a new gun or a used one.

Asked for on 2026-10-20, with the carry shops (Locked & Loaded, Florida Guns,
G4G, Frisco and the rest), which sell distributors' new guns beside a shelf of
used ones: "distinguish between used and new in the database and add a
search for new versus used". Stored as ``Item.is_new``: True new, False used,
None where nothing says.

**Strongest first:**

1. **The scraper's word for the listing** (``ScrapedItem.is_new``): the shop
   filed it under "Used Firearms", or in a maker's new-gun section.
2. **What the shop sells** (``SiteScraper.sells``): "used" for the surplus,
   antique and trade-in dealers this application was built for, "new" for a
   shop of new guns only (Muzzle-Loaders.com's reproductions), "mixed" for one
   that sells both.
3. **On a mixed shop, the section's and the title's words**: "Used",
   "Pre-Owned", "Trade-In", "Surplus", "Demo" for used ("Certified Used", "Used
   Muzzleloading Rifles"); "New in Box", "NIB", "Brand New", "Factory New" for
   new.
   Never on a used dealer's listing: there, "new in box" describes the box,
   and the gun has still been sold before.
"""

from __future__ import annotations

import re
from typing import Any

USED = "used"
NEW = "new"
MIXED = "mixed"

#: The search's answers, and what each asks of the column.
CHOICES: dict[str, bool] = {NEW: True, USED: False}

_USED_WORDS = re.compile(
    r"\b(?:used|pre[\s-]*owned|preowned|trade[\s-]*ins?|police\s+trade|le\s+trade|surplus|"
    r"consignment|second[\s-]*hand|demo|demonstrator)\b",
    re.I,
)
_NEW_WORDS = re.compile(
    r"\b(?:new\s+in\s+(?:the\s+)?box|nib|brand[\s-]*new|factory[\s-]*new|new\s+old\s+stock)\b",
    re.I,
)


def decide(
    stated: bool | None, sells: str | None, title: str | None, category: str | None = None
) -> bool | None:
    """New (True), used (False), or not known (None)."""
    if stated is not None:
        return stated
    if sells == NEW:
        return True
    if sells == USED:
        return False
    if sells == MIXED:
        for text in (category or "", title or ""):
            if _USED_WORDS.search(text):
                return False
            if _NEW_WORDS.search(text):
                return True
    return None


def sells_for(slug: str) -> str | None:
    """What the registered scraper for *slug* sells, or None."""
    from ..scrapers import get_scraper_class

    return getattr(get_scraper_class(slug), "sells", None)


def backfill(session: Any) -> dict[str, int]:
    """File every stored listing new or used, by its shop and its words.
    Migration 0082; the scan does the same for each listing it reads."""
    from sqlalchemy import func, select, update

    from ..models import Item, Site

    for site_id, slug in session.execute(select(Site.id, Site.slug)).all():
        sells = sells_for(slug)
        if sells in (NEW, USED):
            session.execute(update(Item).where(Item.site_id == site_id).values(is_new=sells == NEW))
            continue
        rows = session.execute(
            select(Item.id, Item.title, Item.category).where(Item.site_id == site_id)
        ).all()
        for value in (True, False):
            ids = [
                i for i, title, category in rows if decide(None, sells, title, category) is value
            ]
            for start in range(0, len(ids), 1000):
                session.execute(
                    update(Item).where(Item.id.in_(ids[start : start + 1000])).values(is_new=value)
                )
    session.flush()

    def count(clause: Any) -> int:
        return int(
            session.execute(select(func.count()).select_from(Item).where(clause)).scalar_one()
        )

    return {
        "new": count(Item.is_new.is_(True)),
        "used": count(Item.is_new.is_(False)),
        "unknown": count(Item.is_new.is_(None)),
    }
