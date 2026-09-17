"""What a kind of gun goes for, across every dealer at once.

Four decisions carry this page and each is one the naive version gets wrong:
the median rather than the mean, firearms only, percentiles rather than the
range, and a minimum sample. There is a test for each, because each looks like
an arbitrary choice until the listing that motivated it turns up.

The concentration flag is the one that came out of building it. Most bands in
a real catalog are one dealer -- 7.5x55mm Swiss is 94% a single shop -- and a
median from one shelf is that shop's pricing rather than the market's.
"""

from __future__ import annotations

import pytest

from app.models import Item, Site
from app.services import market


@pytest.fixture
def shops(clean_db):
    rows = [
        Site(slug=f"shop{n}", name=f"Shop {n}", base_url=f"https://s{n}.test/") for n in range(1, 4)
    ]
    clean_db.add_all(rows)
    clean_db.commit()
    return rows


def stock(session, site, caliber, prices, *, is_rifle=True, **kwargs):
    for index, price in enumerate(prices):
        session.add(
            Item(
                site_id=site.id,
                external_key=f"{site.slug}-{caliber}-{index}-{kwargs.get('tag', '')}",
                url=f"{site.base_url}{index}",
                title=f"{caliber} thing {index}",
                caliber=caliber,
                current_price=float(price),
                is_active=kwargs.get("is_active", True),
                is_sold=kwargs.get("is_sold", False),
                is_rifle=is_rifle,
                is_pistol=False,
            )
        )
    session.commit()


class TestTheTypicalPrice:
    def test_it_is_the_median_not_the_mean(self, clean_db, shops):
        """One dealer listing a heap of cheap stock drags a mean and leaves a
        median where it was."""
        stock(clean_db, shops[0], "8mm Mauser", [500, 500, 500, 500, 500, 20000])
        band = market.summarize(clean_db, "caliber").bands[0]
        assert band.median == 500
        assert band.listings == 6

    def test_the_spread_is_the_tenth_to_the_ninetieth(self, clean_db, shops):
        """A single extraordinary listing sets the maximum and says nothing
        about the ones anybody will buy."""
        stock(clean_db, shops[0], ".45-70", [100, 200, 300, 400, 500, 750000])
        band = market.summarize(clean_db, "caliber").bands[0]
        assert band.high < 750000
        assert band.low >= 100


class TestWhatIsCountedAtAll:
    def test_a_parts_kit_is_not_a_gun(self, clean_db, shops):
        """A caliber's listings mix rifles with bayonets and magazines, and a
        median across those describes nothing that exists."""
        stock(clean_db, shops[0], "8mm Mauser", [600, 620, 640, 660, 680])
        stock(clean_db, shops[0], "8mm Mauser", [40, 40, 40, 40, 40], is_rifle=False, tag="acc")

        firearms = market.summarize(clean_db, "caliber").bands[0]
        assert firearms.listings == 5
        assert firearms.median == 640

        everything = market.summarize(clean_db, "caliber", firearms_only=False).bands[0]
        assert everything.listings == 10

    def test_a_sold_listing_is_not_on_the_shelf(self, clean_db, shops):
        stock(clean_db, shops[0], "8mm Mauser", [600, 620, 640, 660, 680])
        stock(
            clean_db, shops[0], "8mm Mauser", [10, 10, 10], is_sold=True, is_active=False, tag="s"
        )
        assert market.summarize(clean_db, "caliber").bands[0].listings == 5

    def test_a_group_too_small_to_mean_anything_is_reported_not_dropped(self, clean_db, shops):
        """A page showing sixty bands out of a hundred and sixty owes the
        reader that number."""
        stock(clean_db, shops[0], "8mm Mauser", [600, 620, 640, 660, 680])
        stock(clean_db, shops[0], "11mm Gras", [900, 950], tag="g")

        result = market.summarize(clean_db, "caliber")
        assert [band.value for band in result.bands] == ["8mm Mauser"]
        assert result.thin_groups == 1
        assert result.thin_listings == 2

    def test_the_threshold_can_be_lowered(self, clean_db, shops):
        stock(clean_db, shops[0], "11mm Gras", [900, 950])
        assert market.summarize(clean_db, "caliber", min_sample=2).bands[0].listings == 2


class TestWhoTheBandBelongsTo:
    def test_a_band_from_one_shop_says_so(self, clean_db, shops):
        stock(clean_db, shops[0], "7.5x55mm Swiss", [400, 420, 440, 460, 480])
        band = market.summarize(clean_db, "caliber").bands[0]
        assert band.sites == 1
        assert band.top_site_share == 1.0
        assert band.concentrated is True

    def test_a_band_several_shops_share_does_not(self, clean_db, shops):
        for shop in shops:
            stock(clean_db, shop, "9mm Luger", [400, 420, 440])
        band = market.summarize(clean_db, "caliber").bands[0]
        assert band.sites == 3
        assert band.top_site_share < market.CONCENTRATED
        assert band.concentrated is False


class TestTheDimensions:
    def test_each_one_groups_by_its_own_column(self, clean_db, shops):
        stock(clean_db, shops[0], "8mm Mauser", [600, 620, 640, 660, 680])
        for item in clean_db.query(Item).all():
            item.country = "Germany"
            item.manufacturer = "Mauser"
        clean_db.commit()

        for dimension, expected in (
            ("caliber", "8mm Mauser"),
            ("country", "Germany"),
            ("manufacturer", "Mauser"),
        ):
            assert market.summarize(clean_db, dimension).bands[0].value == expected

    def test_an_unknown_one_is_refused(self, clean_db):
        with pytest.raises(ValueError):
            market.summarize(clean_db, "color")


class TestTheEndpoint:
    def test_any_signed_in_user_may_read_it(self, client, normal_user):
        response = client.get("/api/market", headers=normal_user["headers"])
        assert response.status_code == 200, response.text
        assert response.json()["dimension"] == "caliber"

    def test_it_needs_signing_in(self, client):
        assert client.get("/api/market").status_code == 401

    def test_an_unknown_dimension_is_refused_rather_than_ignored(self, client, admin_headers):
        response = client.get("/api/market?by=color", headers=admin_headers)
        assert response.status_code == 422

    def test_accessories_are_asked_for_rather_than_excluded(self, client, admin_headers):
        """The client's query builder drops a false boolean, so a parameter
        whose default is on can never be turned off from the browser. Spelled
        as the non-default, absence means the default and the switch works."""
        default = client.get("/api/market", headers=admin_headers).json()
        assert default["firearms_only"] is True

        included = client.get("/api/market?include_accessories=true", headers=admin_headers)
        assert included.json()["firearms_only"] is False

    def test_the_sample_floor_is_bounded(self, client, admin_headers):
        assert client.get("/api/market?min_sample=1", headers=admin_headers).status_code == 422
        assert client.get("/api/market?min_sample=2", headers=admin_headers).status_code == 200
