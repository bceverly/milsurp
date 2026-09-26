"""Following a vendor email's links to the shop's pages.

Link shapes are the real ones from the shops' first mail in September 2026:
Klaviyo, Listrak on the shop's own domain, SendGrid into Privy, Constant
Contact, Mailchimp's encoded payload and its short links.
"""

from __future__ import annotations

import base64
import io
import json

import pytest
import requests

from app.services import maillinks

UA = "Mozilla/5.0 (compatible; MilsurpMonitor/1.0; +https://milsurpmonitor.com)"


class Redirects:
    """A stand-in for requests.get over a fixed set of redirects."""

    def __init__(self, hops):
        self.hops = hops
        self.asked = []

    def __call__(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False, "a redirect must be read, never followed"
        self.asked.append(url)
        if url not in self.hops:
            raise AssertionError(f"requested something that is not a tracker: {url}")
        response = requests.Response()
        response.raw = io.BytesIO(b"")
        response.status_code = 302
        response.headers["Location"] = self.hops[url]
        return response


def mailchimp(target):
    inner = json.dumps({"u": 1, "v": 2, "url": target})
    outer = json.dumps({"s": "x", "v": 2, "p": inner})
    payload = base64.urlsafe_b64encode(outer.encode()).decode().rstrip("=")
    return f"https://click.mailchimp.com/track/click/30010842/shop.list-manage.com?p={payload}"


class TestWhichLinksAreRead:
    EMAIL = """
    <a href="https://ctrk.klclick1.com/l/A_0"><img alt="Classic Firearms"></a>
    <a href="https://ctrk.klclick1.com/l/A_11"><img alt="Image of Winchester 12 Ga"></a>
    <a href="https://ctrk.klclick1.com/l/A_12">Shop now</a>
    <a href="https://ctrk.klclick1.com/l/A_12">Shop now</a>
    <a href="https://ctrk.klclick1.com/l/A_33"><img alt="instagram"></a>
    <a href="https://ctrk.klclick1.com/l/A_35">PRIVACY POLICY</a>
    <a href="http://hub.classicfirearms.com/p/preference_center">Unsubscribe</a>
    <a href="https://ctrk.klclick1.com/l/A_40">View Email in Browser</a>
    <a href="https://manage.kmail-lists.com/subscriptions/unsubscribe?a=1">here</a>
    <a href="mailto:sales@officerstore.com">sales@officerstore.com</a>
    <a href="tel:6108578070">610-857-8070</a>
    <a href="#">Forward to a Friend</a>
    """

    def test_the_news_is_kept_and_the_footer_is_not(self):
        found = maillinks.html_of(self.EMAIL)
        assert [link.url for link in found] == [
            "https://ctrk.klclick1.com/l/A_0",
            "https://ctrk.klclick1.com/l/A_11",
            "https://ctrk.klclick1.com/l/A_12",
        ]

    def test_a_product_link_keeps_its_image_alt_as_its_text(self):
        found = maillinks.html_of(self.EMAIL)
        assert found[1].text == "Image of Winchester 12 Ga"


class TestWhereALinkLeads:
    def test_a_link_already_on_the_shop_needs_no_request(self):
        get = Redirects({})
        url, how = maillinks.destination(
            "https://aimsurplus.com/pages/discount?utm_source=email",
            "aimsurplus.com",
            get=get,
            user_agent=UA,
        )
        assert (url, how) == ("https://aimsurplus.com/pages/discount", "direct")
        assert get.asked == []

    def test_mailchimp_is_decoded_without_a_request(self):
        get = Redirects({})
        url, how = maillinks.destination(
            mailchimp("https://shop.joesalter.com/New-Arrivals"),
            "joesalter.com",
            get=get,
            user_agent=UA,
        )
        assert (url, how) == ("https://shop.joesalter.com/New-Arrivals", "decoded")
        assert get.asked == []

    def test_a_mailchimp_unsubscribe_is_recognized_after_decoding(self):
        """The first decoded Mailchimp link measured was exactly this."""
        url, how = maillinks.destination(
            mailchimp("https://joesalter.us3.list-manage.com/unsubscribe?u=1&id=2"),
            "joesalter.com",
            get=Redirects({}),
            user_agent=UA,
        )
        assert (url, how) == (None, "subscription")

    def test_klaviyo_is_resolved_with_one_request(self):
        get = Redirects(
            {
                "https://ctrk.klclick1.com/l/A_12": (
                    "https://www.classicfirearms.com/rebate-and-promotions/"
                    "?utm_source=Klaviyo&utm_medium=email"
                )
            }
        )
        url, how = maillinks.destination(
            "https://ctrk.klclick1.com/l/A_12", "classicfirearms.com", get=get, user_agent=UA
        )
        assert url == "https://www.classicfirearms.com/rebate-and-promotions/"
        assert how == "resolved"
        assert len(get.asked) == 1

    def test_a_tracker_on_the_shop_s_own_domain_is_still_a_tracker(self):
        """Listrak runs link.botach.com: the shop's domain, not the shop's page.
        Taken as a shop page, thirty Botach links were counted as followed
        without one being resolved."""
        get = Redirects(
            {"https://link.botach.com/q/HGv": "https://botach.com/trading-post/?trk_msg=S0Q"}
        )
        url, how = maillinks.destination(
            "https://link.botach.com/q/HGv", "botach.com", get=get, user_agent=UA
        )
        assert (url, how) == ("https://botach.com/trading-post/", "resolved")

    def test_sendgrid_into_privy_is_decoded_on_the_second_hop(self):
        privy = (
            "https://r1.privy.com/link_v2?original_uri="
            "https%3A%2F%2Fwww.clydearmory.com%2F%3Futm_campaign%3Dprivy_4599925"
        )
        get = Redirects({"https://u6948458.ct.sendgrid.net/ls/click?upn=u001.EZK": privy})
        url, _how = maillinks.destination(
            "https://u6948458.ct.sendgrid.net/ls/click?upn=u001.EZK",
            "clydearmory.com",
            get=get,
            user_agent=UA,
        )
        assert url == "https://www.clydearmory.com/"
        assert len(get.asked) == 1  # Privy was decoded, not asked

    def test_a_chain_ending_off_the_shop_stops_without_asking_it(self):
        """Joe Salter's auction links end at GunBroker. That page is not a
        tracker and not the shop, so it is never requested."""
        get = Redirects(
            {
                "https://us.list-manage.com/jTMs": (
                    "https://joesalter.us3.list-manage.com/track/click?u=1&id=2"
                ),
                "https://joesalter.us3.list-manage.com/track/click?u=1&id=2": (
                    "https://www.gunbroker.com/All/search?IncludeSellers=995775"
                ),
            }
        )
        url, how = maillinks.destination(
            "https://us.list-manage.com/jTMs", "joesalter.com", get=get, user_agent=UA
        )
        assert (url, how) == (None, "offsite")
        assert not any("gunbroker" in asked for asked in get.asked)

    def test_a_third_party_link_is_not_requested_at_all(self):
        get = Redirects({})
        assert maillinks.destination(
            "https://www.credova.com/disclaimers", "classicfirearms.com", get=get, user_agent=UA
        ) == (None, "offsite")
        assert get.asked == []

    def test_a_tracker_that_will_not_answer(self):
        def down(_url, **_kwargs):
            raise requests.ConnectionError("nope")

        assert maillinks.destination(
            "https://ctrk.klclick1.com/l/A_1", "classicfirearms.com", get=down, user_agent=UA
        ) == (None, "failed")

    def test_a_loop_of_trackers_gives_up(self):
        get = Redirects(
            {
                "https://ctrk.klclick1.com/l/1": "https://ctrk.klclick1.com/l/2",
                "https://ctrk.klclick1.com/l/2": "https://ctrk.klclick1.com/l/3",
                "https://ctrk.klclick1.com/l/3": "https://ctrk.klclick1.com/l/4",
            }
        )
        assert maillinks.destination(
            "https://ctrk.klclick1.com/l/1", "classicfirearms.com", get=get, user_agent=UA
        ) == (None, "offsite")
        assert len(get.asked) == maillinks.MAX_HOPS


class TestMatchingAListing:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            (
                "https://www.classicfirearms.com/m96-swedish-mauser/",
                "https://classicfirearms.com/m96-swedish-mauser?utm_source=Klaviyo",
            ),
            ("https://botach.com/x?trk_msg=1&id=5", "https://BOTACH.com/x?id=5"),
        ],
    )
    def test_the_same_listing_however_the_email_spelled_it(self, a, b):
        assert maillinks.normalized(a) == maillinks.normalized(b)

    def test_without_its_query_as_a_fallback(self):
        """A tracker can add a parameter the listing's own address never had."""
        assert maillinks.normalized(
            "https://www.apexgunparts.com/p/1?cid=1eHD", query=False
        ) == maillinks.normalized("https://www.apexgunparts.com/p/1", query=False)
