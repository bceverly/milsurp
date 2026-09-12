"""Reading candidate armory rows out of listings.

The property that matters is not recall. It is that the queue stays worth
reading: a scan that proposes every capitalized word in a title produces a
pending list nobody opens, which is worse than the empty one this replaced.
So most of what follows is about what must *not* be proposed.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, Caliber, FirearmModel, Item, Manufacturer, Site
from app.services import armory, discovery


@pytest.fixture
def cartridge(clean_db):
    row = Caliber(name=".32 ACP", aliases="7.65mm Browning", status=ArmoryStatus.APPROVED)
    clean_db.add(row)
    clean_db.commit()
    armory.invalidate()
    return row


@pytest.fixture
def carbine(clean_db):
    row = FirearmModel(name="M1 Carbine", aliases="US M1 Carbine", status=ArmoryStatus.APPROVED)
    clean_db.add(row)
    clean_db.commit()
    armory.invalidate()
    return row


@pytest.fixture
def site(clean_db):
    row = Site(slug="shop", name="Shop", base_url="https://shop.test/")
    clean_db.add(row)
    clean_db.commit()
    return row


def listing(session, site, title, **kwargs):
    fields = {"is_rifle": True, "is_pistol": False, "caliber": None, "description": None}
    fields.update(kwargs)
    row = Item(
        site_id=site.id,
        external_key=title[:40],
        url=f"https://shop.test/{abs(hash(title))}",
        title=title,
        **fields,
    )
    session.add(row)
    session.commit()
    return row


class TestModelDesignations:
    def shapes(self, session, title, caliber=None):
        return discovery.model_candidates(session, title, caliber)

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("Winchester Model 1873 Lever Action Rifle", "Model 1873"),
            ("Japanese Arisaka Type 99 Rifle", "Type 99"),
            ("German K98k Mauser, all matching", "K98k"),
            ("WWI British No.4 Mk.I Bolt Action", "No.4 Mk.I"),
            ("Czech vz.24 Mauser Rifle", "vz.24"),
            ("Russian Tula M91/30 Bolt Action Rifle", "M91/30"),
            ("CZ75B 9mm Semi-Auto Pistol", "CZ75B"),
            ("British Pattern 1914 Rifle", "Pattern 1914"),
        ],
    )
    def test_the_shapes_the_trade_writes(self, seeded, title, wanted):
        assert wanted in self.shapes(seeded, title)

    def test_a_lot_code_in_parentheses_is_not_a_model(self, seeded):
        """Vendors put them there, and every one has a designation's shape:
        "(L2026-10870)", "(FG389)", "(SGR110)"."""
        assert self.shapes(seeded, "Finnish Mosin Nagant Rifle (L2026-10870)") == []

    def test_nor_is_anything_after_a_serial_number(self, seeded):
        assert self.shapes(seeded, "Colt Python Revolver Serial T34147") == []

    def test_nor_a_caliber(self, seeded):
        """ ".380 ACP 3.5\\" barrel" produced "ACP 3" before the stop list."""
        assert self.shapes(seeded, 'Beretta .380 ACP 3.5" 7 Rd Pistol', ".380 ACP") == []

    def test_nor_a_cartridge_the_armory_knows(self, clean_db, cartridge):
        """ "GP11" has the shape and is the Swiss service round. It reached the
        queue before this rule existed."""
        cartridge.name = "7.5x55mm Swiss"
        cartridge.aliases = "GP11"
        clean_db.commit()
        armory.invalidate()
        assert self.shapes(clean_db, "Swiss Martini Stutzer GP11 Target Rifle") == []

    def test_nor_a_lower_case_phrase(self, seeded):
        """The first version of this was case-insensitive and the bare-initials
        branch matched "with 4" out of "Pistol with 4 magazines"."""
        assert self.shapes(seeded, "Luger Pistol with 4 magazines") == []


