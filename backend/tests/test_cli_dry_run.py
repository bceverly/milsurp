"""``cli.py scan --site X --dry-run``: read a vendor, print it, store nothing.

Adding a vendor used to mean a full scan to find out whether the selectors were
right -- and then a catalog in the database to look at, or to undo.
"""

from __future__ import annotations

import argparse

import cli
import pytest
from sqlalchemy import func, select

from app.models import Item, ScanRun
from app.scrapers import ScrapedItem, SiteScraper


class Vendor(SiteScraper):
    slug = "dry-vendor"
    name = "Dry Vendor"
    base_url = "https://dry.test/"
    #: How many the stream offers, and how many it was asked for.
    offered = 50
    produced = 0

    def scrape(self, ctx):
        ctx.warn("one product page answered 403")
        for n in range(self.offered):
            type(self).produced = n + 1
            yield ScrapedItem(
                external_key=f"k{n}",
                url=f"https://dry.test/{n}",
                title=f"Swiss K31 Carbine {n}",
                price=650.0 if n % 2 else None,
                category="Rifles",
            )


@pytest.fixture
def vendor(monkeypatch):
    from app import scrapers

    Vendor.produced = 0
    monkeypatch.setitem(scrapers._REGISTRY, Vendor.slug, Vendor)
    return Vendor


def run(**overrides):
    args = dict(site="dry-vendor", dry_run=True, limit=3, accept_delist=False)
    args.update(overrides)
    return cli.cmd_scan(argparse.Namespace(**args))


def test_it_prints_what_it_parsed(vendor, clean_db, capsys):
    assert run() == 0
    out = capsys.readouterr().out
    assert "Swiss K31 Carbine 0" in out
    assert "3 listing(s) read." in out
    assert "3 rifle" in out
    assert "1 priced" in out
    # A warning is what would make the real scan PARTIAL, so it is shown.
    assert "one product page answered 403" in out


def test_it_stops_at_the_limit(vendor, clean_db):
    run(limit=3)
    assert vendor.produced == 3


def test_it_stores_nothing(vendor, clean_db):
    run()
    assert clean_db.execute(select(func.count()).select_from(Item)).scalar_one() == 0
    assert clean_db.execute(select(func.count()).select_from(ScanRun)).scalar_one() == 0


def test_it_needs_a_site(vendor, capsys):
    assert run(site=None) == 2
    assert "--dry-run needs --site" in capsys.readouterr().err


def test_an_unknown_site_says_so(capsys):
    assert run(site="nobody") == 1
    assert "No scraper is registered" in capsys.readouterr().err
