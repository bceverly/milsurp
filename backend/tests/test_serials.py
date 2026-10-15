"""When a gun was made: its serial and the year (app.services.serials).

Asked for on 2026-10-15. The phrases are production's, from the 9,276 gun
listings that mention a serial or a date that day; each exclusion is one a
first draft misread. The placement figures are its own leave-one-out test.
"""

from __future__ import annotations

import pytest

from app.models import ArmoryStatus, FirearmModel, Item, Site
from app.services import serials, variants


def serial(text, title=""):
    return serials.read_serial(title, text)


class TestTheSerial:
    @pytest.mark.parametrize(
        ("text", "value", "low", "high"),
        [
            ("Serial no. 165791. Manufactured circa mid-late 1942", "165791", 165791, 165791),
            ("Contract M1 Garand Rifle Serial # 5121908. The rifle", "5121908", 5121908, 5121908),
            ("Model: M1911 Serial Number: 253765 Caliber: 45 ACP", "253765", 253765, 253765),
            ("SKU: 1144596 Serial#: AD003063 Condition: EXCELLENT", "AD003063", 3063, 3063),
            ("Zastava M88 Pistol 1 \u2013 SN: 43575 \u2013 Very Good", "43575", 43575, 43575),
            ("S/N 780xx", "780xx", 78000, 78099),
            ("serial number 10550xx. The receiver", "10550xx", 1055000, 1055099),
            ("Serial numbered in the 3,733,xxx range", "3,733,xxx", 3733000, 3733999),
            ("Its serial number is 21009, and it retains", "21009", 21009, 21009),
        ],
    )
    def test_labeled(self, text, value, low, high):
        found = serial(text)
        assert (found.text, found.low, found.high) == (value, low, high)

    def test_the_prefix_is_kept(self):
        assert serial("Serial#: BC4409 Condition").prefix == "BC"

    @pytest.mark.parametrize(
        "text",
        [
            "Serial numbers for the Remington Rand started at 916405",
            "has a non-match serial number stamped on top of the shank",
            "marked QUALITY H.M.C. with the serial number at the rear",
            "SKU: 1144596 Condition: EXCELLENT",
            "Stock number 4471 and drawing number 6528287",
        ],
    )
    def test_not_a_serial(self, text):
        assert serial(text) is None


def year(text, title=""):
    found = serials.read_stated_year(title, text)
    return (found.year_from, found.year_to) if found else None


class TestAYearStated:
    @pytest.mark.parametrize(
        ("text", "years"),
        [
            ("Serial no. 3657019. Manufactured in 1945 at Springfield", (1945, 1945)),
            ("Manufacturer: Colt Date Manufactured: 1917 Model: M1911", (1917, 1917)),
            ("Serial no. 165791. Manufactured circa mid\u2013late 1942 by Inland", (1942, 1942)),
            ("serial number 34009xx, placing production in approximately 1945", (1945, 1945)),
            ("Serial no. 5301025. Manufactured circa 1954\u20131955 by Springfield", (1954, 1955)),
            ("Manufactured in 1973/74", (1973, 1974)),
            ("All original 1917 production in the 183,xxx serial range", (1917, 1917)),
            ("RECEIVER CIRCA JANUARY 1941. Serial number", (1941, 1941)),
            ("Circa 1840s percussion pistol", (1840, 1849)),
            ("MADE IN OCTOBER 1934 AND LATER PRIATIZED", (1934, 1934)),
        ],
    )
    def test_in_the_dealers_words(self, text, years):
        assert year(text) == years

    @pytest.mark.parametrize(
        "text",
        [
            "Remington began M1903 production in September 1941 at serial number 3,000,000",
            "The M1 Garand was produced from 1937 to 1957",
            "U.S. Model 1903 rifle, Model 1911 pistol",
            "1971 IMPORT, WATER DAMAGE",
        ],
    )
    def test_not_this_guns_year(self, text):
        assert year(text) is None

    def test_a_title_year_is_only_read_as_a_phrase(self):
        assert year(None, "Winchester M1 Garand - 1942 mfg") == (1942, 1942)
        assert year(None, "1945 Springfield M1 Garand - Danish Issued") is None


def evidence(*pairs, prefix=""):
    return [
        serials.Evidence(number, made, made, at, prefix) for at, (number, made) in enumerate(pairs)
    ]


STRAIGHT = evidence(
    (1_000_000, 1942), (1_500_000, 1943), (2_000_000, 1943), (2_600_000, 1944), (3_400_000, 1945)
)


