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
PLANNED: tuple[PlannedSite, ...] = ()
