"""Reading a scanned advertising flyer.

The pieces that need no OCR — layout cutting, price parsing, heading detection,
grouping, cropping — are tested directly against synthetic pages, so they run
everywhere and fail for one reason each.

The OCR-dependent tests build their own flyer with Pillow rather than checking
in a scan of a real advertisement: a fixture image of a real vendor's page
would be someone else's copyrighted artwork, it would be a megabyte in the
repository, and it would make these tests a report on one particular scan
rather than on the code.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from app.scrapers import flyer


def blank(width: int = 800, height: int = 1000) -> Image.Image:
    return Image.new("L", (width, height), 255)


def synthetic_page() -> Image.Image:
    """A two-column page divided by a vertical rule, with a rule between rows.

    The columns are *filled* with bars standing in for lines of type, not left
    as empty outlines. That matters: an outlined box has a blank interior, so a
    page drawn that way has whitespace gutters everywhere and does not test the
    thing that made this hard. A real advertisement is text edge to edge, which
    is why whitespace-cutting fails on it and rule-cutting does not.
    """
    page = blank(1200, 900)
    draw = ImageDraw.Draw(page)
    draw.rectangle([595, 0, 605, 900], fill=0)  # the column divider
    draw.rectangle([0, 445, 1200, 455], fill=0)  # a rule between the two rows
    for left, right in ((20, 580), (620, 1180)):
        for top in (60, 120, 180, 240, 300, 360, 520, 580, 640, 700, 760, 820):
            draw.rectangle([left, top, right, top + 26], fill=0)
    return page


class TestPriceParsing:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Only $178.88. C&R or FFL req.", 178.88),
            ("$1,450.00 for the pair", 1450.0),
            ("as is $99", 99.0),
            ("$ 219.00 plus shipping", 219.0),
            ("no price here", None),
            ("", None),
        ],
    )
    def test_parse_price(self, text, expected):
        assert flyer.parse_price(text) == expected

    def test_every_price_in_a_line(self):
        line = "$322.88 for a limited time. Add $25 for hand select and $12 for a sling."
        assert flyer.prices_in(line) == [322.88, 25.0, 12.0]

    def test_a_trailing_full_stop_is_punctuation_not_precision(self):
        assert flyer.parse_price("Yours for $41.00.") == 41.0


class TestHeadingDetection:
    def line(self, text, height=50):
        return flyer.TextLine(text=text, box=(0, 0, 100, height), height=height)

    def test_capitals_make_a_heading(self):
        assert flyer.is_heading(self.line("1893 SPANISH MAUSER LONG RIFLES"))
        assert flyer.is_heading(self.line("INDIAN MILITARY KUKRI KNIVES"))

    def test_prose_does_not(self):
        assert not flyer.is_heading(self.line("with frames, unissued, excellent condition"))
        assert not flyer.is_heading(self.line("Found a small lot of the original Spanish Hornets"))

    def test_a_short_abbreviation_is_not_a_heading(self):
        # These appear mid-sentence all over the page.
        for text in ("FFL", "C&R", "NEW", "MFG"):
            assert not flyer.is_heading(self.line(text))

    def test_size_is_not_consulted_at_all(self):
        """The signal is capitalisation, deliberately, not height.

        An all-caps heading's bounding box is no taller than a line of prose
        with ascenders and descenders, so a height rule found five headings on
        a real page where there were thirty. A tiny heading is still a heading,
        and a huge line of prose is still prose.
        """
        tiny = flyer.TextLine(text="ITALIAN ARTILLERY CARBINES", box=(0, 0, 100, 8), height=8)
        huge = flyer.TextLine(text="with frames, unissued", box=(0, 0, 100, 400), height=400)
        assert flyer.is_heading(tiny)
        assert not flyer.is_heading(huge)


class TestBulletDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "• RUSSIAN M44 CARBINES good condition",
            "· US T-HANDLE TRENCH SHOVELS $58.88",
            "¢ BAYONET GRAB BAG, qty 4 different",
            "e JAP ARISIKA BBL REC",
            "° WW2 US GI HELMETS",
            "« HAND WOVEN BLANKETS",
        ],
    )
    def test_ocr_renders_the_bullet_many_ways(self, text):
        """Tesseract returns the flyer's bullet glyph as whatever it resembles."""
        assert flyer.TextLine(text=text, box=(0, 0, 1, 1), height=1).is_bulleted

    def test_ordinary_text_is_not_bulleted(self):
        for text in ("RUSSIAN M44 CARBINES", "with frames, unissued"):
            assert not flyer.TextLine(text=text, box=(0, 0, 1, 1), height=1).is_bulleted


