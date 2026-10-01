"""What is for sale that fits the guns somebody owns.

The scrapers read every shop's whole catalog, and about a fifth of it is not
guns: ammunition, stripper clips, bayonets, slings, parts. Until the collection
existed none of that had anybody in particular to be for. Now a reader has
told the application what they own, and "6.5x52 Carcano, two boxes" is news to
the owner of a Moschetto and to nobody else.

**Two kinds of fit, matched two ways.**

* *Ammunition and clips, by caliber.* A listing whose title says it is
  cartridges, clips, chargers or a bandolier, in a caliber one of the guns
  chambers -- the row's own caliber, or any the armory says its model
  chambers.
* *Accessories and parts, by model.* Anything else that is not a gun and
  names one of the owned models, matched with the armory's own spellings for
  it and then checked against the full matcher, so the precedence the armory
  keeps for listings applies here too: a Mosin M91/30 bayonet is not offered
  to the owner of a Carcano M91 because "M91" is in both.

Only what is for sale. Measured on production 2026-10-01: 1,842 active
listings that are not guns, 36 of them ammunition-like -- six of those in
6.5x52mm Carcano.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import CollectionItem, FirearmModel, Item, User
from . import armory, classify

#: A title that says it is ammunition or what holds it.
AMMO = re.compile(
    r"\b(?:ammo|ammunition|rounds?|rds|cartridges?|spam\s*cans?|bandoliers?|"
    r"stripper\s+clips?|clips?|chargers?|en[\s-]?bloc)\b",
    re.IGNORECASE,
)

#: "AK 30 round magazine" says "round" and is a magazine: a title naming one
#: is an accessory, matched by model, never ammunition.
MAGAZINE = re.compile(r"\b(?:mag|mags|magazines?)\b", re.IGNORECASE)

#: The most of each kind shown per gun. The page is a list to look down, and a
#: model with forty bayonets for sale is summarized by its count.
PER_GUN = 12


@dataclass
class Fits:
    """What fits one owned gun."""

    row: CollectionItem
    calibers: list[str]
    ammo: list[Item] = field(default_factory=list)
    accessories: list[Item] = field(default_factory=list)
    #: How many matched before the lists were cut to PER_GUN.
    ammo_total: int = 0
    accessories_total: int = 0

    @property
    def any(self) -> bool:
        return bool(self.ammo or self.accessories)


def _calibers(session: Session, row: CollectionItem) -> list[str]:
    """Every caliber this gun could want ammunition in, as the catalog spells it."""
    found: list[str] = []
    if row.caliber:
        # Read the way a listing's caliber is read, before the normalizer. An
        # owner types "6.5mm Carcano", and the normalizer finds "6.5mm" in it
        # -- a caliber of its own -- where the listing reader knows it is
        # 6.5x52mm Carcano, which is what the ammunition is filed under.
        found.append(
            classify.extract_caliber(row.caliber, None)
            or armory.canonical_caliber(session, row.caliber)
            or row.caliber
        )
    if row.firearm_model is not None:
        found.extend(caliber.name for caliber in row.firearm_model.calibers)
    return list(dict.fromkeys(found))


def _not_a_gun():
    return (
        Item.is_active.is_(True),
        Item.is_sold.is_(False),
        Item.is_rifle.is_(False),
        Item.is_pistol.is_(False),
    )


def for_user(session: Session, user: User, *, since: datetime | None = None) -> list[Fits]:
    """What fits each of this reader's guns, gun by gun.

    ``since`` narrows it to listings first seen after then, for the digest:
    the page shows everything, the email what is new.
    """
    rows = list(
        session.execute(
            select(CollectionItem)
            .options(selectinload(CollectionItem.firearm_model).selectinload(FirearmModel.calibers))
            .where(CollectionItem.user_id == user.id)
            .order_by(CollectionItem.id)
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    conditions = list(_not_a_gun())
    if since is not None:
        conditions.append(Item.first_seen_at >= since)
    candidates = list(
        session.execute(
            select(Item).where(*conditions).order_by(Item.first_seen_at.desc(), Item.id.desc())
        )
        .scalars()
        .all()
    )

    registry = armory.model_registry(session)
    patterns = {rule.found.model_id: rule.pattern for rule in registry.rules}

    found: list[Fits] = []
    for row in rows:
        fits = Fits(row=row, calibers=_calibers(session, row))
        wanted = {name.lower() for name in fits.calibers}
        pattern = patterns.get(row.firearm_model_id) if row.firearm_model_id else None
        for item in candidates:
            title = item.title or ""
            if AMMO.search(title) and not MAGAZINE.search(title):
                if (item.caliber or "").lower() in wanted:
                    fits.ammo.append(item)
                continue
            # The armory's precedence decides, as it does for a listing: this
            # model's spelling in the title is not enough if another model
            # claims the title first.
            if (
                pattern is not None
                and pattern.search(title)
                and registry.match(title).model_id == row.firearm_model_id
            ):
                fits.accessories.append(item)
        fits.ammo_total, fits.accessories_total = len(fits.ammo), len(fits.accessories)
        fits.ammo = fits.ammo[:PER_GUN]
        fits.accessories = fits.accessories[:PER_GUN]
        found.append(fits)
    return found
