"""BigCommerce custom fields, and the shop that publishes nothing else.

Legacy Collectibles write no prose description on any of their 258 listings.
What they write instead is BigCommerce's stock custom-field table:

    Year: 1911-15   Maker: Mauser   Type: C96
    Caliber: 7.63mm Mauser   Bore: 9/10   Condition: ~94-95%

That is better than prose, because it is the vendor *stating* what this
application otherwise infers from a title -- and a stated value outranks a
derived one everywhere else here. These pin the reading of it, the boundary on
what a shop's own field names are allowed to mean, and the one measured reason
the fields are named rather than poured in as text.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.scrapers.bigcommerce import BigCommerceScraper, custom_fields, sold_out
from app.scrapers.legacy_collectibles import LegacyCollectiblesScraper


def table(*rows: tuple[str, str]) -> BeautifulSoup:
    cells = "".join(
        f'<tr><td class="custom-field-label"><strong>{label}</strong></td>'
        f'<td class="custom-field-value">{value}</td></tr>'
        for label, value in rows
    )
    return BeautifulSoup(
        f'<div><table class="productView-custom-fields"><tbody>{cells}</tbody></table></div>',
        "html.parser",
    )


MAUSER = (
    ("Year:", "1911-15"),
    ("Maker:", "Mauser"),
    ("Type:", "C96"),
    ("Caliber:", "7.63mm Mauser"),
    ("Bore:", "9/10"),
    ("Condition:", "~94-95%"),
)


class TestReadingTheTable:
    def test_every_row_comes_back(self):
        assert custom_fields(table(*MAUSER)) == {
            "year": "1911-15",
            "maker": "Mauser",
            "type": "C96",
            "caliber": "7.63mm Mauser",
            "bore": "9/10",
            "condition": "~94-95%",
        }

    def test_the_label_loses_its_colon_and_its_case(self):
        """A shop that writes "Caliber:" and one that writes "caliber" have to
        read the same, or a subclass's map is guessing at punctuation."""
        assert custom_fields(table(("CALIBER:", "8mm"))) == {"caliber": "8mm"}

    def test_a_row_missing_half_of_itself_is_skipped(self):
        soup = BeautifulSoup(
            '<table class="productView-custom-fields"><tr>'
            '<td class="custom-field-label">Maker:</td></tr></table>',
            "html.parser",
        )
        assert custom_fields(soup) == {}

    def test_an_empty_value_is_not_a_fact(self):
        """BigCommerce renders a field the shop left blank as an empty cell."""
        assert custom_fields(table(("Maker:", ""), ("Caliber:", "8mm"))) == {"caliber": "8mm"}

    def test_a_page_with_no_table_is_not_an_error(self):
        assert custom_fields(BeautifulSoup("<div>Nothing here.</div>", "html.parser")) == {}


class TestWhatAFieldIsAllowedToMean:
    """A shop's field names are its own business; what they may set here is
    not. "Type" means the model on one site and the action on another."""

    def test_only_the_four_a_vendor_can_state(self):
        class Shop(BigCommerceScraper):
            slug, name, base_url = "s", "S", "https://s.example/"
            custom_field_map = (("type", "is_rifle"),)

        with pytest.raises(ValueError, match="is_rifle"):
            Shop()._stated({"type": "Rifle"})

    def test_a_field_the_shop_did_not_fill_sets_nothing(self):
        assert LegacyCollectiblesScraper()._stated({"maker": "Mauser"}) == {
            "manufacturer": "Mauser"
        }

    def test_a_shop_with_no_map_reads_no_table_at_all(self):
        """The table costs nothing to parse, but a shop that has not said what
        its fields mean must not have them guessed at."""
        assert BigCommerceScraper.custom_field_map == ()
        assert BigCommerceScraper()._stated(dict(custom_fields(table(*MAUSER)))) == {}


class TestLegacyCollectibles:
    def test_the_three_columns_they_answer(self):
        assert LegacyCollectiblesScraper()._stated(custom_fields(table(*MAUSER))) == {
            "caliber": "7.63mm Mauser",
            "manufacturer": "Mauser",
            "condition": "9/10",
        }

    def test_the_maker_is_taken_from_the_field_not_from_the_text(self):
        """The measured reason this is a map and not a description.

        Their Magnum Research Desert Eagle is "Caliber: 9mm Luger", and fed to
        the classifier as prose that listing's manufacturer came back as
        **Luger**. Naming the field is the difference between using a vendor's
        data and guessing at it.
        """
        fields = custom_fields(
            table(
                ("Maker:", "Magnum Research"),
                ("Type:", "Desert Eagle"),
                ("Caliber:", "9mm Luger"),
            )
        )
        assert LegacyCollectiblesScraper()._stated(fields)["manufacturer"] == "Magnum Research"

    def test_the_bore_grade_is_kept_in_the_vendors_own_words(self):
        """The column is shown to a reader as "Bore condition", and "9/10" is
        a better answer there than a grade re-derived from it. It does mean
        this column now holds two vocabularies -- theirs and the seven grades
        `BORE_GRADES` produces -- which is worth knowing before it is filtered
        on."""
        assert LegacyCollectiblesScraper()._stated({"bore": "Like New"}) == {
            "condition": "Like New"
        }

    def test_the_model_is_deliberately_not_mapped(self):
        """There is no model column on a listing -- the armory works it out --
        so "Type" reaches it through the description instead."""
        mapped = dict(LegacyCollectiblesScraper.custom_field_map)
        assert "type" not in mapped


