"""Vendors that are not built yet, and what is standing between here and there.

The registry in ``__init__.py`` answers "what can this application scan?". This
answers the question the Sites page gets asked next, which is "is that all of
them?" -- and the honest answer has always been in ROADMAP.md rather than
anywhere the application could show it.

**Every entry is a measurement, not a wish.** Each of these was fetched before
it was written down, and the ``blocker`` says what the fetch showed. A vendor
that was measured and *refused* -- Impact Guns, USA Gun Shop, Edelweiss Arms,
The Mosin Crate, Century Arms, Gideon Tactical, Birmingham Pistol Wholesale, KY
Gun Co, Bud's Gun Shop, Victory Arms -- is not here: refusing one is a decision, and listing
it as "coming soon" would quietly reverse it. The roadmap keeps those with the
reasoning; this keeps only what is still queued.

Kept beside the scrapers rather than in the web layer because it is the same
kind of fact as a scraper's ``slug`` and ``base_url``, and because the test that
stops these two lists from contradicting each other -- a planned vendor that has
since shipped is a stale promise on the page -- belongs next to both.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannedSite:
    """One vendor the roadmap intends to read, and what it is waiting on."""

    #: The slug it will get when it ships, so a stale entry is easy to spot.
    slug: str
    name: str
    base_url: str
    #: The storefront platform, or what was found instead of one.
    platform: str
    #: What has to happen first, in one line. This is the interesting field:
    #: "not written yet" and "cannot get in" are different kinds of waiting and
    #: an operator reading the page deserves to know which this is.
    blocker: str


#: Ordered the way the roadmap orders them: buildable first, nearest to
#: buildable at the top, and the ones blocked at the door last.
PLANNED: tuple[PlannedSite, ...] = (
    # -- buildable, not written yet ----------------------------------------
    PlannedSite(
        slug="ww2-collectibles",
        name="WW2 Collectibles",
        base_url="https://ww2collectibles.com/",
        platform="AppSoft CMS, custom",
        blocker=(
            "Not written yet; needs its own small parser. Rifles and Pistols "
            "held 153 listings on 2026-09-27, 81 for sale and 72 marked SOLD, "
            "with id, name and price as data attributes on each card. "
            "Blank-firing replicas share the pistol shelf and must be left out."
        ),
    ),
    PlannedSite(
        slug="nickerson-military",
        name="Nickerson Military",
        base_url="https://www.nickersonmilitary.com/",
        platform="WordPress page, hand-written",
        blocker=(
            "Not written yet, and the weaker of the two: one hand-edited "
            "price list, 29 lines with a price each on 2026-09-27, and no "
            "photos, links or ids. Keys would come from titles, and a "
            "removed line is the only sign of a sale."
        ),
    ),
    # -- blocked at the door -----------------------------------------------
    PlannedSite(
        slug="wis-transfers",
        name="WIS Transfers",
        base_url="https://www.wistransfers.com/",
        platform="PHP shop behind an AWS WAF bot-control rule",
        blocker=(
            "The shop is fine; its firewall refuses us. AWS WAF answers our "
            "honest MilsurpMonitor user agent with a JavaScript challenge "
            "(x-amzn-waf-action: challenge, 202, empty) -- robots.txt "
            "included -- while a browser gets the page. Pretending to be a "
            "browser would be evading their bot control, so this waits on "
            "WIS allowing the MilsurpMonitor agent."
        ),
    ),
)
