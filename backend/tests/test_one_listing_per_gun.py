"""One listing per gun, when a product page sells several (app.scrapers.choices).

Asked for on 2026-10-10, with grade tiers ("Good $279.99 / Fair $259.99") split
the same way, and each choice sold or for sale on its own -- a page mixes the
two. The rule came out of a survey of every shop; see ROADMAP.md, "One listing
per gun when a product page sells several".
"""

from __future__ import annotations

import contextlib
import gzip
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from recordings import load, replaying

from app.scrapers import ScrapeCanceled, get_scraper
from app.scrapers.base import ScrapedItem
from app.scrapers.choices import Choice, split, splits, with_numbered_photos
from app.scrapers.classic_firearms import ClassicFirearmsScraper
from app.scrapers.magento import custom_option_choices
from app.scrapers.woocommerce import page_choices

PAGES = Path(__file__).parent / "fixtures" / "choices"


def page(name: str) -> str:
    return gzip.decompress((PAGES / name).read_bytes()).decode("utf-8")


def choices(*labels, prices=None, pictures=None):
    return [
        Choice(
            key=str(n),
            label=label,
            price=(prices or {}).get(label, 100.0),
            image_urls=[(pictures or {})[label]] if label in (pictures or {}) else [],
        )
        for n, label in enumerate(labels)
    ]


class TestWhenTheChoicesAreSeparateGuns:
    @pytest.mark.parametrize(
        ("names", "labels"),
        [
            (["Condition"], ["Good", "Fair"]),
            (["Condition"], ["Radom P-83 Pistol - 1", "Radom P-83 Pistol - 2"]),
            (["Rifle Selection"], ["1", "2", "3"]),
            (["Choose Your Firearm"], ["1 - Phoenix Arms HP22B", "2 - Smith & Wesson M&P 40"]),
            (["Type"], ["Blem", "Non Blem"]),
        ],
    )
    def test_numbered_or_graded_choices_are_guns(self, names, labels):
        assert splits(names, choices(*labels))

    def test_differently_priced_makers_are_guns(self):
        lugers = choices(
            "Mauser 1942", "Erfurt 1917", prices={"Mauser 1942": 4999.99, "Erfurt 1917": 2500.0}
        )
        assert splits(["P08 Variations"], lugers)

    @pytest.mark.parametrize(
        ("names", "labels"),
        [
            # IMA: a service on the same gun, not a choice of gun.
            (["Hand Select"], ["No", "Yes"]),
            (["Certificate of Authenticity"], ["None", "Signed & Laminated"]),
            (["Magazine Size"], ["5 Round Magazine", "20 Round Magazine"]),
            # J & G: a preference over a pick the shop makes.
            (["Stock Pattern"], ["No Preference", "Scant Grip", "Straight Grip"]),
        ],
    )
    def test_services_accessories_and_preferences_are_not(self, names, labels):
        prices = {label: 100.0 + n for n, label in enumerate(labels)}
        assert not splits(names, choices(*labels, prices=prices))

    def test_a_new_gun_in_colors_at_one_price_is_one_product(self):
        assert not splits(["Color"], choices("Black", "FDE"))

    def test_but_surplus_finishes_priced_apart_are_two_guns(self):
        priced = choices("Blued", "Chrome", prices={"Blued": 299.99, "Chrome": 329.99})
        assert splits(["Finish"], priced)

    def test_one_choice_is_the_page_itself(self):
        assert not splits(["Condition"], choices("Good"))


class TestTheListingsTheyBecome:
    parent = ScrapedItem(
        external_key="woo-133181",
        url="https://shop.test/p83",
        title="Polish Radom P-83 Pistol \u2013 9MM Makarov",
        price=379.99,
        image_urls=["https://shop.test/all.jpg"],
    )

    def test_each_has_its_own_key_price_stock_and_parent(self):
        made = split(
            self.parent,
            [
                Choice(key="1", label="Radom P-83 Pistol \u2013 1", price=399.99, is_sold=True),
                Choice(key="2", label="Radom P-83 Pistol \u2013 2", price=379.99),
            ],
        )
        assert [(m.external_key, m.price, m.is_sold, m.split_from) for m in made] == [
            ("woo-133181#1", 399.99, True, "woo-133181"),
            ("woo-133181#2", 379.99, False, "woo-133181"),
        ]

    def test_a_count_on_the_products_own_name_becomes_a_number(self):
        [made] = split(self.parent, [Choice(key="20", label="Radom P-83 Pistol \u2013 20")])
        assert made.title == "Polish Radom P-83 Pistol \u2013 9MM Makarov #20"

    def test_a_grade_is_appended(self):
        [made] = split(self.parent, [Choice(key="g", label="Very Good")])
        assert made.title.endswith(" - Very Good")

    def test_a_choice_with_no_picture_shows_the_pages(self):
        [made] = split(self.parent, [Choice(key="g", label="Good")])
        assert made.image_urls == ["https://shop.test/all.jpg"]