class TestTheDescriptionTheyDoNotWrite:
    """It is for the reader. Measured on forty of their listings, the
    synthesized description changes no classification, matches no additional
    armory model, and gains one country — the mapped fields do that work. What
    it carries that nothing else does is Year and Type.
    """

    def test_it_is_their_own_words_in_their_own_order(self):
        assert LegacyCollectiblesScraper().description_from(custom_fields(table(*MAUSER))) == (
            "Year: 1911-15. Maker: Mauser. Type: C96. Caliber: 7.63mm Mauser. "
            "Condition: ~94-95%."
        )

    def test_the_bore_is_not_repeated_into_it(self):
        """It is already on the row as the condition; repeating it only gives
        the bore grader something to re-derive."""
        assert "Bore" not in (
            LegacyCollectiblesScraper().description_from(custom_fields(table(*MAUSER))) or ""
        )

    def test_it_carries_the_two_facts_that_have_no_column(self):
        """Year and Type. Everything else in it is on the row as well, so this
        is the whole of what the description is for."""
        said = LegacyCollectiblesScraper().description_from(custom_fields(table(*MAUSER))) or ""
        assert "1911-15" in said
        assert "C96" in said

    def test_a_shorter_table_says_only_what_it_has(self):
        assert LegacyCollectiblesScraper().description_from({"maker": "DWM", "type": "P.08"}) == (
            "Maker: DWM. Type: P.08."
        )

    def test_and_no_table_writes_no_description(self):
        assert LegacyCollectiblesScraper().description_from({}) is None

    def test_the_base_class_writes_none_by_default(self):
        assert BigCommerceScraper().description_from({"maker": "Mauser"}) is None


class TestSold:
    """A sold listing says so on the product page and nowhere else.

    Its card in the grid looks exactly like an in-stock one, so this platform
    read every listing as available -- and Legacy Collectibles, who rename a
    sold listing "SOLD - ..." and go on showing it at its price, had a $1,095
    Winchester sitting in Available.

    Measured over 25 product pages across the three BigCommerce vendors, the
    two signals split cleanly: Legacy (15/15) and Bowman Arms (4/4) publish
    schema.org availability; Arms of America publish none (0/6) and show
    Stencil's banner instead.
    """

    def ld(self, availability):
        return BeautifulSoup(
            '<script type="application/ld+json">'
            '{"@type":"Product","offers":{"@type":"Offer","availability":'
            f'"https://schema.org/{availability}"}}}}</script><body></body>',
            "html.parser",
        )

    @pytest.mark.parametrize("state", ["OutOfStock", "SoldOut", "Discontinued"])
    def test_structured_data_that_says_it_cannot_be_bought(self, state):
        assert sold_out(self.ld(state)) is True

    def test_and_one_that_says_it_can(self):
        assert sold_out(self.ld("InStock")) is False

    @pytest.mark.parametrize("words", ["Out of stock", "Sold Out", "SOLD"])
    def test_the_stencil_banner(self, words):
        """Legacy Collectibles' says exactly "SOLD" and nothing else, which is
        why a bare "sold" counts — inside this element it can only be about
        this product."""
        soup = BeautifulSoup(
            '<div class="alertBox alertBox--error">'
            f'<p class="alertBox-message"><span>{words}</span></p></div>',
            "html.parser",
        )
        assert sold_out(soup) is True

    def test_a_page_that_says_neither_is_not_sold(self):
        """Silence is not "sold". Reading it that way would de-list a whole
        catalog the first time a theme dropped the field."""
        assert sold_out(BeautifulSoup("<div>A rifle.</div>", "html.parser")) is False

    def test_the_phrase_anywhere_else_on_the_page_does_not_count(self):
        """The trap, and it is a real page: Arms of America's PPSh-41 kit is in
        stock at $599.99 and carries "Out of stock" five times over — in the
        theme's JSON configuration, in the option list of a product whose
        *variants* differ in stock, and on every related-product card in the
        footer. Only the banner means this product.
        """
        soup = BeautifulSoup(
            '<script>{"out_of_stock_message":"Out of stock"}</script>'
            "<select><option>1943 - (Matching) - Out of stock</option></select>"
            '<div class="card"><a class="card-figcaption-button">Out of stock</a></div>',
            "html.parser",
        )
        assert sold_out(soup) is False

    def test_a_banner_about_something_else_does_not_count_either(self):
        assert (
            sold_out(
                BeautifulSoup(
                    '<div class="alertBox alertBox--error">'
                    "Please choose a product option.</div>",
                    "html.parser",
                )
            )
            is False
        )
