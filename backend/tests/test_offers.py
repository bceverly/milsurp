"""Reading an offer out of a vendor email's text.

The first cases are the shops' real wording from September 2026; the rest are
the sale wording the rules are written for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import offers

# A Saturday.
SENT = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)


def read(text, subject="News"):
    return offers.read(subject, text, SENT)


class TestTheShopsRealWording:
    def test_botach_s_welcome_code(self):
        found = read(
            "As promised, here's your 5% off code to use on your first order DQV8UU7PYS541 "
            "From firearms accessories to tactical gear",
            "Welcome to Botach — Here's 5% Off to Gear Up",
        )
        assert (found.discount, found.code, found.terms) == (
            "5% off",
            "DQV8UU7PYS541",
            "first order",
        )
        assert found.personal is True
        assert found.ends_at is None

    def test_centerfire_s_code_valid_for_30_days(self):
        found = read(
            "Use code the code below to secure $10 off your first purchase! CF6LZLK82H "
            "CODE VALID FOR 30 DAYS [Start Shopping](http://www.centerfiresystems.com)"
        )
        assert (found.discount, found.code) == ("$10 off", "CF6LZLK82H")
        assert found.ends_at == SENT + timedelta(days=30)

    def test_officer_store_s_free_shipping_code(self):
        found = read(
            "PROMOTION DETAILS: Use promo code: OSW2QQ550 for free shipping on orders $150+, "
            "in-stock only, exclusions apply.",
            "OfficerStore Welcome: Free Shipping $150+",
        )
        assert (found.discount, found.code) == ("free shipping", "OSW2QQ550")
        assert found.terms == "orders $150+; in-stock only"

    def test_ima_s_mixed_case_code(self):
        found = read("Use coupon code NS26-7f5b8t at checkout to save 5% off your next order")
        assert found.code == "NS26-7f5b8t"

    def test_aim_s_discount_with_no_code_in_the_email(self):
        found = read(
            "To receive your coupon code for 5% OFF your next purchase, please click the "
            "link below. 5% is off regular priced items only Get my discount code!"
        )
        assert (found.discount, found.code) == ("5% off", None)
        assert "regular priced items only" in found.terms

    def test_joe_salter_s_auction_endings_are_not_an_offer(self):
        assert (
            read(
                "Whitney Wolverine Semi-Auto 22 Pistol Built 1956 Minimum Bid: $1000.00 "
                "Ending Time: 9/26/2026 7:39 PM (https://joesalter.us3.list-manage.com/track/click?u=1)"
            )
            is None
        )

    def test_a_code_inside_a_link_is_not_a_code(self):
        found = read("5% off! Use code at https://shop.test/c?code=AB12CD34 today")
        assert found.code is None


class TestEndDates:
    @pytest.mark.parametrize(
        ("text", "day"),
        [
            ("15% off with code SURPLUS15 through 9/30", 30),
            ("Sale ends October 2! 10% off", 2),
            ("20% off everything until Sunday", 27),
            ("10% off, valid through 10/1/2026", 1),
        ],
    )
    def test_an_explicit_end(self, text, day):
        found = read(text)
        assert found.ends_at is not None
        # The end of that day in the US: read back in Eastern time, it is that
        # day (in UTC it is the early hours of the next).
        assert (found.ends_at - timedelta(hours=5)).day == day

    def test_hours_only(self):
        assert read("10% off, 72 hours only!").ends_at == SENT + timedelta(hours=72)

    def test_a_january_date_in_december_is_next_year(self):
        found = offers.read("News", "10% off through 1/5", datetime(2026, 12, 20, tzinfo=UTC))
        assert found.ends_at.year == 2027

    def test_vague_wording_leaves_no_end(self):
        assert read("10% off for a limited time!").ends_at is None


class TestWhatIsPersonal:
    def test_a_sale_for_everyone_is_not(self):
        assert read("Labor Day sale: 15% off with code LABOR15 through 9/7").personal is False

    def test_a_first_order_code_is(self):
        assert read("$10 off your first order with code FIRST10X").personal is True