class TestGrouping:
    def lines(self, *texts):
        return [
            flyer.TextLine(text=t, box=(0, i * 60, 400, i * 60 + 50), height=50)
            for i, t in enumerate(texts)
        ]

    def test_a_heading_starts_a_listing_and_prose_continues_it(self):
        listings = flyer.listings_from_lines(
            self.lines(
                "ITALIAN ARTILLERY CARBINES",
                "Flat shooting super accurate 6.5mm artillery carbine.",
                "Only $199.00. Hand select add $20.00.",
                "1910 MEXICAN MAUSER RIFLES",
                "Back in! Very nice condition. $424.88",
            ),
        )
        assert [x.title for x in listings] == [
            "ITALIAN ARTILLERY CARBINES",
            "1910 MEXICAN MAUSER RIFLES",
        ]

    def test_the_first_price_is_the_price(self):
        """The page states a price once, where the description ends.

        Anything after it is an option — "Add $25 for hand select." Treating
        each amount as its own listing, which an early version did, invented
        products called "and" and "Hand select while available". Taking the
        largest instead held until a listing's text bled into its neighbour's,
        and then reached over and took the bigger number.
        """
        listings = flyer.listings_from_lines(
            self.lines(
                "1903 TURKISH CONTRACT MAUSERS",
                "$322.88 for a limited time. Add $25 for hand select.",
            ),
        )
        assert len(listings) == 1
        assert listings[0].price == 322.88

    def test_a_listing_without_a_price_is_not_a_listing(self):
        # "OLE ZEKE'S TREASURES" is a section header, not something for sale.
        listings = flyer.listings_from_lines(
            self.lines("“OLE ZEKE’S” TREASURES", "VZ24 BAYONET Nice! $28.00")  # noqa: RUF001
        )
        assert [x.price for x in listings] == [28.0]

    def test_each_bullet_is_its_own_listing(self):
        listings = flyer.listings_from_lines(
            self.lines(
                "• US T-HANDLE TRENCH SHOVELS $58.88.",
                "• WW2 ENFIELD NO1 MK2 PARTS KITS. No frame $48.88.",
                "• COLT PP .38 FRAMES. $29.00",
            ),
        )
        assert [x.price for x in listings] == [58.88, 48.88, 29.0]
        assert listings[0].title.startswith("US T-HANDLE")

    def test_bullet_glyph_noise_is_stripped_from_the_title(self):
        listings = flyer.listings_from_lines(self.lines("¢e SWEDISH LEATHER AMMO BELT $29.88"))
        assert listings[0].title.startswith("SWEDISH LEATHER")

    def test_a_short_heading_borrows_the_next_line(self):
        # The flyer sets "CZ 50/70" above "PISTOL KITS"; neither alone is a name.
        listings = flyer.listings_from_lines(
            self.lines("CZ 50/70", "PISTOL KITS", "unissued. Only $178.88.")
        )
        assert listings[0].title == "CZ 50/70 PISTOL KITS"


class TestLayout:
    def test_a_ruled_page_splits_into_its_columns(self):
        page = synthetic_page()
        bounds = flyer.columns(page)
        assert len(bounds) == 2
        left, right = bounds
        assert left[1] <= 600 <= right[0]

    def test_a_blank_page_is_one_column(self):
        assert flyer.columns(blank()) == [(0, 800)]

    def test_every_column_lies_inside_the_page(self):
        page = synthetic_page()
        for left, right in flyer.columns(page):
            assert 0 <= left < right <= page.width

    def test_a_ruled_division_beats_a_ragged_right_margin(self):
        """Short lines line up into a band of blank pixels that is not a gutter.

        Cutting on whitespace here produced three columns and sliced a heading
        in half, so a drawn rule takes precedence over any amount of space.
        """
        page = blank(2000, 600)
        draw = ImageDraw.Draw(page)
        draw.rectangle([980, 0, 990, 600], fill=0)  # the real division
        for top in (60, 140, 220):  # short lines, each leaving a wide margin
            draw.rectangle([40, top, 470, top + 26], fill=0)
            draw.rectangle([1020, top, 1450, top + 26], fill=0)
        bounds = flyer.columns(page)
        assert len(bounds) == 2
        assert bounds[0][1] <= 990 <= bounds[1][0]

    def test_whitespace_alone_would_not_have_cut_this_page(self):
        """The reason the cut looks for rules as well as gutters.

        Every column of a ruled page contains ink, so a classic XY-cut — which
        splits only on blank gutters — finds nothing to split.
        """
        page = synthetic_page()
        binary = flyer._binarize(page)
        profile = flyer._projection(binary, "v")
        blank_runs = flyer._runs(profile, lambda v: v <= flyer.BLANK_COVERAGE, flyer.MIN_BLANK_RUN)
        interior = [r for r in blank_runs if r[0] > 0 and r[1] < len(profile)]
        assert not interior
        # ...but the rule between the columns is found.
        assert flyer._runs(profile, lambda v: v >= flyer.RULE_COVERAGE, flyer.MIN_RULE_RUN)


class TestCropping:
    def test_a_crop_is_a_png_of_the_requested_region(self):
        page = synthetic_page()
        data = flyer.crop_for_listing(page, (100, 100, 400, 300))
        image = Image.open(io.BytesIO(data))
        assert image.format == "PNG"
        assert image.width >= 300

    def test_a_small_crop_is_enlarged_to_stay_legible(self):
        page = synthetic_page()
        box = (100, 100, 200, 160)
        data = flyer.crop_for_listing(page, box)
        image = Image.open(io.BytesIO(data))
        # Enlarged, though MAX_UPSCALE stops it reaching MIN_CROP_LONG_EDGE
        # from something this small — magnifying paper grain helps nobody.
        unscaled_long_edge = (box[2] - box[0]) + 2 * 24
        assert max(image.size) > unscaled_long_edge

    def test_enlargement_is_bounded(self):
        page = blank(2000, 2000)
        data = flyer.crop_for_listing(page, (0, 0, 20, 20))
        image = Image.open(io.BytesIO(data))
        # 20px * MAX_UPSCALE, plus the padding on each side.
        assert max(image.size) <= (20 + 2 * 24) * flyer.MAX_UPSCALE + 1

    def test_a_box_at_the_page_edge_does_not_overflow(self):
        page = synthetic_page()
        data = flyer.crop_for_listing(page, (0, 0, page.width, page.height))
        assert Image.open(io.BytesIO(data)).size == page.size


