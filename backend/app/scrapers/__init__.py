"""Scraper registry.

Adding a vendor is a two-line change: write the scraper class in this package,
then list it in :data:`SCRAPER_CLASSES`. Startup reconciles the registry against
the ``sites`` table -- new scrapers get a row, and a row whose scraper has been
removed is flagged unavailable rather than deleted, so its history survives.
"""

from __future__ import annotations

import os

from .base import (
    ScrapeCanceled,
    ScrapeContext,
    ScrapedItem,
    ScrapeError,
    SiteScraper,
)
from .demo import DemoScraper
from .empire_arms import EmpireArmsScraper
from .royal_tiger import RoyalTigerScraper


def _demo_site_enabled() -> bool:
    """Whether to register the network-free demo scraper.

    Off by default: it is a test fixture, and a real deployment should never
    show a fake vendor in its site list. The end-to-end suite and the
    screenshot runner set this so they can exercise the scan pipeline without
    contacting anyone.
    """
    return os.environ.get("MILSURP_ENABLE_DEMO_SITE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


#: Every scraper the application knows about. Order sets the initial UI order.
SCRAPER_CLASSES: tuple[type[SiteScraper], ...] = (
    RoyalTigerScraper,
    EmpireArmsScraper,
    *((DemoScraper,) if _demo_site_enabled() else ()),
)

_REGISTRY: dict[str, type[SiteScraper]] = {cls.slug: cls for cls in SCRAPER_CLASSES}

if len(_REGISTRY) != len(SCRAPER_CLASSES):  # pragma: no cover - guards a typo
    raise RuntimeError("two scrapers share the same slug")


def available_slugs() -> list[str]:
    return list(_REGISTRY)


def get_scraper_class(slug: str) -> type[SiteScraper] | None:
    return _REGISTRY.get(slug)


def get_scraper(slug: str) -> SiteScraper | None:
    cls = _REGISTRY.get(slug)
    return cls() if cls else None


def iter_scrapers() -> list[SiteScraper]:
    return [cls() for cls in SCRAPER_CLASSES]


__all__ = [
    "SCRAPER_CLASSES",
    "ScrapeCanceled",
    "ScrapeContext",
    "ScrapeError",
    "ScrapedItem",
    "SiteScraper",
    "available_slugs",
    "get_scraper",
    "get_scraper_class",
    "iter_scrapers",
]
