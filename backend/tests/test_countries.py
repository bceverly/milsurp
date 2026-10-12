class TestAbbreviationsAreCapitals:
    """ "Ship it back to us" filed a Taurus and a Zastava under United States
    (2026-10-12): the spelling "US" matched the pronoun."""

    def test_us_in_capitals_is_the_country_and_in_lower_case_is_not(self):
        from app.services.countries import _compile

        pattern = _compile(["United States", "US", "U.S.", "USA"])
        assert pattern.search("US M1 Carbine")
        assert pattern.search("Made in USA")
        assert pattern.search("united states property")
        assert not pattern.search("we will arrange shipment back to us")
