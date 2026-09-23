"""Vendors that are not built yet, and what is standing between here and there.

The registry in ``__init__.py`` answers "what can this application scan?". This
answers the question the Sites page gets asked next, which is "is that all of
them?" -- and the honest answer has always been in ROADMAP.md rather than
anywhere the application could show it.

**Every entry is a measurement, not a wish.** Each of these was fetched before
it was written down, and the ``blocker`` says what the fetch showed. A vendor
that was measured and *refused* -- Impact Guns, USA Gun Shop, Edelweiss Arms,
The Mosin Crate, Century Arms -- is not here: refusing one is a decision, and
listing it as "coming soon" would quietly reverse it. The roadmap keeps those
with the reasoning; this keeps only what is still queued.

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


#: Ordered the way the roadmap orders them: what is nearest to buildable first,
#: what needs a way in after that, and what is blocked at the door last.
PLANNED: tuple[PlannedSite, ...] = (
    # -- nearest to buildable: a supported platform, serving its catalog ----
    PlannedSite(
        slug="madison-guns",
        name="Madison Guns",
        base_url="https://madisonguns.com/",
        platform="BigCommerce (Stencil)",
        blocker=(
            "Nothing but the writing. Their used-guns page serves 12 cards "
            "straight to a plain request and the existing BigCommerce reader "
            "finds every one of them."
        ),
    ),
    PlannedSite(
        slug="gideon-tactical",
        name="Gideon Tactical",
        base_url="https://gideontactical.com/",
        platform="BigCommerce (Stencil)",
        blocker=(
            "Nothing but the writing. Their used-firearms page answers with 12 "
            "cards the existing BigCommerce reader already parses, and robots "
            "disallows only the cart and account paths."
        ),
    ),
    PlannedSite(
        slug="dbg-firearms",
        name="DBG Firearms",
        base_url="https://www.dbgfirearms.com/",
        platform="Wix Stores",
        blocker=(
            "Nothing but the writing: Wix is already read for another vendor. "
            "Their robots.txt refuses PetalBot and allows everything else, so "
            "the Disallow near the top of it is not about us."
        ),
    ),
    # -- a supported platform, but the catalog is not in the page ----------
    PlannedSite(
        slug="botach",
        name="Botach",
        base_url="https://botach.com/",
        platform="BigCommerce, with an Algolia-rendered catalog",
        blocker=(
            "The grid is built in the browser. Their firearms page is 336 KB "
            "and holds zero BigCommerce cards -- Algolia InstantSearch fills "
            "it after load -- so this wants their search endpoint read "
            "directly rather than the markup, the way Sarco's is."
        ),
    ),
    PlannedSite(
        slug="kings-firearms",
        name="King's Firearms",
        base_url="https://www.kingsfirearmsonline.com/",
        platform="Client-rendered, backed by GunBroker",
        blocker=(
            "There is no catalog in the page to read: the trade-in listing "
            "answers with a 15 KB shell, a <noscript> and a GunBroker "
            "reference. Needs a way in that is not the HTML, and possibly a "
            "decision about reading a marketplace rather than a shop."
        ),
    ),
    # -- blocked at the door -----------------------------------------------
    PlannedSite(
        slug="clyde-armory",
        name="Clyde Armory",
        base_url="https://clydearmory.com/",
        platform="BigCommerce (Stencil)",
        blocker=(
            "Their certificate chain is broken. The server sends its own "
            "Sectigo DV certificate without the intermediate, so verification "
            "fails with 'unable to verify the first certificate' and every "
            "request dies at TLS. The page is a perfectly ordinary "
            "BigCommerce grid behind it. Turning verification off is not the "
            "answer; this waits for them to fix the chain."
        ),
    ),
    PlannedSite(
        slug="wis-transfers",
        name="WIS Transfers",
        base_url="https://www.wistransfers.com/",
        platform="Unknown -- nothing is served to look at",
        blocker=(
            "Answers 202 with an empty body, to the catalog and to the home "
            "page alike. That is a challenge rather than a shop, and until "
            "something comes back there is no platform to identify and "
            "nothing to parse."
        ),
    ),
)