@pytest.mark.skipif(not flyer.ocr_available(), reason="tesseract is not installed")
class TestWithRealOcr:
    """End to end over a page this test draws itself."""

    def flyer_page(self) -> Image.Image:
        from PIL import ImageFont

        # Wide enough that a 44pt heading fits inside its column: clipped text
        # would make this a test of the page size, not of the reader.
        page = Image.new("L", (2000, 1100), 255)
        draw = ImageDraw.Draw(page)
        try:
            heading = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
            body = ImageFont.truetype("DejaVuSans.ttf", 30)
        except OSError:  # pragma: no cover - depends on host fonts
            pytest.skip("DejaVu fonts are not installed")

        draw.rectangle([980, 0, 990, 1100], fill=0)
        draw.text((40, 60), "SPANISH MAUSER RIFLES", font=heading, fill=0)
        draw.text((40, 140), "Dusty but sound, a fine project rifle.", font=body, fill=0)
        draw.text((40, 190), "Yours for only $110.88 each.", font=body, fill=0)
        draw.text((1020, 60), "ITALIAN CARCANO CARBINES", font=heading, fill=0)
        draw.text((1020, 140), "As is, off the top, all models.", font=body, fill=0)
        draw.text((1020, 190), "Priced at $99.00 only.", font=body, fill=0)
        return page

    def test_it_recovers_both_listings_with_their_prices(self):
        listings = flyer.read_flyer(self.flyer_page())
        by_price = {round(x.price, 2): x for x in listings if x.price}
        assert 110.88 in by_price
        assert 99.0 in by_price
        assert "MAUSER" in by_price[110.88].title.upper()
        assert "CARCANO" in by_price[99.0].title.upper()

    def test_a_column_heading_is_not_read_together_with_its_neighbour(self):
        """The defect that made whole-page OCR unusable.

        Handed the whole page, Tesseract merged headings from different
        columns into one line. Reading a column at a time is what stops it.
        """
        for listing in flyer.read_flyer(self.flyer_page()):
            title = listing.title.upper()
            assert not ("MAUSER" in title and "CARCANO" in title)

    def test_an_empty_page_yields_nothing_rather_than_raising(self):
        assert flyer.read_flyer(blank()) == []


class TestMultiLineProductNames:
    """The flyer breaks a name over as many lines as it needs.

    Every one of these came back from a reader of the real July 2026 flyer as
    a listing with the maker, the model, or both missing.
    """

    def lines(self, *texts):
        return [
            flyer.TextLine(text=t, box=(0, i * 60, 400, i * 60 + 50), height=50)
            for i, t in enumerate(texts)
        ]

    @pytest.mark.parametrize(
        ("raw", "expected", "price"),
        [
            (
                ("S&W", "K-FRAME,", "SNUB-NOSE", "REVOLVER KITS", "very good. No frame $120.88."),
                "S&W K-FRAME, SNUB-NOSE REVOLVER KITS",  # the comma is on the page
                120.88,
            ),
            (
                ("S&W MODEL", "10 PISTOLS", "as is, no barrels. Only $109.00"),
                "S&W MODEL 10 PISTOLS",
                109.0,
            ),
            (
                ("CZ 50/70", "PISTOL KITS", "unissued, excellent. Only $178.88."),
                "CZ 50/70 PISTOL KITS",
                178.88,
            ),
            (
                (
                    "GAHENDRA MARTINI",
                    "BEAUTIFUL HANDSOME",
                    "WOOD STOCK SET",
                    "Cond. NEW. Yours only $138.00.",
                ),
                "GAHENDRA MARTINI BEAUTIFUL HANDSOME WOOD STOCK SET",
                138.0,
            ),
            (
                ("MAUSER C96 PISTOL KITS", "with frames, used. only $278.88."),
                "MAUSER C96 PISTOL KITS",
                278.88,
            ),
        ],
    )
    def test_the_whole_name_survives(self, raw, expected, price):
        listings = flyer.listings_from_lines(self.lines(*raw))
        assert len(listings) == 1
        assert listings[0].title == expected
        assert listings[0].price == price

    def test_a_heading_after_body_text_starts_a_new_listing(self):
        """The run only continues while everything so far is heading text."""
        listings = flyer.listings_from_lines(
            self.lines(
                "ITALIAN ARTILLERY CARBINES",
                "Flat shooting. Only $199.00. Hand select add $20.00.",
                "1910 MEXICAN MAUSER RIFLES",
                "Back in! Very nice condition. $424.88",
            )
        )
        assert [x.title for x in listings] == [
            "ITALIAN ARTILLERY CARBINES",
            "1910 MEXICAN MAUSER RIFLES",
        ]
        assert [x.price for x in listings] == [199.0, 424.88]

    def test_page_furniture_is_not_part_of_a_name(self):
        """The masthead and terms box are capitals too, and drift into titles."""
        listings = flyer.listings_from_lines(
            self.lines("OR MONEY", "MAUSER C96 PISTOL KITS", "used. only $278.88.")
        )
        assert listings[0].title == "MAUSER C96 PISTOL KITS"


