"""A stored description has to be prose, not the code that surrounded it.

Every platform here receives a description as HTML and flattens it the same
way, and every one of them had the same hole: ``get_text()`` returns the text
inside a ``<style>`` or ``<script>`` element like any other text. On a Magento
Page Builder shop the description *opens* with a stylesheet, so 75 of Apex Gun
Parts' 93 listings were stored with

    #html-body [data-pb-style=TWCLXS0]{justify-content:flex-start;display:flex;…

where their description should be. One shared helper answers it for all of
them; these hold it to that, and to the two things it must not do.
"""

from __future__ import annotations

import argparse

import cli
import pytest
from bs4 import BeautifulSoup

from app.models import Item, Site
from app.scrapers.base import flatten_html, text_of

PAGE_BUILDER = (
    "<style>#html-body [data-pb-style=TWCLXS0]{justify-content:flex-start;"
    "display:flex;flex-direction:column}</style>"
    "<div data-content-type='text'><p>CETME Model C parts kit, 7.62 NATO.</p></div>"
)


class TestWhatIsDropped:
    def test_a_page_builder_stylesheet_is_not_the_description(self):
        assert flatten_html(PAGE_BUILDER) == "CETME Model C parts kit, 7.62 NATO."

    @pytest.mark.parametrize("tag", ["style", "script", "noscript", "template"])
    def test_nor_is_anything_else_that_is_code(self, tag):
        markup = f"<{tag}>var x = 1;</{tag}><p>An original rifle.</p>"
        assert flatten_html(markup) == "An original rifle."

    def test_the_prose_around_it_is_kept_in_order(self):
        markup = "<p>Before.</p><style>a{color:red}</style><p>After.</p>"
        assert flatten_html(markup) == "Before. After."


class TestWhatIsKept:
    """The two ways a fix like this goes wrong: eating text that was never
    markup, and mistaking prose for it."""

    def test_an_ampersand_survives(self):
        assert flatten_html("<p>Bolt &amp; carrier</p>") == "Bolt & carrier"

    def test_and_so_does_a_less_than_sign_in_prose(self):
        """ "Bore diameter < 7.63mm" is not a tag and must not be treated as
        one -- the second flattening pass is guarded on something that really
        looks like markup."""
        assert flatten_html("<p>Bore &lt; 7.63mm and headspaced</p>") == (
            "Bore < 7.63mm and headspaced"
        )

    @pytest.mark.parametrize("markup", [None, "", "   ", "<p></p>"])
    def test_nothing_in_is_nothing_out(self, markup):
        assert flatten_html(markup) == ""


class TestMarkupEscapedTwice:
    """Classic Firearms have one description ending
    ``&amp;nbsp;&lt;/span&gt;&lt;/p&gt;``. Decoding that once leaves literal
    ``</span></p>`` as *text*, which is not markup any more and so was stored.
    """

    def test_a_second_pass_finishes_it(self):
        assert flatten_html(
            "<p>No collection is complete.&amp;nbsp;&lt;/span&gt;&lt;/p&gt;</p>"
        ) == ("No collection is complete.")

    def test_but_only_a_second(self):
        """Two passes, not "until it stops changing" -- a description that
        talks about markup should survive being read."""
        assert "&lt;" not in flatten_html("<p>Escaped: &amp;amp;lt;p&amp;amp;gt;</p>")


class TestTextOf:
    def test_it_leaves_the_tree_it_was_given_alone(self):
        """A scraper reads the same node more than once -- a price, then a
        description. A helper that quietly empties the tree it was handed is a
        trap for whatever runs next."""
        soup = BeautifulSoup("<div><style>a{color:red}</style><p>Rifle</p></div>", "html.parser")
        node = soup.select_one("div")

        assert text_of(node) == "Rifle"
        assert soup.select_one("style") is not None


class TestFindingTheOnesAlreadyStored:
    """The fix cannot reach a listing whose product page has already been
    fetched, because a scan skips those. `refetch-details` clears that mark.
    """

    @pytest.fixture
    def shop(self, session, request):
        # The command commits, so a site row outlives the session fixture's
        # rollback and a fixed slug collides with the next test in the class.
        slug = f"prose-{request.node.name}"[:60]
        site = Site(
            slug=slug,
            name="Prose Test",
            base_url="https://prose.example/",
            description="A test double.",
        )
        session.add(site)
        session.flush()
        return site

    def item(self, session, site, key, description):
        from app.models import utcnow

        row = Item(
            site_id=site.id,
            external_key=key,
            url=f"https://prose.example/{key}",
            title=key,
            description=description,
            detail_fetched_at=utcnow(),
        )
        session.add(row)
        session.flush()
        return row

    def run(self, monkeypatch, session, **kwargs):
        import contextlib

        @contextlib.contextmanager
        def scope():
            yield session

        monkeypatch.setattr(cli, "session_scope", scope)
        args = argparse.Namespace(site=None, all=False, dry_run=False, **kwargs)
        return cli.cmd_refetch_details(args)

    def test_a_leaked_stylesheet_is_found(self, monkeypatch, session, shop):
        bad = self.item(session, shop, "bad", "#html-body [data-pb-style=X]{display:flex;")
        good = self.item(session, shop, "good", "An original CETME parts kit.")

        assert self.run(monkeypatch, session) == 0
        assert bad.detail_fetched_at is None
        assert good.detail_fetched_at is not None

    def test_so_are_tags_that_survived(self, monkeypatch, session, shop):
        bad = self.item(session, shop, "tags", "No collection is complete.</span></p>")

        self.run(monkeypatch, session)
        assert bad.detail_fetched_at is None

    def test_prose_is_left_alone(self, monkeypatch, session, shop):
        """Including prose that mentions a price, a caliber and a comma --
        the pattern looks for a CSS declaration, not for punctuation."""
        good = self.item(
            session, shop, "prose", "Bore: excellent; stock: good. 7.62x54R, matching numbers."
        )

        self.run(monkeypatch, session)
        assert good.detail_fetched_at is not None

    @pytest.mark.parametrize("description", [None, ""])
    def test_a_listing_with_no_description_is_not_damaged(
        self, monkeypatch, session, shop, description
    ):
        """is_prose() answers "is this text worth keeping", so it says False
        for an empty description as well as for a stylesheet. Reading that as
        "needs re-fetching" queued 264 undamaged listings for a product-page
        read they did not need -- a shop's bandwidth, spent on nothing."""
        empty = self.item(session, shop, f"empty-{description!r}", description)

        self.run(monkeypatch, session)
        assert empty.detail_fetched_at is not None

    def test_a_dry_run_reports_and_changes_nothing(self, monkeypatch, session, shop):
        bad = self.item(session, shop, "dry", "#html-body [data-pb-style=X]{display:flex;")

        args = argparse.Namespace(site=None, all=False, dry_run=True)
        import contextlib

        @contextlib.contextmanager
        def scope():
            yield session

        monkeypatch.setattr(cli, "session_scope", scope)
        assert cli.cmd_refetch_details(args) == 0
        assert bad.detail_fetched_at is not None

    def test_an_unknown_site_is_an_error_rather_than_a_silent_no_op(
        self, monkeypatch, session, shop
    ):
        import contextlib

        @contextlib.contextmanager
        def scope():
            yield session

        monkeypatch.setattr(cli, "session_scope", scope)
        args = argparse.Namespace(site="not-a-shop", all=False, dry_run=False)
        assert cli.cmd_refetch_details(args) == 1
