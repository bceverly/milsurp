"""One-click links to the stores' own search for what fits an owned gun.

Slice 1 of "Upgrades and accessories for the guns you own" (ROADMAP.md),
asked for on 2026-10-27. Nothing here is fetched or scraped: each link is a
store's own search page, for the gun and the kind of accessory its kind of gun
takes ("Glock 19 magazine" at GunMag Warehouse), which the reader follows
themselves. So a store whose bot controls refuse the scanner can still be
linked, and what the reader sees is the store's own stock and price, current.

**The search addresses** were read from each store's own pages on 2026-10-27:
the schema.org ``SearchAction`` Brownells, Primary Arms and Numrich publish,
and Magento's standard ``catalogsearch/result/?q=`` for GunMag Warehouse,
whose page names Magento. MidwayUSA refused this application's request, so its
address (``/s?searchTerm=``) is the form its site has used for years, not one
read that day; a reader will see quickly if it moves. KY Gun Co draws its
search in the browser and publishes no address to link, so it is not here.

**What to search for** comes from the gun's kind, in the armory: magazines for
a pistol or a rifle, speedloaders and moon clips for a revolver, chokes for a
shotgun. A gun the armory has no kind for gets the general shelves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

if TYPE_CHECKING:
    from ..models import CollectionItem

#: Each store's search, with ``{q}`` for the words searched.
STORES: dict[str, str] = {
    "GunMag Warehouse": "https://gunmagwarehouse.com/catalogsearch/result/?q={q}",
    "Brownells": "https://www.brownells.com/search/?search={q}",
    "MidwayUSA": "https://www.midwayusa.com/s?searchTerm={q}",
    "Primary Arms": "https://www.primaryarms.com/search?keywords={q}",
    "Numrich Gun Parts": "https://www.gunpartscorp.com/search.html?Search={q}",
}

MAGAZINE_STORES = ("GunMag Warehouse", "Brownells", "MidwayUSA", "Primary Arms")
GENERAL_STORES = ("Brownells", "MidwayUSA", "Primary Arms")
PARTS_STORES = ("Numrich Gun Parts", "Brownells")

#: What each kind of gun is shopped for: the shelf's name, the word searched,
#: and the stores worth asking.
_PISTOL = (
    ("Magazines", "magazine", MAGAZINE_STORES),
    ("Holsters", "holster", GENERAL_STORES),
    ("Grips and sights", "grips", ("Brownells", "MidwayUSA")),
    ("Parts", "parts", PARTS_STORES),
)
_REVOLVER = (
    ("Speedloaders and moon clips", "speedloader", ("Brownells", "MidwayUSA")),
    ("Holsters", "holster", GENERAL_STORES),
    ("Grips", "grips", ("Brownells", "MidwayUSA")),
    ("Parts", "parts", PARTS_STORES),
)
_RIFLE = (
    ("Magazines", "magazine", MAGAZINE_STORES),
    ("Slings", "sling", ("Brownells", "MidwayUSA")),
    ("Scope mounts", "scope mount", GENERAL_STORES),
    ("Parts", "parts", PARTS_STORES),
)
_SHOTGUN = (
    ("Chokes", "choke", ("Brownells", "MidwayUSA")),
    ("Slings", "sling", ("Brownells", "MidwayUSA")),
    ("Parts", "parts", PARTS_STORES),
)
#: A muzzleloader: no magazine to buy, and its parts are the useful shelf.
_MUZZLELOADER = (("Parts", "parts", PARTS_STORES),)
#: A gun the armory has no kind for.
_GENERAL = (
    ("Magazines", "magazine", MAGAZINE_STORES),
    ("Parts and accessories", "parts", ("Numrich Gun Parts", "Brownells", "MidwayUSA")),
)

SHELVES: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "pistol": _PISTOL,
    "revolver": _REVOLVER,
    "rifle": _RIFLE,
    "carbine": _RIFLE,
    "shotgun": _SHOTGUN,
    "flintlock_rifle": _MUZZLELOADER,
    "flintlock_carbine": _MUZZLELOADER,
    "flintlock_pistol": _MUZZLELOADER,
    "percussion_rifle": _MUZZLELOADER,
    "percussion_carbine": _MUZZLELOADER,
    "percussion_pistol": _MUZZLELOADER,
    "percussion_revolver": _MUZZLELOADER,
}


@dataclass(frozen=True)
class Link:
    store: str
    url: str


@dataclass(frozen=True)
class Shelf:
    """One kind of accessory, and where to search for it."""

    label: str
    query: str
    links: tuple[Link, ...]


def search_url(store: str, words: str) -> str:
    return STORES[store].format(q=quote_plus(words))


def gun_words(row: CollectionItem) -> str:
    """What to call the gun in a search: the armory's name for its model,
    which carries the maker ("Smith & Wesson Model 10"), or what its owner
    called it."""
    model = getattr(row, "firearm_model", None)
    return (model.name if model is not None else row.title or "").strip()


def shelves(row: CollectionItem) -> list[Shelf]:
    """The search links for one owned gun, shelf by shelf."""
    gun = gun_words(row)
    if not gun:
        return []
    model = getattr(row, "firearm_model", None)
    kind = getattr(getattr(model, "kind", None), "value", getattr(model, "kind", None))
    found = []
    for label, word, stores in SHELVES.get(str(kind or ""), _GENERAL):
        query = f"{gun} {word}"
        found.append(
            Shelf(
                label=label,
                query=query,
                links=tuple(Link(store, search_url(store, query)) for store in stores),
            )
        )
    return found
