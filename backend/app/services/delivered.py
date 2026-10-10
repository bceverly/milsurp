"""What a gun costs delivered to your dealer, not what it costs on the shelf.

A $50-cheaper rifle with $65 shipping is not the better deal, and every price
this application shows is a shelf price. So a firearm listing also carries
three numbers added up: its price, the shop's charge to ship one gun to a
dealer, and the reader's own dealer's transfer fee.

**Only what somebody stated.** The shipping charge is the shop's own, read off
its policy page and declared on its scraper (``shipping_long_gun``,
``shipping_handgun``, with the page it came from) -- or an administrator's
override on the site when a shop changes it. Where the shop says "calculated
at checkout" there is no figure, and the total says it is incomplete rather
than quietly treating shipping as free. The transfer fee is the reader's, set
once on their settings; unset, it is left out and said to be.

**Firearms only.** A gun ships to a dealer, at the gun rate; a bayonet or a
magazine ships to the door at whatever the cart says, and adding a transfer
fee to a sling would be nonsense.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item, Site, User
from ..scrapers import get_scraper_class


@dataclass(frozen=True)
class Shipping:
    """One shop's firearm shipping, as it applies."""

    long_gun: float | None = None
    handgun: float | None = None
    note: str | None = None
    #: Where the figures were read, when they came from the scraper.
    source: str | None = None
    #: Whether an administrator set them rather than the scraper declaring them.
    overridden: bool = False


def shipping_for_site(site: Site) -> Shipping:
    """The site's override where it has one, the scraper's declaration otherwise.

    Per figure: an administrator correcting the handgun rate has not said
    anything about the long-gun one.
    """
    scraper = get_scraper_class(site.slug)
    declared_long = getattr(scraper, "shipping_long_gun", None)
    declared_hand = getattr(scraper, "shipping_handgun", None)
    overridden = site.shipping_long_gun is not None or site.shipping_handgun is not None
    return Shipping(
        long_gun=site.shipping_long_gun if site.shipping_long_gun is not None else declared_long,
        handgun=site.shipping_handgun if site.shipping_handgun is not None else declared_hand,
        note=site.shipping_note or getattr(scraper, "shipping_note", "") or None,
        source=getattr(scraper, "shipping_source", None),
        overridden=overridden,
    )


def is_firearm(item: Item) -> bool:
    return bool((item.is_rifle or item.is_pistol) and not item.is_parts_kit)


@dataclass(frozen=True)
class Delivered:
    """A firearm's shelf price, shipping and transfer fee, and their sum."""

    price: float
    shipping: float | None
    transfer_fee: float | None
    total: float
    #: Both of the other two are known. When False the total is a floor, and
    #: the page says which part is missing.
    complete: bool
    #: The shop's policy in a line, for when the figure alone does not say it
    #: -- above all when there is no figure: "calculated at checkout".
    shipping_note: str | None = None


@dataclass
class Costs:
    """Everything needed to price a page of listings, read once per request."""

    by_site: dict[int, Shipping] = field(default_factory=dict)
    transfer_fee: float | None = None
    #: Whose fee that is: the reader's cheapest dealer, by name.
    transfer_dealer: str | None = None

    @classmethod
    def load(cls, session: Session, user: User | None) -> Costs:
        sites = session.execute(select(Site)).scalars().all()
        dealer = user.cheapest_dealer if user is not None else None
        return cls(
            by_site={site.id: shipping_for_site(site) for site in sites},
            transfer_fee=dealer.transfer_fee if dealer is not None else None,
            transfer_dealer=dealer.name if dealer is not None else None,
        )

    def shipping(self, item: Item) -> float | None:
        """This listing's shipping, at the handgun or long-gun rate."""
        if not is_firearm(item):
            return None
        rates = self.by_site.get(item.site_id)
        if rates is None:
            return None
        return rates.handgun if item.is_pistol else rates.long_gun

    def delivered(self, item: Item) -> Delivered | None:
        """What this listing costs at the reader's dealer, or None.

        None for anything that is not a firearm, and for a listing with no
        price -- "call for price" plus $35 is not a number.
        """
        if not is_firearm(item) or item.current_price is None:
            return None
        shipping = self.shipping(item)
        fee = self.transfer_fee
        total = float(item.current_price) + (shipping or 0.0) + (fee or 0.0)
        rates = self.by_site.get(item.site_id)
        return Delivered(
            price=float(item.current_price),
            shipping=shipping,
            transfer_fee=fee,
            total=round(total, 2),
            complete=shipping is not None and fee is not None,
            shipping_note=rates.note if rates else None,
        )
