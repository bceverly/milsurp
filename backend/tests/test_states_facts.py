"""Every scraper that hands over a vendor's caliber, country or maker says so.

``states_facts`` is what stops a scan attributing a stored value of unknown
origin to the rules. A scraper that fills one of those fields but forgets the
flag would let the vendor's word be recorded as ours, and a later recompute
could then overwrite it -- the exact damage provenance exists to prevent. So
this reads each scraper's source rather than trusting a list.
"""

from __future__ import annotations

import inspect
import re

import pytest

from app.scrapers import SCRAPER_CLASSES, SiteScraper
from app.scrapers.demo import DemoScraper

#: A keyword argument or an assignment to one of the three fields.
_SETS_A_FACT = re.compile(r"^(?!\s*#).*\b(?:caliber|country|manufacturer)\s*=(?!=)", re.M)


def _own_modules(cls: type) -> list[str]:
    """Source of every module in this scraper's ancestry, bar the base."""
    sources = []
    for klass in cls.__mro__:
        if klass in (SiteScraper, object) or not issubclass(klass, SiteScraper):
            continue
        module = inspect.getmodule(klass)
        if module is not None:
            sources.append(inspect.getsource(module))
    return sources


@pytest.mark.parametrize(
    "scraper", [*SCRAPER_CLASSES, DemoScraper], ids=lambda cls: cls.slug or cls.__name__
)
def test_a_scraper_that_sets_a_fact_declares_it(scraper):
    sets = any(_SETS_A_FACT.search(source) for source in _own_modules(scraper))
    if sets:
        assert (
            scraper.states_facts
        ), f"{scraper.__name__} sets caliber, country or maker; give it states_facts = True"


def test_most_do_not():
    """The flag is only worth having because most scrapers state nothing."""
    assert sum(1 for cls in SCRAPER_CLASSES if not cls.states_facts) > 10