class TestPanelsBoundListings:
    """Panels stop one product quoting the price of the one beside it."""

    def panelled(self, *specs):
        out = []
        for index, (text, panel) in enumerate(specs):
            out.append(
                flyer.TextLine(
                    text=text, box=(0, index * 60, 400, index * 60 + 50), height=50, panel=panel
                )
            )
        return out

    def test_a_panel_boundary_ends_a_listing(self):
        """Without this the CZ 50/70 kit took the Turkish Mauser's $322.88."""
        listings = flyer.listings_from_lines(
            self.panelled(
                ("CZ 50/70 PISTOL KITS", 1),
                ("unissued. Only $178.88.", 1),
                ("MFG by germany for the Ottoman Empire. $322.88", 2),
            )
        )
        assert [x.price for x in listings] == [178.88, 322.88]

    def test_a_heading_may_still_cross_one_boundary(self):
        """The flyer draws a rule between a name and its description.

        That single crossing has to be allowed, or every panel is titled with
        the first line of its own prose.
        """
        listings = flyer.listings_from_lines(
            self.panelled(
                ("MAUSER C96 PISTOL KITS", 1),
                ("with frames, used, good condition. only $278.88.", 2),
            )
        )
        assert len(listings) == 1
        assert listings[0].title == "MAUSER C96 PISTOL KITS"
        assert listings[0].price == 278.88


class TestHeadingAttachment:
    """Getting a product's name onto the product, across the rule beneath it."""

    def line(self, text, panel=0, y=0):
        return flyer.TextLine(text=text, box=(0, y, 400, y + 50), height=50, panel=panel)

    def test_a_price_less_group_hands_its_heading_to_the_next_listing(self):
        """A name with no price is a name looking for one.

        Discarding it outright left listings titled "needs TLC" and "frame
        for" — the tail of a bulleted line whose beginning had been thrown
        away with the heading above it.
        """
        listings = flyer.listings_from_lines(
            [
                self.line("RUSSIAN M44 CARBINES", panel=1, y=0),
                self.line("good condition, cracked stock (toe),", panel=2, y=60),
                self.line("needs TLC. $179.88.", panel=2, y=120),
            ]
        )
        assert len(listings) == 1
        assert listings[0].title.startswith("RUSSIAN M44 CARBINES")
        assert listings[0].price == 179.88

    def test_only_the_name_is_carried_not_the_prose(self):
        listings = flyer.listings_from_lines(
            [
                self.line("some trailing prose from the panel above", panel=1, y=0),
                self.line("INDIAN MILITARY KUKRI KNIVES", panel=1, y=60),
                self.line("w/leather sheath. Very good condition $41.00.", panel=2, y=120),
            ]
        )
        assert listings[0].title == "INDIAN MILITARY KUKRI KNIVES"

    def test_a_section_header_does_not_take_a_bullet_s_title(self):
        """ "OLE ZEKE'S TREASURES" is not for sale; the bullet under it is."""
        listings = flyer.listings_from_lines(
            [
                self.line("“OLE ZEKE’S” TREASURES", panel=1, y=0),  # noqa: RUF001
                self.line("• VZ24 BAYONET Nice! $28.00.", panel=1, y=60),
            ]
        )
        assert listings[0].title.startswith("VZ24 BAYONET")

    def test_prose_in_front_of_a_name_is_dropped(self):
        """Every product here is named in capitals, so lower case ahead of it
        is something that leaked in from a neighbouring panel."""
        listings = flyer.listings_from_lines(
            [
                self.line("Swedish steel. GAHENDRA MARTINI RIFLE", panel=1, y=0),
                self.line("BBL Action/Rec $48.88", panel=1, y=60),
            ]
        )
        assert listings[0].title.startswith("GAHENDRA MARTINI RIFLE")

    def test_the_masthead_is_not_a_product_name(self):
        listings = flyer.listings_from_lines(
            [
                self.line("SEE OUR WEB SITE", panel=0, y=0),
                self.line("CZ 50/70 PISTOL KITS", panel=1, y=60),
                self.line("unissued. Only $178.88.", panel=1, y=120),
            ]
        )
        assert "WEB SITE" not in listings[0].title
        assert "CZ 50/70 PISTOL KITS" in listings[0].title


class TestPanelAssignment:
    def test_a_heading_sitting_on_a_rule_belongs_to_a_panel(self):
        """A name is set on the rule that separates it from the panel above.

        Assigning by midpoint put it in the gap between two panels and it
        belonged to neither, which read as a panel change and cut it off from
        its own description.
        """
        boxes = [(0, 0, 400, 100), (0, 120, 400, 300)]
        on_the_rule = flyer.TextLine(text="A NAME", box=(10, 95, 390, 135), height=40)
        assert flyer._panel_of(on_the_rule, boxes) in (0, 1)

    def test_a_line_clear_of_every_panel_takes_the_nearest_below(self):
        boxes = [(0, 200, 400, 400)]
        above = flyer.TextLine(text="A NAME", box=(10, 10, 390, 50), height=40)
        assert flyer._panel_of(above, boxes) == 0

    def test_a_line_over_nothing_at_all_has_no_panel(self):
        assert (
            flyer._panel_of(
                flyer.TextLine(text="x", box=(900, 0, 950, 20), height=20), [(0, 0, 100, 100)]
            )
            == -1
        )


