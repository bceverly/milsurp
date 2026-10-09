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
    # -- blocked at the door -----------------------------------------------
    PlannedSite(
        slug="dixie-gun-works",
        name="Dixie Gun Works",
        base_url="https://www.dixiegunworks.com/",
        platform="Behind Cloudflare; robots.txt asks for 29 seconds between requests",
        blocker=(
            "The best-known black powder supplier, asked for by name -- but "
            "Cloudflare answers this application with a challenge (403, "
            "cf-mitigated: challenge; checked 2026-10-08) on the home page "
            "itself. That is their bot control saying no, so this waits on "
            "Dixie allowing the scanner."
        ),
    ),
    PlannedSite(
        slug="lodgewood",
        name="Lodgewood Mfg",
        base_url="https://www.lodgewood.com/",
        platform="Shift4Shop (3dcart), behind Cloudflare",
        blocker=(
            "85 guns, mostly original percussion and flintlock arms, every one "
            "priced with its stock status -- and a plain command-line fetch "
            "gets the page, but Cloudflare challenges this application's own "
            "HTTP client (403, cf-mitigated: challenge; checked 2026-10-08), as "
            "it does at Family Firearms & Finishes. Waits on the shop allowing "
            "the scanner."
        ),
    ),
    PlannedSite(
        slug="shop-family-firearms",
        name="Family Firearms & Finishes",
        base_url="https://shopfamilyfirearms.com/",
        platform="Shift4Shop (3dcart), behind Cloudflare",
        blocker=(
            "76 surplus rifles and pistols on one page, every one priced, and a "
            "parser was written and run -- but Cloudflare answers this "
            "application's requests with a challenge (cf-mitigated: challenge, "
            "403; checked 2026-10-08) while letting a plain command-line fetch "
            "through. That is the shop's bot control telling our client apart, "
            "and getting past it would be evading it, so this waits on the "
            "shop allowing the scanner, as Liberty Tree does."
        ),
    ),
    PlannedSite(
        slug="liberty-tree-collectors",
        name="Liberty Tree Collectors",
        base_url="https://www.libertytreecollectors.com/",
        platform="Lightspeed (Ecwid) store inside WordPress, behind Cloudflare",
        blocker=(
            "About 67 C&R rifles, pistols and antiques, every one priced, and "
            "readable without JavaScript -- but Cloudflare answers this "
            "application's requests with 403 on every catalog page (checked "
            "2026-10-06) while a browser is let through. That is the shop's bot "
            "control saying no, and getting past it would be evading it, so "
            "this waits on Liberty Tree allowing the scanner, as WIS Transfers "
            "does."
        ),
    ),
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