class TestTheCollectorShorthands:
    """Widened after measuring: DESIGNATION was built for "M91/30" and "K31"
    and a pass over 5,002 unlinked firearms proposed ten models. These are the
    forms it could not see."""

    def shapes(self, session, title, caliber=None):
        return discovery.model_candidates(session, title, caliber)

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            # One letter and two or three digits. 98 C96s sat unlinked because
            # the letters branch wants two.
            ("MAUSER C96 Broomhandle 7.63mm", "C96"),
            ("Walther P38 9mm Pistol", "P38"),
            # Three digits after a P: the SIG P210 is 48 listings here.
            ("SIG P210 Swiss Service Pistol", "P210"),
            # The space is the point -- "DSM-34" was the only form that matched.
            ("WALTHER DSM 34 Training Rifle", "DSM 34"),
            # A pattern year carrying its update. The slash is what makes it a
            # designation rather than a date.
            ("Swiss 1896/11 Straight Pull Rifle", "1896/11"),
            ("W+F BERN 06/24 Luger", "06/24"),
            # The prefix vocabulary, read case-insensitively for the vendors
            # who write a whole title in capitals.
            ("COLT MODEL 1917 REVOLVER", "MODEL 1917"),
            ("Remington U.S. MODEL OF 1917 Rifle", "MODEL OF 1917"),
            ("MAC MODELE 1950 Pistol", "MODELE 1950"),
            ("MAS MLE 1936 Rifle", "MLE 1936"),
            ("ASTRA MODELO 1921 Semi Auto Pistol", "MODELO 1921"),
            ("Polish Wz.48 Training Rifle", "Wz.48"),
        ],
    )
    def test_the_shapes_the_collectors_write(self, seeded, title, wanted):
        assert wanted in self.shapes(seeded, title)

    def test_a_match_that_stops_at_a_slash_stopped_too_early(self, seeded):
        """The letters-and-digits branch starts further left than the year
        branch and so wins: "WF BERN 96/11" gave "BERN 96"."""
        assert self.shapes(seeded, "WF BERN 96/11") == ["96/11"]

    @pytest.mark.parametrize(
        ("title", "junk"),
        [
            ("COLT COMMANDER GOLD EDITION WITH FACTORY CASE 45 ACP", "CASE 45"),
            ("FN (HERSTAL) AUTO 22 Rifle", "AUTO 22"),
            ("Luger Pistol WITH 2 Magazines", "WITH 2"),
            ("COLT NEW LINE 32 Revolver", "LINE 32"),
        ],
    )
    def test_an_english_word_before_a_number_is_not_one(self, seeded, title, junk):
        """Allowing the space for "DSM 34" turned every short capitalized word
        before a number into a designation."""
        assert junk not in self.shapes(seeded, title)

    def test_but_the_enfield_still_gets_its_number(self, seeded):
        """ "No" sits one word away from that stop list and must stay out of it:
        the head of "No.4 Mk.I" is "No"."""
        assert "No.4 Mk.I" in self.shapes(seeded, "WWI British No.4 Mk.I Bolt Action")


