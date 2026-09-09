"""DuPage Trading (dupagetrading.com).

Requested, and small: **20 bayonets and 3 rifles**, every one priced. They are
primarily a parts dealer, and what they sell whole is exactly what this catalog
wants -- M1905s with M3 scabbards, AFH- and ENS-marked M1 bayonets,
new-old-stock M8A1 scabbards, and three WWII rifles (a Springfield Armory M1
Garand, a Winchester M1 Garand, and an M14 rebuilt on a Criterion barrel).

Twenty bayonets is worth having on its own: the whole catalog held 24 before
this shop.

BigCommerce Stencil, on the stock selectors, with ``data-entity-id`` on every
card -- so a listing keeps its identity through a rename.

**Their grid renders each product twice**, which is why the card selector is
narrowed. Every ``li.product`` holds two ``article`` elements, and the base
class's ``li.product article`` alternative takes both: 40 cards for 20
products. The ``seen`` set would collapse them by key and nothing would be
stored twice, but the scan log would report double what the shop sells, and a
count that is wrong in the logs is a count somebody will later trust.

**Most of the shop is left alone**, on the standing rule. ``/parts/`` is broken
down to the barrel, receiver, stock and trigger groups of an M1 Garand and an
M14; ``/rifle-stocks/`` is USGI and reproduction stocks and handguards; and
``/militaria/`` is gear. There is no parts-*kit* section, so the rule that
admits kits costs nothing here -- this is one of the shops where "parts, not
parts kits" is the whole of the decision.

``/firearms/us-military-firearms/`` is the same three guns as ``/firearms/``
and is a sub-category of it, so only the parent is a source.
"""

from __future__ import annotations

from .bigcommerce import BigCommerceScraper

SITE_BASE = "https://dupagetrading.com/"


class DupageTradingScraper(BigCommerceScraper):
    slug = "dupage-trading"
    name = "DuPage Trading"
    base_url = SITE_BASE
    description = (
        "M1 Garand and M14 specialists. Their bayonets and their few complete "
        "rifles are read; their parts, stocks and militaria are not."
    )
    requires_browser = False
    default_interval_minutes = 1440

    #: Narrowed to the card itself. See the note above about the doubled grid:
    #: the base class's ``li.product article`` alternative matches a second
    #: element inside every product and turns 20 listings into 40.
    card_selector = "article.card"

    sources = (
        {"category": "Bayonets", "url": f"{SITE_BASE}bayonets/"},  # 20
        {"category": "Firearms", "url": f"{SITE_BASE}firearms/"},  # 3
    )