class TestListItemsWhoseBulletWasLost:
    """OCR drops the bullet glyph often enough that it cannot be relied on.

    The lists set each item's name in capitals and then continue in sentence
    case — "BRITISH NO4 MK1 RIFLES as is $88.00." — so the line is neither
    bulleted nor capitalised enough to read as a heading, and it was being
    swallowed by the item above along with its price. On the real page that
    handed the bayonet grab bag the British No4's $88.
    """

    def lines(self, *texts):
        return [
            flyer.TextLine(text=t, box=(0, i * 60, 400, i * 60 + 50), height=50, panel=1)
            for i, t in enumerate(texts)
        ]

    def test_each_item_keeps_its_own_price(self):
        listings = flyer.listings_from_lines(
            self.lines(
                "¢ BAYONET GRAB BAG, qty 4 different,",
                "as is $38.88.",
                "US GI HELMETS, no liner $20.00.",
                "BRITISH NO4 MK1 RIFLES as is $88.00.",
                "FFL or C&R required. Hand select add $20.00.",
            )
        )
        assert [x.price for x in listings] == [38.88, 20.0, 88.0]
        assert listings[2].title.startswith("BRITISH NO4 MK1 RIFLES")

    def test_terms_after_a_price_stay_with_their_item(self):
        """ "FFL or C&R required" opens with capitals and is not a new item."""
        listings = flyer.listings_from_lines(
            self.lines(
                "BRITISH NO4 MK1 RIFLES as is $88.00.",
                "FFL or C&R required. Hand select add $20.00.",
            )
        )
        assert len(listings) == 1
        assert listings[0].price == 88.0

    def test_a_wrapped_name_does_not_split_from_its_description(self):
        """ ".38 SNUB" / "NOSE HOLSTER ... $14.50." is one item in two lines."""
        listings = flyer.listings_from_lines(
            self.lines(
                "Vietnam era unissued leather .38 SNUB",
                "NOSE HOLSTER for belt or boot $14.50.",
            )
        )
        assert len(listings) == 1
        assert listings[0].price == 14.5

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("BRITISH NO4 MK1 RIFLES as is", True),
            ("US GI HELMETS, no liner", True),
            ("1903 BRITISH .303 LEATHER AMMO", True),
            ("FFL or C&R required", False),
            ("as is $38.88.", False),
            ("LIER can fit a variety of rifle", False),
            ("New lot with more parts", False),
        ],
    )
    def test_what_counts_as_opening_with_a_name(self, text, expected):
        assert flyer.starts_with_a_name(text) is expected


class TestPriceIsNotBorrowedFromANeighbour:
    def test_the_first_amount_wins_over_a_larger_later_one(self):
        """Measured on the real page: hand-woven blankets came out at $99.00
        instead of $36.88, having taken the number from the panel beside them,
        and a barrelled receiver at $47.88 instead of $45.00."""
        listings = flyer.listings_from_lines(
            [
                flyer.TextLine(text=t, box=(0, i * 60, 400, i * 60 + 50), height=50, panel=1)
                for i, t in enumerate(
                    (
                        "HAND WOVEN EXTRA LARGE VAQUERO BLANKETS.",
                        "Native hand spun, different colors $36.88.",
                        "off the top $99.00.",
                    )
                )
            ]
        )
        assert listings[0].price == 36.88


class TestNamesBrokenAcrossLines:
    """The flyer hyphenates to fit its columns, mid-word."""

    def lines(self, *texts):
        return [
            flyer.TextLine(text=t, box=(0, i * 60, 400, i * 60 + 50), height=50, panel=1)
            for i, t in enumerate(texts)
        ]

    def test_a_hyphenated_word_is_put_back_together(self):
        """ "BELT/BANDO-" + "LIER" is "BELT/BANDOLIER", not two names."""
        listings = flyer.listings_from_lines(
            self.lines(
                "• SWEDISH LEATHER AMMO BELT/BANDO-",
                "LIER can fit a variety of rifle, cartridge handy, styl-",
                "ish piece $29.88.",
            )
        )
        assert listings[0].title == "SWEDISH LEATHER AMMO BELT/BANDOLIER"
        assert listings[0].price == 29.88

    def test_the_name_stops_where_the_description_starts(self):
        """The two meet mid-line, so the boundary is between words."""
        listings = flyer.listings_from_lines(self.lines("BRITISH NO4 MK1 RIFLES as is $88.00."))
        assert listings[0].title == "BRITISH NO4 MK1 RIFLES"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("COLT PP .38 FRAMES. Most have bbl& maybe few parts $29.00", "COLT PP .38 FRAMES"),
            # Punctuation inside a name is kept ("S&W K-FRAME,"); a trailing
            # comma is where the name ended, so it goes.
            ("US GI HELMETS, no liner $20.00.", "US GI HELMETS"),
            (
                "6.5MM ITALIAN CARCANO CARBINES As Is, off the top $99.00",
                "6.5MM ITALIAN CARCANO CARBINES",
            ),
            ("1903 BRITISH .303 LEATHER AMMO bandolier $39.88", "1903 BRITISH .303 LEATHER AMMO"),
        ],
    )
    def test_digits_and_punctuation_stay_in_the_name(self, raw, expected):
        """A product name is full of both: "6.5MM", ".303", "1940'S", "S&W"."""
        listings = flyer.listings_from_lines(self.lines(raw))
        assert listings[0].title == expected

    def test_a_listing_with_no_recognisable_name_keeps_its_opening_line(self):
        """Better something identifiable than an empty title."""
        listings = flyer.listings_from_lines(
            self.lines("be missing part, but will include some extras $119.00")
        )
        assert listings[0].title.startswith("be missing part")

    def test_the_masthead_is_removed_before_the_name_is_read(self):
        """Not after: stripping it from the finished title emptied it.

        The CZ 50/70 kits carried a scrap of the masthead as their heading, the
        name was read off that, and then the whole of it was stripped away.
        """
        listings = flyer.listings_from_lines(
            self.lines(
                "~ SEE OUR WEB SITE Loc",
                "CZ 50/70",
                "PISTOL KITS",
                "with frames, unissued. Only $178.88.",
            )
        )
        assert listings[0].title == "CZ 50/70 PISTOL KITS"