class TestAPatternYearIsNotADate:
    """The Swiss, Swedish and Luger trades name a gun by the year its pattern
    was adopted and nothing else -- "WF BERN 1911", "CARL GUSTAFS 1896", "DWM
    1906", 944 listings of it. A bare four-digit number has no shape that tells
    it from a date, so this rule is context instead."""

    @pytest.mark.parametrize(
        ("title", "wanted"),
        [
            ("WF BERN 1911", "WF BERN 1911"),
            ("CARL GUSTAFS 1896 MAUSER FSR", "CARL GUSTAFS 1896"),
            ("DWM 1906 BRAZILIAN", "DWM 1906"),
            ("FN 1935 HI POWER", "FN 1935"),
            ("BOFORS CARL GUSTAV AB 1896", "CARL GUSTAV AB 1896"),
        ],
    )
    def test_a_maker_and_a_pattern_year(self, seeded, title, wanted):
        assert discovery.year_candidates(title, None) == [wanted]

    def test_the_maker_stays_in_the_name(self, seeded):
        """A bare "1911" would match every Colt automatic in the catalog and a
        bare "1896" would match a serial number."""
        assert discovery.year_candidates("WF BERN 1911", None) == ["WF BERN 1911"]

    @pytest.mark.parametrize(
        "title",
        [
            # No maker in front of it at all.
            "1944 Izhevsk Tula PU Mosin Nagant Sniper",
            # A date word stops the walk-back dead.
            "Original Circa 1850 Belgian Percussion Naval Pistol",
            "Colt Civilian New Army Revolver 41 Colt Built 1904",
            # ...or follows the year.
            "BROWNING HI POWER MADE IN BELGIUM 9MM PISTOL, 1971 MFR",
            # Too late to be a pattern year: ordnance had stopped naming guns
            # for the year of adoption long before.
            "Awesome Ruger Blackhawk Revolver Rare 3 Screw 30 Carbine 1970",
            "CHINESE NORINCO PISTOL, 1966 MFR",
        ],
    )
    def test_a_date_is_not_a_designation(self, seeded, title):
        assert discovery.year_candidates(title, None) == []

    def test_one_sighting_is_not_enough(self, clean_db, site):
        """A positional guess has to corroborate, exactly as a maker does."""
        listing(clean_db, site, "WF BERN 1911")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert "WF BERN 1911" not in found.models

    def test_two_listings_write_it_down(self, clean_db, site):
        listing(clean_db, site, "WF BERN 1911")
        listing(clean_db, site, "WF BERN 1911 PRIVATE SERIES")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert "WF BERN 1911" in found.models
        row = clean_db.query(FirearmModel).filter(FirearmModel.name == "WF BERN 1911").one_or_none()
        assert row is not None
        assert row.status is ArmoryStatus.PENDING

    def test_a_title_that_already_names_a_designation_is_left_alone(self, clean_db, site):
        """It has answered the question. Reading a year out of it as well would
        propose the date it was made alongside the name it goes by."""
        listing(clean_db, site, "1943 Remington M1903A3 Rifle")
        listing(clean_db, site, "1944 Remington M1903A3 Rifle")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert "M1903A3" in found.models
        assert not [name for name in found.models if name.endswith(("1943", "1944"))]

    def test_and_a_bayonet_proposes_nothing(self, clean_db, site):
        """Same rule the whole module runs on: a designation on something that
        is not a gun names what it fits."""
        listing(clean_db, site, "WF BERN 1911 BAYONET", is_rifle=False)
        listing(clean_db, site, "WF BERN 1911 BAYONET w/ scabbard", is_rifle=False)
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert found.models == set()


class TestMakerCandidates:
    def test_the_words_before_a_designation(self, seeded):
        assert "Bernardelli" in discovery.maker_candidates("Bernardelli M1934 .32 ACP Pistol")

    def test_a_three_word_firm_arrives_whole(self, seeded):
        """Capped at two, "James River Armory" became "River Armory" -- a name
        that is wrong rather than merely short."""
        assert "James River Armory" in discovery.maker_candidates(
            "James River Armory M1 Garand Rifle"
        )

    def test_a_nationality_is_not_a_firm(self, seeded):
        assert discovery.maker_candidates("Yugoslavian M48 Mauser Rifle") == []

    def test_nor_is_a_word_about_the_gun(self, seeded):
        assert discovery.maker_candidates("Excellent Condition M1 Carbine") == []

    def test_nor_a_war(self, seeded):
        assert discovery.maker_candidates("WWI Eddystone M1917 Rifle") == ["Eddystone"]


