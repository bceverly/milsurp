"""Each vendor's mailing-list signup, and the card that shows it.

The notification account is subscribed to the shops' marketing email so the
inbox reader can hear about sales early. The Sites card links each shop's
signup page, green once mail from that shop has arrived and red until then.
The link is only useful if every shop has one, so declaring it is part of
adding a vendor, and these tests are where that is enforced.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from app.models import Site, utcnow
from app.scrapers import SCRAPER_CLASSES

#: Mailing services a vendor's signup page may live on instead of their own
#: domain. Adding one here is a deliberate act, like any other domain we send
#: an administrator to.
MAILING_SERVICES = ("list-manage.com", "constantcontact.com", "constantcontactpages.com")


def _registrable(host: str) -> str:
    return ".".join(host.lower().split(".")[-2:])


@pytest.mark.parametrize("scraper", SCRAPER_CLASSES, ids=lambda cls: cls.slug)
class TestEveryVendorDeclaresOne:
    def test_the_scraper_itself_says_so(self, scraper):
        """Declared on the class, not inherited from the base's None: a vendor
        added without anyone looking for a signup page must fail here."""
        assert "newsletter_url" in vars(scraper), (
            f"{scraper.__name__} does not declare newsletter_url. Find the "
            "shop's mailing-list signup (often a footer form on the home page) "
            "or set it to None with a newsletter_note saying none was found."
        )

    def test_a_missing_one_says_why(self, scraper):
        if scraper.newsletter_url is None:
            assert len(scraper.newsletter_note) > 10, scraper.slug

    def test_a_link_is_https_and_goes_to_the_vendor_or_their_mailing_service(self, scraper):
        url = scraper.newsletter_url
        if url is None:
            return
        parsed = urlparse(url)
        assert parsed.scheme == "https", scraper.slug
        vendor = _registrable(urlparse(scraper.base_url).hostname or "")
        host = parsed.hostname or ""
        assert _registrable(host) == vendor or host.endswith(MAILING_SERVICES), (
            scraper.slug,
            host,
        )


class TestTheSitesEndpoint:
    def _site(self, session, slug="sarco"):
        return session.query(Site).filter_by(slug=slug).one()

    def test_it_carries_the_link_and_how_to_use_it(self, client, admin_headers, session):
        site = self._site(session)
        body = client.get(f"/api/sites/{site.id}", headers=admin_headers).json()
        assert body["newsletter_url"] == "https://www.sarcoinc.com/"
        assert "footer" in body["newsletter_note"].lower()

    def test_nothing_received_is_null_until_the_inbox_says_otherwise(
        self, client, admin_headers, session
    ):
        site = self._site(session)
        body = client.get(f"/api/sites/{site.id}", headers=admin_headers).json()
        assert body["marketing_email_at"] is None

        site.marketing_email_at = utcnow()
        session.commit()
        body = client.get(f"/api/sites/{site.id}", headers=admin_headers).json()
        assert body["marketing_email_at"] is not None
