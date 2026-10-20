"""New or used (app.services.newness), asked for on 2026-10-20."""

from __future__ import annotations

import pytest

from app.models import Item, Site
from app.services import newness, search


class TestDeciding:
    def test_the_shops_filing_comes_first(self):
        assert newness.decide(True, newness.USED, "USED Glock 19") is True
        assert newness.decide(False, newness.NEW, "Glock 19") is False

    def test_then_what_the_shop_sells(self):
        assert newness.decide(None, newness.USED, "Glock 19 New in Box") is False
        assert newness.decide(None, newness.NEW, "Pietta 1858") is True

    @pytest.mark.parametrize(
        ("title", "category", "expected"),
        [
            ("USED Glock 19 Gen 3", None, False),
            ("S&W 642 Pre-Owned", None, False),
            ("LE Trade-In Sig P229", None, False),
            ("Glock 43X, New in Box", None, True),
            ("NIB Ruger LCR", None, True),
            ("Inland M1 Carbine", "Certified Used", False),
            ("Kentucky Pistol - Flint", "Used Muzzleloading Pistols", False),
            ("Ruger GP100", None, None),
        ],
    )
    def test_on_a_mixed_shop_the_words(self, title, category, expected):
        assert newness.decide(None, newness.MIXED, title, category) is expected

    def test_nothing_known_is_none(self):
        assert newness.decide(None, None, "Glock 19") is None


@pytest.fixture
def stocked(clean_db):
    """One listing each from a shop of used guns, one of new, and one of both."""
    rows = []
    for slug, title, category in (
        ("clyde-armory", "Glock 22 LE trade-in", None),
        ("muzzle-loaders", "Pietta 1858 New Army", None),
        ("centerfire-systems", "Inland M1 Carbine", "Certified Used"),
        ("centerfire-systems", "Cimarron 1873", "Classic Military"),
    ):
        site = clean_db.query(Site).filter_by(slug=slug).one_or_none()
        if site is None:
            site = Site(slug=slug, name=slug, base_url=f"https://{slug}.test/")
            clean_db.add(site)
            clean_db.flush()
        item = Item(
            site_id=site.id,
            external_key=f"{slug}-{len(rows)}",
            url=f"https://{slug}.test/{len(rows)}",
            title=title,
            category=category,
            is_active=True,
            is_sold=False,
            is_pistol=True,
        )
        clean_db.add(item)
        rows.append(item)
    clean_db.commit()
    return clean_db, rows


def test_the_backfill_files_every_listing(stocked):
    session, rows = stocked
    counts = newness.backfill(session)
    session.commit()
    for row in rows:
        session.refresh(row)
    assert [row.is_new for row in rows] == [False, True, False, None]
    assert counts == {"new": 1, "used": 2, "unknown": 1}


def test_searching_new_or_used(stocked, client, admin_headers):
    session, _rows = stocked
    newness.backfill(session)
    session.commit()

    def titles(**params):
        page = client.get(
            "/api/items", params={"availability": "all", **params}, headers=admin_headers
        ).json()
        return sorted(row["title"] for row in page["items"])

    assert titles(newness="new") == ["Pietta 1858 New Army"]
    assert titles(newness="used") == ["Glock 22 LE trade-in", "Inland M1 Carbine"]
    refused = client.get("/api/items", params={"newness": "old"}, headers=admin_headers)
    assert refused.status_code == 422
    with pytest.raises(search.BadQuery):
        search.parse_query("newness=old")
    assert "newness=used" in search.parse_query("newness=used").as_query_string()


def test_a_scan_files_each_listing(clean_db):
    """The scraper's own filing, then what its shop sells."""
    from app.scrapers.base import ScrapedItem
    from app.services import scan_service

    site = Site(slug="clyde-armory", name="Clyde", base_url="https://c.test/")
    clean_db.add(site)
    clean_db.commit()

    def scan(key, **fields):
        scraped = ScrapedItem(external_key=key, url=f"https://c.test/{key}", title="Glock 22")
        for name, value in fields.items():
            setattr(scraped, name, value)
        item, _, _ = scan_service._upsert_item(
            clean_db, site, scraped, run=None, seen_at=scan_service.utcnow()
        )
        clean_db.commit()
        return item

    assert scan("a").is_new is False  # Clyde Armory sells used guns
    assert scan("b", is_new=True).is_new is True
