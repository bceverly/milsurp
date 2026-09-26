"""Clyde Armory (clydearmory.com).

A Georgia dealer with an "Agency Trade-In" shelf: department trade-in Glocks,
a SIG P320, HK VP9 and HK45, a Mini-14, Benelli and Mossberg shotguns, an
LRP-07, a USAS-12 and Colt SBRs, beside trade-in optics, lights and complete
upper and lower receivers. The shelf is read whole and the classifier sorts the
guns from the gear, as it does for Officer Store's; the section name marks the
guns as police surplus.

**Their server sends an incomplete certificate chain**, which kept this shop
off the list for a while. It sends its own Sectigo DV certificate and not the
intermediate that links it to a trusted root. A browser downloads the missing
intermediate by itself and shows a padlock; Python does not, and fails with
"unable to verify the first certificate". The fix is not to switch
verification off: the same public intermediate is shipped in
``certs/extra-intermediates.pem`` and added to the trusted roots, so the chain
is verified end to end (see ``base.ca_bundle``).

An ordinary BigCommerce Stencil grid otherwise, one page of about forty
products. The product id is on the quickview button inside each card, which
``key_from_inner_id`` reads.

robots.txt disallows the cart, account and search paths and the faceted
``_bc_fsnf`` parameter, and nothing this reads.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://clydearmory.com/"


class ClydeArmoryScraper(BigCommerceScraper):
    slug = "clyde-armory"
    name = "Clyde Armory"
    base_url = SITE_BASE
    newsletter_url = "https://clydearmory.com/"
    newsletter_note = (
        "No form in the page itself; Privy is loaded, so signup is a popup on the home page"
    )
    description = (
        "Georgia dealer's agency trade-in shelf: police Glocks, SIGs, HKs, "
        "Mini-14s and shotguns, among trade-in optics and parts."
    )
    requires_browser = False
    default_interval_minutes = 1440

    sources = ({"category": "Agency Trade-In", "url": f"{SITE_BASE}agency-trade-in/"},)