class TestBulletsWithNoSpaceBehindThem:
    """OCR loses the space after the bullet often enough to matter.

    "¢CZ 52 SEMI AUTO ASSAULT RIFLES" is a bulleted line whose bullet is
    welded to its first word. Read as ordinary text it started no listing, so
    the CZ 52 was swallowed by the Colt frames above it and took its
    photograph with it.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "¢CZ 52 SEMI AUTO ASSAULT RIFLES broken or missing stock",
            "*SPANISH M43 RIFLES off the top $99.00",
            "•BRITISH NO4 MK1 RIFLES as is $88.00",
        ],
    )
    def test_a_glyph_against_a_name_is_still_a_bullet(self, text):
        assert flyer.TextLine(text=text, box=(0, 0, 1, 1), height=1).is_bulleted

    @pytest.mark.parametrize(
        "text",
        [
            "-38 SPECIAL, unissued",
            "(38 CAL) as is",
            "cZ 52 in a sentence",
        ],
    )
    def test_a_character_that_is_also_a_word_still_needs_the_space(self, text):
        """Only the unmistakable glyphs may run straight into the name.

        A hyphen, a bracket or a stray lowercase letter is a real character in
        its own right, so without a space behind it there is nothing to say it
        was ever meant as a bullet.
        """
        assert not flyer.TextLine(text=text, box=(0, 0, 1, 1), height=1).is_bulleted


class TestABulletIsNeverAContinuation:
    """Where one product's name stops being able to reach the next one."""

    def line(self, text, panel=0, y=0, **kw):
        return flyer.TextLine(text=text, box=(0, y, 400, y + 50), height=50, panel=panel, **kw)

    def test_a_price_less_heading_does_not_cross_a_bullet(self):
        """Two products, one price, and the wrong name on it.

        The bandolier's own "39.88." lost its dollar sign to OCR, so its group
        ended without a price and handed its name to the next listing --
        giving "1903 BRITISH .303 LEATHER AMMO JAP ARISIKA BBL REC", one
        listing where there are two.
        """
        listings = flyer.listings_from_lines(
            [
                self.line("¢ 1903 BRITISH .303 LEATHER AMMO", panel=1, y=0),
                self.line("BANDOLIER super cool 39.88.", panel=1, y=60),
                self.line("e JAP ARISIKA BBL REC .T-99, T-38, CARBINE", panel=2, y=120),
                self.line("New lot with more parts, bolts. $45.00.", panel=2, y=180),
            ]
        )
        assert len(listings) == 1
        assert listings[0].price == 45.00
        assert listings[0].title.startswith("JAP ARISIKA")
        assert "1903 BRITISH" not in listings[0].title

    def test_an_unbulleted_wrapped_name_still_carries(self):
        """The case the carry exists for, and which must keep working."""
        listings = flyer.listings_from_lines(
            [
                self.line("S&W", panel=1, y=0),
                self.line("K-FRAME, SNUB-NOSE", panel=1, y=60),
                self.line("REVOLVER KITS", panel=2, y=120),
                self.line("with frames, unissued. $120.88.", panel=2, y=180),
            ]
        )
        assert len(listings) == 1
        assert listings[0].title.startswith("S&W")


class TestAPanelBoundaryOnlyEndsAPricedListing:
    def line(self, text, panel=0, y=0):
        return flyer.TextLine(text=text, box=(0, y, 400, y + 50), height=50, panel=panel)

    def test_a_rule_through_a_sentence_does_not_end_it(self):
        """In the dense half of the page the rules fall mid-sentence.

        A listing ends at its price, which is the one thing these pages are
        consistent about. Cutting at the rule instead separated "1903 TURKISH
        CONTRACT MAUSERS" from the "$322.88" three words later.
        """
        listings = flyer.listings_from_lines(
            [
                self.line("1903 TURKISH CONTRACT MAUSERS", panel=1, y=0),
                self.line("MFG by germany for The Empire. Such an", panel=2, y=60),
                self.line("interesting rifle. $322.88. C&R/FFL", panel=3, y=120),
            ]
        )
        assert len(listings) == 1
        assert listings[0].price == 322.88
        assert listings[0].title.startswith("1903 TURKISH")

    def test_but_it_does_end_one_that_has_its_price(self):
        listings = flyer.listings_from_lines(
            [
                self.line("US GI HELMETS as is $20.00", panel=1, y=0),
                self.line("BRITISH NO4 MK1 RIFLES as is $88.00", panel=2, y=60),
            ]
        )
        assert [item.price for item in listings] == [20.00, 88.00]