class TestWhatAPassProposes:
    def test_an_unknown_cartridge_is_written_down(self, clean_db, site):
        listing(clean_db, site, "Swedish Mauser rifle", caliber="6.5x55mm Swedish")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert "6.5x55mm Swedish" in found.calibers
        row = clean_db.query(Caliber).filter_by(name="6.5x55mm Swedish").one()
        assert row.status is ArmoryStatus.PENDING

    def test_and_the_title_it_came_from(self, clean_db, site):
        listing(clean_db, site, "Swedish Mauser rifle", caliber="6.5x55mm Swedish")
        discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        row = clean_db.query(Caliber).filter_by(name="6.5x55mm Swedish").one()
        assert row.first_seen_in == "Swedish Mauser rifle"

    def test_a_model_is_proposed_from_a_firearm(self, clean_db, site):
        listing(clean_db, site, "Winchester Model 1873 Lever Action Rifle")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert "Model 1873" in found.models

    def test_but_not_from_an_accessory(self, clean_db, site):
        """A bayonet listing names the rifle it fits, and proposing that
        rifle's designation from it teaches the armory nothing it can trust."""
        listing(
            clean_db,
            site,
            "Bayonet for the Winchester Model 1873",
            is_rifle=False,
            is_pistol=False,
        )
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        assert found.models == set()

    def test_nor_from_a_listing_the_armory_already_matches(self, clean_db, site, carbine):
        listing(clean_db, site, "US M1 Carbine, 1944 Inland")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        assert found.models == set()

    def test_a_maker_seen_once_is_not_written_down(self, clean_db, site):
        """A firm's name has no shape to recognize, so one sighting is a guess.
        A real firm that stocks a shop appears more than once."""
        listing(clean_db, site, "Bernardelli M1934 Pistol", is_rifle=False, is_pistol=True)
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert found.manufacturers == set()
        assert clean_db.query(Manufacturer).count() == 0

    def test_but_one_seen_twice_is(self, clean_db, site):
        for year in ("1938", "1941"):
            listing(
                clean_db,
                site,
                f"Bernardelli M1934 Pistol {year}",
                is_rifle=False,
                is_pistol=True,
            )
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert "Bernardelli" in found.manufacturers
        row = clean_db.query(Manufacturer).filter_by(name="Bernardelli").one()
        assert row.status is ArmoryStatus.PENDING
        assert len(row.first_seen_in.splitlines()) == discovery.MIN_MAKER_SIGHTINGS

    def test_everything_it_writes_is_pending(self, clean_db, site):
        listing(clean_db, site, "Winchester Model 1873 Rifle", caliber=".44-40 Winchester")
        discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert (
            not clean_db.query(FirearmModel)
            .filter(FirearmModel.status != ArmoryStatus.PENDING)
            .count()
        )
        assert not clean_db.query(Caliber).filter(Caliber.status != ArmoryStatus.PENDING).count()


class TestRunningItTwice:
    """It runs at the end of every scan, so this is the load-bearing property."""

    def test_the_second_pass_adds_nothing(self, clean_db, site):
        listing(clean_db, site, "Winchester Model 1873 Rifle", caliber=".44-40 Winchester")
        items = clean_db.query(Item).all()
        discovery.discover(clean_db, items)
        clean_db.commit()
        again = discovery.discover(clean_db, items)
        clean_db.commit()
        assert again.total_added == 0

    def test_the_same_unknown_in_forty_listings_is_one_row(self, clean_db, site):
        """Without a flush after each add, the session's own pending row is
        invisible to the next lookup and the commit dies on a UNIQUE
        violation. Every earlier test committed between proposals, which is
        exactly why nothing caught it."""
        for n in range(40):
            listing(clean_db, site, f"Mauser rifle no. {n}", caliber="8x57mm")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        clean_db.commit()
        assert found.added["calibers"] == 1
        assert clean_db.query(Caliber).filter_by(name="8x57mm").count() == 1

    def test_an_approved_row_stops_being_proposed(self, clean_db, site):
        listing(clean_db, site, "Swedish Mauser rifle", caliber="6.5x55mm Swedish")
        items = clean_db.query(Item).all()
        discovery.discover(clean_db, items)
        clean_db.commit()
        clean_db.query(Caliber).filter_by(name="6.5x55mm Swedish").one().status = (
            ArmoryStatus.APPROVED
        )
        clean_db.commit()
        armory.invalidate()
        assert discovery.discover(clean_db, items).total_added == 0

    def test_and_so_does_one_approved_under_another_spelling(self, clean_db, site):
        """The case that matters. A scan meeting "7.65mm Browning" for the
        hundredth time must not keep proposing it because the row it belongs
        to is called ".32 ACP"."""
        clean_db.add(
            Caliber(
                name=".32 ACP",
                aliases="7.65mm Browning",
                status=ArmoryStatus.APPROVED,
            )
        )
        clean_db.commit()
        armory.invalidate()
        listing(clean_db, site, "CZ 27 pistol", caliber="7.65mm Browning")
        found = discovery.discover(clean_db, clean_db.query(Item).all())
        assert found.calibers == set()
