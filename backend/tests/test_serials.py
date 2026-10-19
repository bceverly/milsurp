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
            ("All models would be produced in 1981", (1981, 1981)),
            ("Winchester Model 94 Saddle Ring Carbine Built 1911 Serial #497382", (1911, 1911)),
            ("1943 production, all matching", (1943, 1943)),
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
            # Misread on production, 2026-10-19:
            "Luger 45 P2020 Made in USA Caliber: 45 ACP",
            "Luger 45 Commander Model 1907 Made in USA Caliber: 45 ACP",
            "MODEL 1861 MILLER CONVERSION 58 RIMFIRE RIFLE MUSKET. RARE ONLY 2000 MADE",
            "returned from foreign nations and sold in a DCM Lottery circa 1995",
            "Colt manufactured 2000 rifles that year",
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
        placed = listing(session, model, site, "p", "Springfield. Serial # 2300000. Nice bore.")
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
        waiting = listing(session, model, site, "p", "Springfield. Serial # 2300000.")
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


class TestSearchingByYearMade:
    """The Year made filter (asked for on 2026-10-17): the year the listing's
    page shows -- stated, placed by its serial, or the C&R reader's."""

    def test_a_range_touches_a_span_and_the_c_and_r_year_counts(
        self, garands, client, admin_headers
    ):
        session, model, site = garands
        listing(session, model, site, "a", "Serial no. 165791. Manufactured in 1942.")
        listing(session, model, site, "b", "Manufactured circa 1943-1944.")
        older = listing(session, model, site, "c", "A fine rifle.")
        older.manufacture_year = 1918
        listing(session, model, site, "d", "Nothing said about when.")
        session.commit()

        def found(**params):
            page = client.get(
                "/api/items", params={"availability": "all", **params}, headers=admin_headers
            ).json()
            return sorted(row["url"].rsplit("/", 1)[1] for row in page["items"])

        assert found(made_min=1944) == ["b"]
        assert found(made_max=1943) == ["a", "b", "c"]
        assert found(made_min=1940, made_max=1942) == ["a"]
        assert found(made_max=1920) == ["c"]
        assert (
            client.get("/api/items", params={"made_min": 900}, headers=admin_headers).status_code
            == 422
        )

    def test_a_saved_search_keeps_it(self):
        from app.services import search

        query = search.parse_query("made_min=1940&made_max=1945")
        assert "made_min=1940" in query.as_query_string()
        with pytest.raises(search.BadQuery):
            search.parse_query("made_min=soon")


@pytest.fixture
def tables(garands):
    """Ranges for the test, not the real tables: the shipped file carries
    those, each with its source."""
    from app.models import Manufacturer, SerialRange

    session, model, site = garands
    springfield = Manufacturer(name="Springfield", aliases="Springfield Armory")
    winchester = Manufacturer(name="Winchester")
    session.add_all([springfield, winchester])
    session.flush()
    for low, high, year in ((1, 49_999, 1940), (50_000, 99_999, 1941)):
        session.add(
            SerialRange(
                model_id=model.id,
                manufacturer_id=springfield.id,
                serial_low=low,
                serial_high=high,
                year_from=year,
                year_to=year,
                source="https://www.cmp.test/garand-serials",
            )
        )
    session.commit()
    session.expire_all()
    return session, model, site


class TestAPublishedTable:
    def test_a_serial_in_a_range_is_dated_by_it(self, tables):
        session, model, site = tables
        item = listing(session, model, site, "a", "Springfield. Serial no. 60123. Nice bore.")
        assert (item.made_from, item.made_to, item.made_source) == (1941, 1941, "table")
        assert item.made_quote == (
            "in Springfield's 50,000 to 99,999, made 1941, as cmp.test publishes"
        )

    def test_only_for_its_maker_and_its_letters(self, tables):
        session, model, site = tables
        other = listing(session, model, site, "w", "Serial no. 60123.", maker="Winchester")
        assert other.made_source is None
        lettered = listing(session, model, site, "l", "Springfield. Serial no. AB60123.")
        assert lettered.made_source is None
        # A maker's other spelling is the maker.
        spelled = listing(
            session,
            model,
            site,
            "s",
            "Springfield Armory. Serial # 123.",
            maker="Springfield Armory",
        )
        assert spelled.made_from == 1940

    def test_only_where_the_listing_names_its_maker(self, tables):
        """A maker read from anything but the listing's words -- "Colt" from a
        ".45 Colt" caliber, "Winchester" for a Krag -- dated the wrong guns
        on production (2026-10-19)."""
        session, model, site = tables
        silent = listing(session, model, site, "n", "Serial no. 60123. Nice bore.")
        assert silent.made_source is None

    @pytest.mark.parametrize(
        "words",
        [
            "Springfield pattern by A. Uberti. Serial no. 60123.",
            "Springfield reproduction. Serial no. 60123.",
            "Non-firing Springfield replica. Serial no. 60123.",
        ],
    )
    def test_never_a_reproduction(self, tables, words):
        session, model, site = tables
        assert listing(session, model, site, "r", words).made_source is None

    def test_letters_after_the_number_are_another_block(self, tables):
        """A Python's "12345E" is not its plain 12345 (2026-10-19)."""
        from app.models import SerialRange

        session, model, site = tables
        session.add(
            SerialRange(
                model_id=model.id,
                suffix="E",
                serial_low=1,
                serial_high=99_999,
                year_from=1975,
                year_to=1975,
                source="https://www.proofhouse.test/pyth.htm",
            )
        )
        session.commit()
        lettered = listing(
            session, model, site, "e", "Winchester. Serial no. 60123E.", maker="Winchester"
        )
        assert (lettered.made_from, lettered.made_source) == (1975, "table")
        assert lettered.made_quote == "in 1E to 99,999E, made 1975, as proofhouse.test publishes"
        plain = listing(
            session, model, site, "p", "Winchester. Serial no. 60123.", maker="Winchester"
        )
        assert plain.made_source is None

    def test_a_hidden_digit_must_fall_inside_one_range(self, tables):
        session, model, site = tables
        item = listing(session, model, site, "h", "Springfield, serial number 4xxxx. The receiver")
        assert item.made_from == 1940
        # 100,000 to 199,999: past the table's end.
        past = listing(session, model, site, "x", "S/N 1xxxxx")
        assert past.made_source is None

    def test_it_comes_before_the_listings_estimate(self, tables):
        session, model, site = tables
        for at, (number, made) in enumerate(
            [(10_000, 1950), (20_000, 1950), (30_000, 1951), (40_000, 1951), (45_000, 1952)]
        ):
            listing(session, model, site, f"s{at}", f"Serial no. {number}. Manufactured in {made}.")
        placed = listing(session, model, site, "p", "Springfield. Serial # 35000.")
        assert (placed.made_from, placed.made_source) == (1940, "table")

    def test_the_c_and_r_line_goes_by_it(self, tables, client, admin_headers):
        session, model, site = tables
        item = listing(
            session, model, site, "c", "Springfield. Serial no. 60123. Rebuilt 2010 import."
        )
        body = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert (body["curio"], body["curio_evidence"]) == ("eligible", "table")

    def test_the_armory_file_carries_them(self, tables, tmp_path):
        import yaml

        from app.services import armory

        session, model, _site = tables
        path = tmp_path / "armory.yaml"
        armory.write_export(session, path)
        written = yaml.safe_load(path.read_text(encoding="utf-8"))
        entry = next(m for m in written["models"] if m["name"] == "M1 Garand")
        assert entry["serials"][0] == {
            "maker": "Springfield",
            "low": 1,
            "high": 49_999,
            "from": 1940,
            "source": "https://www.cmp.test/garand-serials",
        }
        assert not armory.plan_sync(session, path)

        entry["serials"][1]["to"] = 1942
        path.write_text(yaml.safe_dump(written), encoding="utf-8")
        [change] = armory.plan_sync(session, path).models
        assert change.fields == ["serials"]
        armory.apply_sync(session, path)
        session.commit()
        session.refresh(model)
        assert [r.year_to for r in model.serial_ranges] == [1940, 1942]


