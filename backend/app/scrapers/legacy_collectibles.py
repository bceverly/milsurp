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
