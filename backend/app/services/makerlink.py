"""The one-click way from a listing to what its maker says about the gun.

Slice 1 of "New-gun prices, and the makers' own pages" (ROADMAP.md): a
reader looking at a used carry gun was searching Google for the maker's page
by hand. Only for a model still in production -- a 1903 Springfield has no
page on anybody's current site -- and in order of how direct it is:

1. the model's own page, when somebody has recorded it (``maker_url``);
2. a search of the maker's own site for the model, when the maker's site is
   known (``Manufacturer.website``) -- the search the reader was typing;
3. otherwise nothing: a search of the whole web is no better than the one
   the reader would type, and a link that lands somewhere vague teaches them
   not to click it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote_plus, urlsplit

from sqlalchemy import select

from ..models import ArmoryStatus, Manufacturer

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import FirearmModel, Item


@dataclass(frozen=True)
class MakerLink:
    url: str
    #: "page" for the model's own page, "search" for a search of the maker's site.
    kind: str
    #: Whose site it is, for the link's wording.
    maker: str | None
    #: The host searched or linked, for the same.
    site: str | None


def _host(url: str) -> str | None:
    # A bare "rossiusa.com" too: the forms add the scheme, a file or a direct
    # edit may not have.
    host = urlsplit(url if "://" in url else f"https://{url}").hostname
    return host.removeprefix("www.") if host else None


def _maker_for(session: Session, item: Item, model: FirearmModel) -> Manufacturer | None:
    """The maker whose site to search: the model's own maker with a website --
    the one the listing names, if it has several -- or failing that, the
    maker the listing names, if the armory knows its site.

    The second half is for the models the queue approved from used-gun shops,
    which arrive with no maker linked: "KAHR CW9 PRE OWNED" made a "CW9" row
    that knows nothing of Kahr, while the listing itself says Kahr.
    """
    named = (item.manufacturer or "").strip().lower()
    with_site = [maker for maker in model.manufacturers if maker.website]
    for maker in with_site:
        if named and named in (spelling.lower() for spelling in maker.spellings):
            return maker
    if with_site:
        return with_site[0]
    if not named:
        return None
    for maker in session.execute(
        select(Manufacturer).where(
            Manufacturer.website.is_not(None),
            Manufacturer.enabled.is_(True),
            Manufacturer.status == ArmoryStatus.APPROVED,
        )
    ).scalars():
        if named in (spelling.lower() for spelling in maker.spellings):
            return maker
    return None


def for_item(session: Session, item: Item) -> MakerLink | None:
    """Where this listing's maker describes the gun, or None. See the module."""
    model = item.firearm_model
    if model is None or not model.modern_production:
        return None
    maker = _maker_for(session, item, model)
    if model.maker_url:
        return MakerLink(
            url=model.maker_url,
            kind="page",
            maker=maker.name if maker else None,
            site=_host(model.maker_url),
        )
    if maker is None or not maker.website:
        return None
    site = _host(maker.website)
    if site is None:
        return None
    query = f"site:{site} {model.name}"
    return MakerLink(
        url=f"https://www.google.com/search?q={quote_plus(query)}",
        kind="search",
        maker=maker.name,
        site=site,
    )
