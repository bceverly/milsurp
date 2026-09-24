"""A row awaiting approval shows how many listings *name* it.

Such a row links nothing -- that is what awaiting approval means -- so its link
count was always 0 and said nothing about whether it was worth approving. The
count is taken with the browse page's own search, and the row's eye opens that
search, so the number and the page cannot disagree.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Site
from app.services import search


@pytest.fixture
def catalog(seeded):
    site = seeded.query(Site).order_by(Site.id).first()
    rows = [
        ("Astra 600/43 pistol, 9mm", None, None),
        ("War time ASTRA 600/43", None, None),
        ("A Spanish pistol", "An Astra 600/43 in good order", None),  # description
        ("Astra 600 pistol", None, None),  # not the phrase
        ("Model 1808 musket", None, None),
        ("Model 18 rifle", "made in 08", None),  # the words, apart: no match
        ("Rifle", None, "Model"),  # across two columns: no match
    ]
    for n, (title, description, caliber) in enumerate(rows):
        seeded.add(
            Item(
                site_id=site.id,
                external_key=f"m{n}",
                url=f"https://m.test/{n}",
                title=title,
                description=description,
                caliber=caliber,
                is_active=n != 1,  # sold and de-listed still count
            )
        )
    seeded.add_all(
        [
            FirearmModel(name="600/43", status=ArmoryStatus.PENDING),
            FirearmModel(name="Model 1808", status=ArmoryStatus.PENDING),
            FirearmModel(name="Astra 600", status=ArmoryStatus.APPROVED),
        ]
    )
    seeded.commit()
    return seeded


class TestTheCount:
    def test_it_is_the_quoted_phrase_anywhere_in_a_listing(self, catalog):
        assert search.count_mentions(catalog, "600/43") == 3
        assert search.count_mentions(catalog, "Model 1808") == 1

    @pytest.mark.parametrize("name", ["600/43", "Model 1808", "Model 18", "Astra", "nothing"])
    def test_the_batch_count_agrees_with_the_search(self, catalog, name):
        """The batch version exists for speed. It must not be a second opinion."""
        assert search.count_mentions_many(catalog, [name])[name] == search.count_mentions(
            catalog, name
        )


class TestTheArmoryPage:
    def rows(self, client, headers, status):
        body = client.get(f"/api/armory/models?status={status}", headers=headers).json()
        return {row["name"]: row for row in body}

    def test_a_pending_row_carries_its_mentions(self, client, admin_headers, catalog):
        rows = self.rows(client, admin_headers, "pending")
        assert rows["600/43"]["mention_count"] == 3
        assert rows["600/43"]["item_count"] == 0
        assert rows["Model 1808"]["mention_count"] == 1

    def test_an_approved_row_does_not(self, client, admin_headers, catalog):
        """It has real links to count, and mixing the two would mislead."""
        assert self.rows(client, admin_headers, "approved")["Astra 600"]["mention_count"] is None
