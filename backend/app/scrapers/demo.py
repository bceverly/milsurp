"""A scraper that touches nothing.

Registered only when ``MILSURP_ENABLE_DEMO_SITE`` is set, which the end-to-end
suite and the screenshot runner both do. It exists so that:

* the browser tests can exercise the whole scan pipeline — start, progress,
  outcome, price history, de-listing — without hitting a real vendor. Pointing
  a test suite at someone else's shop on every run is slow, flaky, and rude.
* a developer can verify a fresh install end to end with
  ``make scan site=demo-vendor`` before configuring anything real.

It returns a small, deterministic catalog, and varies it slightly between runs
so that re-scanning produces the price changes and de-listings the UI is meant
to surface.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..services import classify
from .base import ScrapeContext, ScrapedItem, SiteScraper

#: (key, title, base price, category)
CATALOG: tuple[tuple[str, str, float, str], ...] = (
    ("demo-01", "GERMAN K98 Mauser rifle, matching numbers", 1450.0, "Rifle"),
    ("demo-02", "RUSSIAN Mosin Nagant M91/30, Izhevsk 1943", 425.0, "Rifle"),
    ("demo-03", "BRITISH Lee-Enfield No.4 Mk I, 1943", 675.0, "Rifle"),
    ("demo-04", "GERMAN Luger P08, 1917 DWM", 3250.0, "Handgun"),
    ("demo-05", "SOVIET Makarov PM, East German", 550.0, "Handgun"),
    ("demo-06", "Bayonet, German S84/98 with scabbard", 145.0, "Accessory"),
)


class DemoScraper(SiteScraper):
    slug = "demo-vendor"
    name = "Demo Vendor"
    base_url = "https://demo.invalid/"
    description = (
        "A built-in test fixture that performs no network access. Enabled only "
        "when MILSURP_ENABLE_DEMO_SITE is set."
    )
    requires_browser = False
    default_interval_minutes = 60

    #: Bumped on each call so successive scans differ. Class-level rather than
    #: per-instance because the scan service builds a fresh scraper each run.
    run_count = 0

    def scrape(self, ctx: ScrapeContext) -> Iterable[ScrapedItem]:
        type(self).run_count += 1
        run = type(self).run_count
        ctx.log(f"Demo scraper: run {run}, no network access.")

        items: list[ScrapedItem] = []
        for index, (key, title, price, category) in enumerate(CATALOG):
            # Drop the last item on every third run so de-listing is exercised.
            if run % 3 == 0 and index == len(CATALOG) - 1:
                continue
            # Shave a little off one item's price each run, so price history
            # and the "reduced" badge have something to show.
            adjusted = price - (25.0 * (run - 1)) if index == 1 else price

            derived = classify.enrich(title, None, adjusted)
            items.append(
                ScrapedItem(
                    external_key=key,
                    url=f"{self.base_url}listing/{key}",
                    title=title,
                    price=round(adjusted, 2),
                    description=(
                        f"{title}. Fixture listing produced by the demo scraper; "
                        f"no vendor was contacted."
                    ),
                    category=category,
                    caliber=derived["caliber"],
                    country=derived["country"],
                    manufacturer=derived["manufacturer"],
                    condition=derived["condition"],
                )
            )
            ctx.check_stop()

        ctx.log(f"Demo scraper returning {len(items)} listing(s).")
        return items