class TestPricesPrintedOverAPhotograph:
    """Recovering the prices tesseract files under "picture" and never reads.

    The second pass is faked here rather than driven through tesseract. The
    behaviour worth pinning down is what gets merged and what does not: a real
    scan proved the reading works and cost several products their text before
    the merge was narrowed to single words.
    """

    @staticmethod
    def data(*words):
        """A tesseract word table: (text, left, top, width, line) per word."""
        table: dict[str, list] = {
            key: [] for key in ("text", "conf", "block_num", "par_num", "line_num")
        }
        table.update({key: [] for key in ("left", "top", "width", "height")})
        for text, left, top, width, line in words:
            table["text"].append(text)
            table["conf"].append(96)
            table["block_num"].append(1)
            table["par_num"].append(1)
            table["line_num"].append(line)
            table["left"].append(left)
            table["top"].append(top)
            table["width"].append(width)
            table["height"].append(30)
        return table

    @pytest.fixture
    def second_pass(self, monkeypatch):
        """Make the layout-free pass return a chosen word table."""

        def install(table):
            class FakeTesseract:
                Output = type("Output", (), {"DICT": "dict"})

                @staticmethod
                def image_to_data(_image, config=None, output_type=None):
                    assert config == flyer.NO_LAYOUT_ANALYSIS
                    return table

            monkeypatch.setattr(flyer, "_pytesseract", lambda: FakeTesseract)

        return install

    def region(self):
        return flyer.Region((0, 0, 800, 1000))

    def test_a_price_standing_alone_becomes_its_own_line(self, second_pass):
        """ "Only $378.88" sits over the rifle's stock, in nothing else's line."""
        second_pass(self.data(("Only", 300, 400, 90, 1), ("$378.88", 400, 400, 160, 1)))
        existing = [flyer.TextLine(text="Good to very good.", box=(600, 395, 790, 430), height=30)]

        merged = flyer._prices_lost_in_the_pictures(blank(), self.region(), existing)

        assert sorted(line.text for line in merged) == ["$378.88", "Good to very good."]

    def test_a_price_inside_a_line_is_put_back_where_it_belongs(self, second_pass):
        """Not at either end: the flyer's first price is the real one.

        "ONLY $219.00. Add $25 for hand select" came back from the first pass
        as "ONLY Add $25 for hand select", so the Spanish Mauser was priced at
        its own hand-select surcharge.
        """
        second_pass(self.data(("$219.00.", 120, 400, 150, 1)))
        line = flyer.TextLine(
            text="ONLY Add $25 for hand select",
            box=(20, 395, 600, 430),
            height=30,
            words=[
                (20, (20, 395, 110, 430), "ONLY"),
                (300, (300, 395, 380, 430), "Add"),
                (390, (390, 395, 450, 430), "$25"),
                (460, (460, 395, 520, 430), "for"),
                (530, (530, 395, 600, 430), "hand select"),
            ],
        )

        merged = flyer._prices_lost_in_the_pictures(blank(), self.region(), [line])

        assert merged[0].text == "ONLY $219.00. Add $25 for hand select"
        assert flyer.prices_in(merged[0].text)[0] == 219.00

    def test_a_price_the_first_pass_already_read_is_not_doubled(self, second_pass):
        second_pass(self.data(("$29.00", 100, 400, 130, 1)))
        line = flyer.TextLine(
            text="COLT PP .38 FRAMES $29.00",
            box=(20, 395, 300, 430),
            height=30,
            words=[(100, (100, 395, 230, 430), "$29.00")],
        )

        merged = flyer._prices_lost_in_the_pictures(blank(), self.region(), [line])

        assert [item.text for item in merged] == ["COLT PP .38 FRAMES $29.00"]

    def test_nothing_but_prices_is_taken(self, second_pass):
        """Reading a photograph as text also produces "ae) :" and "~~"."""
        second_pass(self.data(("ae)", 300, 400, 60, 1), ("~~", 380, 400, 40, 1)))
        existing = [flyer.TextLine(text="Good to very good.", box=(600, 395, 790, 430), height=30)]

        merged = flyer._prices_lost_in_the_pictures(blank(), self.region(), existing)

        assert [line.text for line in merged] == ["Good to very good."]


class TestNamesTesseractDidNotRead:
    """A heading set over its own photograph, recovered from the second pass.

    "1903 TURKISH CONTRACT MAUSERS" is underlined, sits directly above the
    rifle's picture, and has the panel rule beneath it. Layout analysis called
    the whole thing a picture and read none of it, so the Ottoman Mauser was
    titled "MFG by germany for The Empire" and cropped to start below its own
    name.
    """

    def line(self, text, top, bottom):
        return flyer.TextLine(text=text, box=(100, top, 900, bottom), height=bottom - top)

    def test_a_heading_in_an_empty_band_is_taken(self):
        first_pass = [self.line("$178.88. C&R or FFL req.", 1245, 1290)]
        assert flyer._in_a_gap(self.line("1903 TURKISH CONTRACT MAUSERS", 1358, 1410), first_pass)

    def test_a_heading_over_text_already_read_is_not(self):
        """The second pass runs text together across a picture, so a line that
        overlaps one already read is a worse copy of it, not a new one."""
        first_pass = [self.line("Swedish steel. GAHENDRA MARTINI RIFLE", 4789, 4840)]
        assert not flyer._in_a_gap(
            self.line("Supply limited. BBL Action/Rec $48.88", 4795, 4845), first_pass
        )


class TestTermsAreNotNames:
    """Every listing says who may buy it, in the same capitals as its name."""

    @pytest.mark.parametrize(
        "text",
        ["NO FFL REQUIRED", "C&R/FFL", "FFL or C&R required", "C&R required", "req"],
    )
    def test_a_line_that_is_only_terms_is_recognized(self, text):
        assert flyer.is_only_terms(text)

    @pytest.mark.parametrize(
        "text",
        ["1888 GERMAN COMMISSION RIFLE", "NOSE HOLSTER", "ENFIELD NO1 MK2 PARTS KITS"],
    )
    def test_a_product_name_is_not(self, text):
        assert not flyer.is_only_terms(text)

    def test_terms_in_front_of_a_name_are_dropped(self):
        """The flyer sets "FFL or / C&R required" in a block beside the
        heading, and OCR reads the two as one line."""
        listings = flyer.listings_from_lines(
            [
                flyer.TextLine(
                    text="FFL or WW2 RUSSIAN 91/30 RIFLES", box=(0, 0, 400, 50), height=50
                ),
                flyer.TextLine(text="C&R required", box=(0, 60, 400, 110), height=50),
                flyer.TextLine(text="Only $378.88", box=(0, 120, 400, 170), height=50),
            ]
        )
        assert listings[0].title == "WW2 RUSSIAN 91/30 RIFLES"

    def test_a_terms_only_line_is_dropped_whole_not_trimmed(self):
        """Trimming the front of "C&R or FFL" leaves "FFL", which then reads as
        the next word of the name above it."""
        listings = flyer.listings_from_lines(
            [
                flyer.TextLine(text="1910 MEXICAN MAUSER RIFLES", box=(0, 0, 400, 50), height=50),
                flyer.TextLine(text="C&R or FFL", box=(0, 60, 400, 110), height=50),
                flyer.TextLine(
                    text="Back in! Very nice. $424.88", box=(0, 120, 400, 170), height=50
                ),
            ]
        )
        assert listings[0].title == "1910 MEXICAN MAUSER RIFLES"


