"""A gun's barrel length and whether it is threaded (app.services.barrels).

Asked for on 2026-10-13. The phrases are production's, from the 16,535 firearm
listings measured that day: each rule is here with the listing that made it
necessary, and each exclusion with the listing it was wrongly reading.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import ArmoryStatus, FirearmModel, Item, ModelVariant, Site
from app.services import barrels, search, variants


def length(title, description=None, *, long_gun=None):
    return barrels.read_length(title, description, long_gun=long_gun)[0]


class TestTheLength:
    @pytest.mark.parametrize(
        ("text", "long_gun", "inches"),
        [
            ('Made in the 1860s. .52 caliber with 30" barrel.', True, 30.0),
            ("Serial #73401, .22 LR, 22 ½ inch octagon barrel with a good bore", True, 22.5),
            ("3-1/4” barrel with original blade front sight", False, 3.25),
            ("SEMI AUTO PISTOL #538, 6.35MM, 2″ BBL, 80%+ BLUE FINISH", False, 2.0),
            ("Barrel Length: 24.6 inches (625 mm) Material: Stock: Wood", True, 24.6),
            ("chambered in 9mm with a barrel length of 4.6″ and come with one", False, 4.6),
            ('Good Bore Condition: Good Barrels: 23" Inch Weight: 145 Ounces', True, 23.0),
            ("rall with 33” round rifled .577 caliber barrel having British proofs", True, 33.0),
            ('Specs caliber 9mm barrel length 3.7" action Striker', False, 3.7),
            ("This Mossberg 500A 12GA has a 27 inch barrel", True, 27.0),
            (
                "measures 56 and 1/2 inches in overall length and has a 41 and 1/4-inch-long barrel",
                True,
                41.25,
            ),
            ("RUGER VAQUERO .45 COLT - 4 & 5/8 INCH BARREL, STAINLESS", False, 4.625),
            ("Barrel Length: 32 inches Overall Length: 51 Inches Action type: Bolt", True, 32.0),
            ('Barrel Lenght: 19" Stock: Features a distinct two-piece buttstock', True, 19.0),
            ("Capacity: 7 + 1 Barrel Size: 7 inch Overall Height : 5.5 inch", False, 7.0),
            ("Barrel Length: 28.5 Total Length: 48.5 in Weight: 4 kg", True, 28.5),
            ("4″ PINNED & TAPPERED BARREL, JULY OF 1953 MFR", False, 4.0),
            ("Overall length is 67″ with a 51″ bbl. Approximately a 16 bore.", True, 51.0),
            ("Barrel shortened to 22 inch carbine length.", True, 22.0),
            ("2 1/2″ OCTAGON TO ROUND BARREL, BARREL MARKED", False, 2.5),
            ('11.1" rust brown barrel', None, 11.1),
        ],
    )
    def test_the_ways_the_shops_write_it(self, text, long_gun, inches):
        assert length("", text, long_gun=long_gun) == pytest.approx(inches)

    def test_millimeters_give_way_to_the_inches_beside_them(self):
        assert length("", "Barrel Length: 600 mm (24 in)", long_gun=True) == 24.0
        assert length("", "Barrel Length: 550 mm Weight: 4 kg", long_gun=True) == pytest.approx(
            21.654, abs=0.01
        )

    def test_an_overall_length_stated_first_is_not_the_barrel(self):
        """Read as 58, 55.5, 38.5 and 6.5 in the first pass."""
        cases = [
            ("The overall length is 58 inches, the barrel is 43 ½ inches.", True, 43.5),
            ("Overall Length: 55.5″ Barrel: 37 Caliber: .69", True, 37.0),
            ("Overall length is 38½” and has a barrel length of 21”.", True, 21.0),
            ('Overall Length: 6.5" Barrel Length: 3" Weight', False, 3.0),
        ]
        for text, long_gun, inches in cases:
            assert length("", text, long_gun=long_gun) == inches, text

    def test_a_cut_barrel_is_the_length_it_is_now(self):
        text = "7-1/2 inch round barrel has been shortened to 5-1/2 inches and is chambered"
        assert length("", text, long_gun=False) == 5.5

    @pytest.mark.parametrize(
        "text",
        [
            'barrel shortened by approximately 3/4". This is an antique',
            "the right barrel 4 ¾” from the muzzle has a pea size barrel dent",
            'drop and 13 1/2" trigger pull with a browned octaganol barrel',
            "Original 7 inch steel rod with walnut barrel handle",
            "Light pitting on the 2 rear barrel bands",
            'A 1" LIGHT SCRATCH ON THE BARREL AT THE REAR BAND',
            "COLTS ADDRESS IN TWO LINES FOLLOW BY “2” ON TOP OF BARREL",
            "The barrel length is usually about 59 cm (around 23 inches)",
            "The barrel is marked Rock-Ola 2-43.",
        ],
    )
    def test_lengths_that_are_not_the_barrels(self, text):
        assert length("", text, long_gun=None) is None

    def test_a_count_in_a_spec_table_is_not_a_length(self):
        """A Walther PPK/S: "Magazine Count : 2.00 Barrel Description"."""
        title = "WALTHER PPK/S SD 32 AUTO 3.3″ 7-RD SEMI-AUTO PISTOL"
        text = "Magazine Count : 2.00 Barrel Description : Threaded 1/2×28"
        assert length(title, text, long_gun=False) == 3.3

    def test_the_title_comes_first_then_its_bare_length_then_the_description(self):
        assert length('Used TAURUS 692 9MM 2.5" STS', "a 6.5 inch barrel", long_gun=False) == 2.5

    def test_a_rail_is_not_the_barrel(self):
        """The title-only rule took the shorter rail: "9" Barrel 8" U-Rail"."""
        title = 'Brigade MFG BM-9 Forged 9mm AR Pistol 9" Barrel 8" U-Rail, FDE'
        assert length(title, long_gun=False) == 9.0

    def test_implausible_lengths_are_left_alone(self):
        assert length("", "a 60 inch barrel", long_gun=False) is None
        assert length("", "a 3 inch barrel", long_gun=True) is None


class TestThreading:
    @pytest.mark.parametrize(
        "text",
        [
            "Beretta 70 .32 ACP Semi-Auto Pistol w/ Threaded Barrel",
            "The muzzle is threaded for 5/8x24. Comes with 4 total magazines.",
            'Features: HOLOSUN 407A3 X2; 4.5" THREADED; CASE',
            "VZ58 AK Builder Nitrided Barrel Threaded 14-1LH Southern Tactical",
            "a 3-lug quick attachment and a 1/2x28 threaded end for suppressor mounting",
            "Thread Pattern: 14x1 Left Hand",
            "barrel with target crown, ½ x 28 threads that accept the bulk of suppressors",
            "THE MUZZLE IS THREADED AND HAS A NYLON THREAD PROTECTOR",
            "a prior owner had threaded the muzzle",
            "Muzzle Thread: 1/2-36 Chamber: 9mm",
        ],
    )
    def test_threaded(self, text):
        assert barrels.read_threaded("", text)[0] is True

    @pytest.mark.parametrize(
        "text",
        [
            "Action: SAO Barrel Length: 5.0” Threaded Barrel: No Sights: Adjustable",
            "feature an original, unthreaded 3.4 inch barrel",
            'a 16" Non-Threaded barrel with an A2 front sight',
            "Beretta 1934 W/O Threaded Barrel C&R Eligible",
        ],
    )
    def test_stated_not_threaded(self, text):
        assert barrels.read_threaded("", text)[0] is False

    @pytest.mark.parametrize(
        "text",
        [
            # An M1 receiver: where the barrel screws in.
            "Crisp leg markings, barrel threads, and sight knurlings.",
            '16" chrome-lined smoothbore barrel with threaded muzzle for choke tubes',
            "The hickory ramrod has a threaded tip for cleaning and ball removal.",
            "the cleaning rod is in very good condition, though the threaded end is broken",
            "The ramrod that comes stock with this rifle is not threaded for attachments",
            "unthreaded cleaning rod are all fully disclosed",
            "Comes with a spare unthreaded barrel and one magazine",
            "HK45 models can be also be fitted with threaded barrels",
        ],
    )
    def test_not_about_the_muzzle(self, text):
        assert barrels.read_threaded("", text)[0] is None

    def test_the_words_are_kept(self):
        found = barrels.read("Beretta 950B w/ Threaded Barrel", '2.4" barrel', long_gun=False)
        assert found.inches == 2.4
        assert found.threaded is True
        assert found.quotes == {
            "length": '2.4" barrel',
            "threaded": "Beretta 950B w/ Threaded Barrel",
        }


@pytest.fixture
def shop(clean_db):
    site = Site(slug="bt", name="Shop BT", base_url="https://bt.test/")
    clean_db.add(site)
    clean_db.commit()
    return clean_db, site


def gun(session, site, key, title, description=None, **flags):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"https://bt.test/{key}",
        title=title,
        description=description,
        is_pistol=flags.pop("is_pistol", True),
        is_active=True,
        is_sold=False,
        **flags,
    )
    barrels.apply(item)
    session.add(item)
    session.commit()
    return item


def found(session, **filters):
    stmt = search.apply_filters(
        select(Item),
        site_ids=None,
        categories=None,
        calibers=None,
        countries=None,
        manufacturers=None,
        models=None,
        forms=None,
        kinds=None,
        curio_states=None,
        availability="all",
        search=None,
        min_price=None,
        max_price=None,
        new_since_hours=None,
        price_drops_only=False,
        **filters,
    )
    return sorted(item.title for item in session.execute(stmt).scalars())


class TestSearching:
    def test_a_range_one_end_and_one_length(self, shop):
        session, site = shop
        gun(session, site, "a", 'Glock 17 Gen 3 9mm 4.49" Barrel')
        gun(session, site, "b", 'Sig P226 4.4" Barrel .40 S&W')
        gun(session, site, "c", "Colt Python", "with a 6 inch barrel")
        gun(session, site, "d", "Mauser C96 pistol")
        assert found(session, barrel_min=4, barrel_max=5) == [
            'Glock 17 Gen 3 9mm 4.49" Barrel',
            'Sig P226 4.4" Barrel .40 S&W',
        ]
        assert found(session, barrel_min=5) == ["Colt Python"]
        # One length, a twentieth either side: 4.49 is 4.5, 4.4 is not.
        assert found(session, barrel_min=4.5, barrel_max=4.5) == ['Glock 17 Gen 3 9mm 4.49" Barrel']

    def test_threaded_or_not(self, shop):
        session, site = shop
        gun(session, site, "a", "Beretta 70 w/ Threaded Barrel")
        gun(session, site, "b", "Beretta 1934 W/O Threaded Barrel")
        gun(session, site, "c", "Beretta 1934")
        assert found(session, threaded="yes") == ["Beretta 70 w/ Threaded Barrel"]
        assert found(session, threaded="no") == ["Beretta 1934 W/O Threaded Barrel"]

    def test_a_saved_search_keeps_them_and_refuses_nonsense(self):
        query = search.parse_query("barrel_min=4&barrel_max=4.5&threaded=yes")
        assert query.filters["barrel_min"] == 4.0
        assert query.filters["threaded"] == "yes"
        assert "barrel_max=4.5" in query.as_query_string()
        with pytest.raises(search.BadQuery):
            search.parse_query("threaded=maybe")
        with pytest.raises(search.BadQuery):
            search.parse_query("barrel_min=long")

    def test_the_list_endpoint_takes_them(self, shop, client, admin_headers):
        session, site = shop
        gun(session, site, "a", 'Glock 17 Gen 3 9mm 4.49" Barrel', current_price=400.0)
        gun(session, site, "b", 'Sig P226 4.4" Barrel', current_price=400.0)
        page = client.get(
            "/api/items",
            params={"barrel_min": 4.5, "barrel_max": 4.5, "availability": "all"},
            headers=admin_headers,
        ).json()
        assert [row["title"] for row in page["items"]] == ['Glock 17 Gen 3 9mm 4.49" Barrel']
        assert page["items"][0]["barrel_inches"] == 4.49
        assert page["items"][0]["barrel_quotes"] == {"length": 'Glock 17 Gen 3 9mm 4.49" Barrel'}


class TestStoring:
    def test_not_a_gun_has_no_barrel(self, shop):
        session, site = shop
        item = gun(session, site, "a", 'Mauser 98 24" barrel', is_pistol=False)
        assert (item.barrel_inches, item.barrel_threaded, item.barrel_quotes) == (None, None, None)

    def test_the_backfill_reads_every_gun(self, shop):
        session, site = shop
        item = gun(session, site, "a", "Walther P38", 'with a 5" barrel, threaded muzzle')
        item.barrel_inches = item.barrel_threaded = item.barrel_quotes = None
        session.commit()
        counts = barrels.backfill(session)
        session.commit()
        session.refresh(item)
        assert counts["length"] == 1 and counts["threaded"] == 1
        assert (item.barrel_inches, item.barrel_threaded) == (5.0, True)


class TestNarrowingTheVersions:
    def test_a_length_in_the_description_narrows_them(self, shop):
        """The title alone could be any PDP; the description says 4.5"."""
        session, site = shop
        model = FirearmModel(
            name="Walther PDP", status=ArmoryStatus.APPROVED, modern_production=True
        )
        session.add(model)
        session.flush()
        for label, barrel in (("PDP Full Size 4.5", 4.5), ("PDP Full Size 5", 5.0)):
            session.add(
                ModelVariant(
                    model_id=model.id,
                    label=label,
                    barrel_inches=barrel,
                    status=ArmoryStatus.APPROVED,
                )
            )
        item = gun(
            session,
            site,
            "a",
            "WALTHER PDP FS PRE OWNED",
            'Condition: EXCELLENT Features: 4.5" barrel, 2 mags',
            firearm_model_id=model.id,
        )
        variants.settle(session, item)
        session.commit()
        assert item.barrel_inches == 4.5
        assert [v.label for v in variants.candidates(session, item)] == ["PDP Full Size 4.5"]