def scan_of(slug, ctx_factory):
    found: list = []
    with contextlib.suppress(ScrapeCanceled):
        found.extend(get_scraper(slug).scrape(replaying(ctx_factory(), load(slug))))
    return found


class TestMokasRaifus:
    """WooCommerce variations, read through the Store API the scraper reads."""

    def test_each_pistol_is_a_listing_sold_or_not_on_its_own(self, ctx_factory):
        items = scan_of("mokas-raifus", ctx_factory)
        p83 = [i for i in items if i.split_from == "woo-133181"]
        assert len(p83) == 20
        assert {i.is_sold for i in p83} == {True, False}
        assert all(len(i.image_urls) == 1 for i in p83)
        assert "woo-133181" not in {i.external_key for i in items}


class TestCoGunSales:
    """WooCommerce variations, read off the product page."""

    def test_lugers_by_maker_and_year(self):
        soup = BeautifulSoup(page("co-gun-sales-lugers.html.gz"), "html.parser")
        names, found = page_choices(soup, "https://cogunsales.com/")
        assert names == ["P08 Variations"]
        assert splits(names, found)
        by_label = {c.label: c for c in found}
        assert by_label["Mauser 1942"].price == 4999.99
        assert by_label["Mauser 1942"].is_sold
        assert not by_label["DWM 1913"].is_sold
        assert by_label["DWM 1913"].description.startswith(
            "This Luger P08 was manufactured in 1913"
        )

    def test_numbered_pistols(self):
        soup = BeautifulSoup(page("co-gun-sales-mas50.html.gz"), "html.parser")
        names, found = page_choices(soup, "https://cogunsales.com/")
        assert (names, len(found)) == (["Number"], 7)
        assert splits(names, found)


class FakeContext:
    def __init__(self, text):
        self.text = text

    def needs_detail(self, _key):
        return True

    def get_text(self, _url, **_kwargs):
        return self.text

    def log(self, _message):
        pass

    def warn(self, message):  # pragma: no cover - a failure if reached
        raise AssertionError(message)


class TestClassicGrabBag:
    """Magento 1 custom options: twenty unrelated handguns listed at "$10"."""

    URL = (
        "https://www.classicfirearms.com/gunsmith-special-handgun-various-manufacturers-and-models/"
    )

    def test_twenty_guns_each_with_its_price_photo_and_stock(self):
        parent = ScrapedItem(
            external_key="gunsmith-special-handgun",
            url=self.URL,
            title="Gunsmith Special Handguns Various Manufacturers and Models",
            price=10.0,
        )
        made = list(
            ClassicFirearmsScraper()._detailed(
                FakeContext(page("classic-gunsmith-handguns.html.gz")), parent
            )
        )
        assert len(made) == 20
        first = made[0]
        assert first.title.startswith("Phoenix Arms HP22B Pistol, 22LR")
        assert first.price == 119.99
        assert first.is_sold
        assert [u.rsplit("/", 1)[-1] for u in first.image_urls] == ["hg1_2.png"]
        assert sum(not m.is_sold for m in made) == 11
        assert 10.0 not in {m.price for m in made}

    def test_a_page_with_no_options_has_no_choices(self):
        soup = BeautifulSoup("<html><body>one gun</body></html>", "html.parser")
        assert custom_option_choices("<html></html>", soup) == ([], [])


class TestPhotographsByNumber:
    def test_a_numbered_choice_takes_its_photograph(self):
        urls = ["https://x.test/media/hg1_2.png", "https://x.test/media/hg10_2.png"]
        found = with_numbered_photos(
            [Choice(key="a", label="1 - A gun"), Choice(key="b", label="10 - Another")], urls
        )
        assert [c.image_urls for c in found] == [[urls[0]], [urls[1]]]