class TestPlacingASerial:
    def test_between_two_that_state_their_year(self):
        found = serials.place(serials.Serial("2300000", 2_300_000, 2_300_000, ""), STRAIGHT)
        assert found[:2] == (1943, 1944)
        assert "2,000,000 (1943) and 2,600,000 (1944)" in found[2]

    def test_never_past_the_ends(self):
        assert serials.place(serials.Serial("1", 500, 500, ""), STRAIGHT) is None
        assert serials.place(serials.Serial("4", 4_000_000, 4_000_000, ""), STRAIGHT) is None

    def test_a_hidden_digit_must_fall_wholly_between(self):
        assert serials.place(serials.Serial("15xxxxx", 1_500_000, 1_599_999, ""), STRAIGHT)[:2] == (
            1943,
            1943,
        )

    def test_too_wide_says_nothing(self):
        wide = evidence((1, 1900), (2, 1901), (3, 1902), (4, 1903), (100, 1940))
        assert serials.place(serials.Serial("50", 50, 50, ""), wide) is None

    def test_numbers_that_restart_are_never_placed(self):
        """A P38's numbers start again each year: a low serial of 1944 sits
        among the high ones of 1938."""
        restarting = evidence(
            (1000, 1941), (2000, 1944), (3000, 1942), (4000, 1943), (5000, 1941), (6000, 1944)
        )
        assert not serials.runs_straight(restarting)
        assert serials.place(serials.Serial("2500", 2500, 2500, ""), restarting) is None

    def test_too_few_to_say(self):
        assert (
            serials.place(serials.Serial("15", 15, 15, ""), evidence((10, 1943), (20, 1943)))
            is None
        )

    def test_a_rebuild_year_does_not_spoil_the_model(self):
        """A 1952 National Match among 1943 and 1944 Springfields."""
        noisy = [*STRAIGHT, *evidence((1_800_000, 1952))]
        kept = serials.without_outliers(noisy)
        assert 1952 not in {e.year_from for e in kept}
        assert serials.place(serials.Serial("2300000", 2_300_000, 2_300_000, ""), noisy)[:2] == (
            1943,
            1944,
        )

    def test_another_prefix_is_another_block(self):
        lettered = evidence((10, 1990), (20, 1991), (30, 1992), (40, 1993), (50, 1994), prefix="AB")
        assert serials.place(serials.Serial("25", 25, 25, "", ""), lettered) is None
        assert serials.place(serials.Serial("AB25", 25, 25, "", "AB"), lettered)[:2] == (1991, 1992)


@pytest.fixture
def garands(clean_db):
    model = FirearmModel(name="M1 Garand", status=ArmoryStatus.APPROVED)
    site = Site(slug="sr", name="Shop SR", base_url="https://sr.test/")
    clean_db.add_all([model, site])
    clean_db.commit()
    return clean_db, model, site


def listing(session, model, site, key, description, maker="Springfield"):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"https://sr.test/{key}",
        title="M1 Garand",
        description=description,
        manufacturer=maker,
        is_rifle=True,
        firearm_model_id=model.id,
        is_active=True,
        is_sold=False,
    )
    session.add(item)
    session.flush()
    variants.settle(session, item)
    session.commit()
    return item


class TestStoredOnTheListing:
    def test_stated_and_placed(self, garands):
        session, model, site = garands
        for at, (number, made) in enumerate(
            [
                (1_000_000, 1942),
                (1_500_000, 1943),
                (2_000_000, 1943),
                (2_600_000, 1944),
                (3_400_000, 1945),
            ]
        ):
            stated = listing(
                session, model, site, f"s{at}", f"Serial no. {number}. Manufactured in {made}."
            )
            assert (stated.serial, stated.made_from, stated.made_source) == (
                str(number),
                made,
                "stated",
            )
        placed = listing(session, model, site, "p", "Serial # 2300000. Nice bore.")
        assert (placed.serial_low, placed.made_from, placed.made_to, placed.made_source) == (
            2_300_000,
            1943,
            1944,
            "serial",
        )
        # Another maker's numbers are another series: Winchester's overlap.
        other = listing(session, model, site, "w", "Serial # 2300000.", maker="Winchester")
        assert other.made_from is None

    def test_the_backfill_reads_then_places(self, garands):
        session, model, site = garands
        for at, (number, made) in enumerate(
            [
                (1_000_000, 1942),
                (1_500_000, 1943),
                (2_000_000, 1943),
                (2_600_000, 1944),
                (3_400_000, 1945),
            ]
        ):
            listing(session, model, site, f"s{at}", f"Serial no. {number}. Manufactured in {made}.")
        waiting = listing(session, model, site, "p", "Serial # 2300000.")
        waiting.made_from = waiting.made_source = None
        session.commit()
        counts = serials.backfill(session)
        session.commit()
        session.refresh(waiting)
        assert counts["stated"] == 5 and counts["placed"] == 1
        assert waiting.made_source == "serial"

    def test_not_a_gun_has_none(self, garands):
        session, model, site = garands
        item = listing(session, model, site, "b", "Serial no. 123456. Manufactured in 1943.")
        item.is_rifle = False
        serials.apply(session, item)
        assert (item.serial, item.made_from) == (None, None)

    def test_shown_by_the_api(self, garands, client, admin_headers):
        session, model, site = garands
        item = listing(session, model, site, "a", "Serial no. 3657019. Manufactured in 1945.")
        body = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert (body["serial"], body["made_from"], body["made_source"]) == (
            "3657019",
            1945,
            "stated",
        )
        assert body["made_quote"] == "Manufactured in 1945"