class TestEditingTablesInTheArmory:
    def test_add_change_and_delete_a_range(self, garands, client, admin_headers):
        from app.models import Manufacturer

        session, model, site = garands
        springfield = Manufacturer(name="Springfield")
        session.add(springfield)
        session.commit()
        item = listing(session, model, site, "a", "Springfield. Serial no. 60123.")
        assert item.made_source is None

        body = {
            "model_id": model.id,
            "manufacturer_id": springfield.id,
            "serial_low": 50_000,
            "serial_high": 99_999,
            "year_from": 1941,
            "year_to": 1941,
            "source": "https://www.cmp.test/garand-serials",
        }
        made = client.post("/api/armory/serials", json=body, headers=admin_headers)
        assert made.status_code == 201, made.text
        assert made.json()["maker"] == "Springfield"
        session.expire_all()
        assert session.get(Item, item.id).made_from == 1941

        changed = client.patch(
            f"/api/armory/serials/{made.json()['id']}",
            json={"year_from": 1942, "year_to": 1942},
            headers=admin_headers,
        )
        assert changed.status_code == 200, changed.text
        session.expire_all()
        assert session.get(Item, item.id).made_from == 1942

        listed = client.get(
            "/api/armory/serials", params={"search": "garand"}, headers=admin_headers
        ).json()
        assert [row["serial_low"] for row in listed] == [50_000]

        gone = client.delete(f"/api/armory/serials/{made.json()['id']}", headers=admin_headers)
        assert gone.status_code == 204
        session.expire_all()
        assert session.get(Item, item.id).made_source is None

    @pytest.mark.parametrize(
        "change",
        [
            {"serial_low": 10, "serial_high": 5},
            {"year_from": 1945, "year_to": 1940},
            {"source": ""},
            {"manufacturer_id": 99_999},
            {"prefix": "A1"},
        ],
    )
    def test_a_range_that_cannot_be_one_is_refused(self, garands, client, admin_headers, change):
        _session, model, _site = garands
        body = {
            "model_id": model.id,
            "serial_low": 1,
            "serial_high": 100,
            "year_from": 1940,
            "year_to": 1940,
            "source": "TM 9-1005-222-12",
            **change,
        }
        refused = client.post("/api/armory/serials", json=body, headers=admin_headers)
        assert refused.status_code == 422


def test_migration_0077_does_not_ask_for_the_tables(garands, monkeypatch):
    """0077 fills in the years before 0081 makes the table of serial ranges:
    on a database with listings, asking for them failed (2026-10-19)."""
    session, model, site = garands
    item = listing(session, model, site, "a", "Serial # 2300000.")
    item.made_source = None
    session.commit()

    def no_table(*_args, **_kwargs):
        raise AssertionError("serial_ranges does not exist yet")

    monkeypatch.setattr(serials, "from_table", no_table)
    counts = serials.backfill(session, tables=False)
    assert counts["serial"] == 1


@pytest.mark.parametrize(
    ("text", "spelling", "named"),
    [
        ("U.S. MODEL 1903A3 BY SMITH CORONA", "Smith-Corona", True),
        ("REMINGTON-UMC U.S. MODEL 1911", "Remington", True),
        ("Colt 45 Bisley SAA", "Colt", True),
        ("Coltrane's rifle", "Colt", False),
    ],
)
def test_a_maker_named_in_the_listings_words(text, spelling, named):
    assert serials._names(text, spelling) is named