class TestCenterfire:
    """Shopify variants: "Condition: Good / Fair", each in stock or not."""

    def test_condition_tiers_are_listings_with_their_own_stock(self, ctx_factory):
        items = scan_of("centerfire-systems", ctx_factory)
        m1935 = sorted(
            (i.title.rsplit(" - ", 1)[-1], i.price, i.is_sold)
            for i in items
            if i.split_from == "shopify-10335809569090"
        )
        assert m1935 == [
            ("Early Production", 339.99, True),
            ("Fair", 299.99, False),
            ("Good", 329.99, True),
        ]

    def test_ima_hand_select_stays_one_listing(self, ctx_factory):
        assert not [i for i in scan_of("ima-usa", ctx_factory) if i.split_from]


class TestBigCommerce:
    """A Stencil page names its choices; what each costs and whether it is in
    stock come from the shop's own ``/remote/v1/product-attributes`` endpoint,
    asked once per choice as the page would ask it."""

    P226 = "https://www.recoilgunworks.com/pd-trade-sig-sauer-p226-9mm-da-sa-night-sights/"

    def recorded_page(self):
        recording = load("recoil-gun-works")
        return recording.text(self.P226)

    def test_the_menu_is_read_off_the_page(self):
        from app.scrapers.bigcommerce import page_options

        options = page_options(BeautifulSoup(self.recorded_page(), "html.parser"))
        assert options.product_id == "822"
        assert options.field == "attribute[364]"
        assert options.names == ["Condition"]
        assert [c.label for c in options.choices][:3] == ["Unissued", "Excellent", "Very Good"]

    def test_each_grade_is_priced_and_stocked_on_its_own(self):
        from app.scrapers.recoil_gun_works import RecoilGunWorksScraper

        answers = {
            "574": (699.99, False),
            "592": (599.99, True),
            "311": (529.99, True),
            "312": (499.99, False),
            "313": (479.99, True),
        }
        asked = []

        class Ctx(FakeContext):
            def post(self, url, data, **_kwargs):
                asked.append((url, data["attribute[364]"]))
                price, instock = answers[data["attribute[364]"]]

                class Answer:
                    def json(self):
                        return {
                            "data": {
                                "price": {"without_tax": {"value": price}},
                                "instock": instock,
                                "purchasable": True,
                                "image": {"data": f"https://cdn.test/{{:size}}/{price}.jpg"},
                            }
                        }

                return Answer()

        parent = ScrapedItem(external_key="822", url=self.P226, title="PD Trade | Sig P226")
        made = list(RecoilGunWorksScraper()._detailed(Ctx(self.recorded_page()), parent))
        assert {url for url, _ in asked} == {
            "https://www.recoilgunworks.com/remote/v1/product-attributes/822"
        }
        assert [(m.title.rsplit(" - ", 1)[-1], m.price, m.is_sold) for m in made] == [
            ("Unissued", 699.99, True),
            ("Excellent", 599.99, False),
            ("Very Good", 529.99, False),
            ("Good", 499.99, True),
            ("Fair", 479.99, False),
        ]
        assert made[0].image_urls == ["https://cdn.test/original/699.99.jpg"]

    def test_an_add_on_menu_is_not_even_priced(self):
        from app.scrapers.bigcommerce import PageOptions, _ruled_out

        certificate = PageOptions(
            "1",
            "attribute[9]",
            ["Certificate of Authenticity"],
            [Choice(key="1", label="None"), Choice(key="2", label="Signed & Laminated")],
        )
        assert _ruled_out(certificate)

    def test_a_refused_price_leaves_the_page_whole(self):
        from app.scrapers.base import ScrapeError
        from app.scrapers.recoil_gun_works import RecoilGunWorksScraper

        class Ctx(FakeContext):
            def post(self, url, **_kwargs):
                raise ScrapeError(f"POST {url}: refused")

        parent = ScrapedItem(external_key="822", url=self.P226, title="PD Trade | Sig P226")
        [made] = list(RecoilGunWorksScraper()._detailed(Ctx(self.recorded_page()), parent))
        assert made.external_key == "822"