class TestASectionHeaderIsNotAName:
    def line(self, text, y):
        return flyer.TextLine(text=text, box=(0, y, 400, y + 50), height=50)

    def test_a_product_that_names_itself_does_not_take_the_section_above_it(self):
        listings = flyer.listings_from_lines(
            [
                # Curly quotes because that is what tesseract returns here.
                self.line("“OLE ZEKE’S” TREASURES", 0),  # noqa: RUF001
                self.line("RUSSIAN M44 CARBINES good condition, cracked stock (toe),", 60),
                self.line("needs TLC. $179.88.", 120),
            ]
        )
        assert listings[0].title == "RUSSIAN M44 CARBINES"

    def test_a_name_broken_across_lines_keeps_all_of_itself(self):
        """No line here names itself, so nothing is a section header."""
        listings = flyer.listings_from_lines(
            [
                self.line("S&W", 0),
                self.line("K-FRAME, SNUB-NOSE", 60),
                self.line("REVOLVER KITS", 120),
                self.line("with frames, unissued. $120.88.", 180),
            ]
        )
        assert listings[0].title.startswith("S&W")

    def test_a_price_is_not_a_name_word(self):
        """ "ONLY $219.00. Add $25 for hand select" is the tail of the listing
        above it, not a product naming itself."""
        listings = flyer.listings_from_lines(
            [
                self.line("1916 SPANISH MAUSER", 0),
                self.line("ONLY $219.00. Add $25 for hand select", 60),
            ]
        )
        assert listings[0].title == "1916 SPANISH MAUSER"
        assert listings[0].price == 219.00

    def test_a_heading_stops_where_the_prose_starts(self):
        """ "MFG by germany for The Ottoman Empire" opens with a capital because
        it opens a sentence, not because it continues the name."""
        listings = flyer.listings_from_lines(
            [
                self.line("1903 TURKISH CONTRACT MAUSERS", 0),
                self.line("MFG by germany for The Ottoman Empire. Such an", 60),
                self.line("impressive unit. $322.88 for a limited time.", 120),
            ]
        )
        assert listings[0].title == "1903 TURKISH CONTRACT MAUSERS"

    def test_but_a_hyphenated_break_still_crosses_into_the_prose(self):
        listings = flyer.listings_from_lines(
            [
                self.line("SWEDISH LEATHER AMMO BELT/BANDO-", 0),
                self.line("LIER can fit a variety of rifle, cartridge", 60),
                self.line("handy, stylish piece $29.88.", 120),
            ]
        )
        assert listings[0].title == "SWEDISH LEATHER AMMO BELT/BANDOLIER"


class TestALicenseIsNotAProduct:
    """A price with no name of its own belongs to the listing above it.

    "ENFIELD NO1 MK2 PARTS KITS. No frame $48.88. Add frame for $38.88.
    C&R/FFL required." is one listing with a second price on it. A rule falling
    between the two lines split it, and the second half — having a price and no
    name — became a $38.88 product called "C&R/FFL", which is a license the ATF
    issues and not something anybody sells.
    """

    def line(self, text, panel=0, y=0):
        return flyer.TextLine(text=text, box=(0, y, 400, y + 50), height=50, panel=panel)

    def listings(self):
        return flyer.listings_from_lines(
            [
                self.line("¢ ENFIELD NO1 MK2 PARTS KITS. No frame $48.88. Add", panel=1, y=0),
                self.line("frame for $38.88. C&R/FFL required.", panel=2, y=60),
            ]
        )

    def test_it_does_not_become_a_listing_of_its_own(self):
        found = self.listings()
        assert len(found) == 1
        assert found[0].title == "ENFIELD NO1 MK2 PARTS KITS"

    def test_the_first_price_is_still_the_product_s_price(self):
        assert self.listings()[0].price == 48.88

    def test_the_option_is_kept_in_the_description(self):
        """Put back rather than dropped: it is a real thing the dealer offers."""
        assert "38.88" in self.listings()[0].description

    def test_and_the_crop_grows_to_cover_it(self):
        """The picture was stopping short of the panel it was cut from."""
        assert self.listings()[0].box[3] >= 110

    def test_a_named_listing_after_one_is_still_its_own(self):
        found = flyer.listings_from_lines(
            [
                self.line("¢ ENFIELD NO1 MK2 PARTS KITS. No frame $48.88.", panel=1, y=0),
                self.line("¢ COLT PP .38 FRAMES. Most have bbl. $29.00", panel=2, y=60),
            ]
        )
        assert [item.title for item in found] == [
            "ENFIELD NO1 MK2 PARTS KITS",
            "COLT PP .38 FRAMES",
        ]
