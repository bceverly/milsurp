"""The wishlist: each gun priced to the door, set against its worth, and added up.

The transfer fee is waived only for a C&R-eligible gun bought by a reader who
holds the license; an unknown status is charged. A missing shipping figure
makes a total "at least", never free. The worth leaves the listing itself out
of its own yardstick, and a gun no longer for sale stays on the list but out of
the totals.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import (
    CollectionItem,
    EmailPreference,
    FirearmModel,
    Item,
    Site,
    User,
    UserRole,
    WishlistItem,
    utcnow,
)
from app.scheduler import Scheduler
from app.security import hash_password
from app.services import digest, pushnotify, watchpoll, wishlist
from app.services.watchlist import News


@pytest.fixture
def world(clean_db):
    shop = Site(slug="w1", name="Shop W", base_url="https://w1.test/", shipping_long_gun=30.0)
    bare = Site(slug="w2", name="Shop X", base_url="https://w2.test/")
    k31 = FirearmModel(name="Swiss K31")
    reader = User(
        username="buyer",
        email="buyer@example.com",
        password_hash=hash_password("buyer-long-passphrase"),
        role=UserRole.NORMAL,
        ffl_transfer_fee=25.0,
    )
    clean_db.add_all([shop, bare, k31, reader])
    clean_db.commit()
    return clean_db, shop, bare, k31, reader


def _gun(session, site, key, price, *, model=None, **kwargs):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"{site.base_url}{key}",
        title=kwargs.pop("title", "Swiss K31 carbine"),
        current_price=None if price is None else float(price),
        is_rifle=kwargs.pop("is_rifle", True),
        first_seen_at=utcnow() - timedelta(days=10),
        firearm_model_id=model.id if model else None,
        **kwargs,
    )
    session.add(item)
    session.flush()
    return item


def _market(session, site, model, prices):
    for index, price in enumerate(prices):
        _gun(session, site, f"m{index}", price, model=model)


class TestLines:
    def test_price_shipping_and_fee_make_the_total(self, world):
        session, shop, _bare, k31, reader = world
        item = _gun(session, shop, "a", 500, model=k31, cr_stated=False)
        wishlist.add(session, reader, item)
        session.commit()
        line = wishlist.build(session, reader).lines[0]
        assert (line.price, line.shipping, line.fee, line.total) == (500, 30, 25, 555)
        assert line.complete and not line.fee_waived

    def test_a_cr_holder_pays_no_fee_on_an_eligible_gun(self, world):
        session, shop, _bare, k31, reader = world
        reader.has_cr_license = True
        old = _gun(session, shop, "old", 500, model=k31, manufacture_year=1940)
        new = _gun(session, shop, "new", 500, model=k31, cr_stated=False)
        unknown = _gun(session, shop, "unk", 500, model=k31)
        for item in (old, new, unknown):
            wishlist.add(session, reader, item)
        session.commit()
        lines = {line.item.external_key: line for line in wishlist.build(session, reader).lines}
        assert (lines["old"].fee, lines["old"].fee_waived, lines["old"].total) == (None, True, 530)
        assert lines["new"].fee == 25
        # Unknown is charged: guessing in the reader's favor is how a budget comes up short.
        assert (lines["unk"].curio, lines["unk"].fee) == ("unknown", 25)

    def test_without_the_license_an_eligible_gun_is_charged(self, world):
        session, shop, _bare, k31, reader = world
        item = _gun(session, shop, "old", 500, model=k31, manufacture_year=1940)
        wishlist.add(session, reader, item)
        session.commit()
        assert wishlist.build(session, reader).lines[0].fee == 25

    def test_missing_shipping_or_fee_makes_it_at_least(self, world):
        session, _shop, bare, k31, reader = world
        reader.ffl_transfer_fee = None
        item = _gun(session, bare, "a", 500, model=k31)
        wishlist.add(session, reader, item)
        session.commit()
        line = wishlist.build(session, reader).lines[0]
        assert (line.total, line.complete, line.fee_missing) == (500, False, True)
        totals = wishlist.build(session, reader).totals
        assert (totals.cost, totals.cost_complete) == (500, False)

    def test_worth_and_profit_leave_the_listing_out(self, world):
        session, shop, bare, k31, reader = world
        _market(session, bare, k31, [600, 600, 600, 600, 600])
        item = _gun(session, shop, "a", 100, model=k31, cr_stated=False)
        wishlist.add(session, reader, item)
        session.commit()
        line = wishlist.build(session, reader).lines[0]
        assert line.valuation is not None and line.valuation.estimate == 600
        assert line.profit == 600 - 155

    def test_a_model_the_market_cannot_price_has_no_profit(self, world):
        session, shop, _bare, k31, reader = world
        item = _gun(session, shop, "a", 500, model=k31)
        wishlist.add(session, reader, item)
        session.commit()
        line = wishlist.build(session, reader).lines[0]
        assert (line.valuation, line.profit) == (None, None)


class TestTotals:
    def test_grand_totals_and_the_gone_left_out(self, world):
        session, shop, bare, k31, reader = world
        _market(session, bare, k31, [600] * 5)
        one = _gun(session, shop, "a", 500, model=k31, cr_stated=False)
        two = _gun(session, shop, "b", 400, model=k31, cr_stated=False)
        gone = _gun(session, shop, "c", 300, model=k31, is_active=False, is_sold=True)
        unpriced = _gun(session, shop, "d", None, model=k31)
        lonely = _gun(session, shop, "e", 200, title="Odd rifle", cr_stated=False)
        for item in (one, two, gone, unpriced, lonely):
            wishlist.add(session, reader, item)
        session.commit()
        totals = wishlist.build(session, reader).totals
        assert (totals.count, totals.for_sale, totals.unpriced) == (5, 4, 1)
        assert totals.cost == 555 + 455 + 255
        assert (totals.value, totals.valued) == (1200, 2)
        assert (totals.compared, totals.compared_cost) == (2, 1010)
        assert totals.profit == 1200 - 1010


class TestMembership:
    def test_add_is_idempotent_and_remove_says_whether(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        first = wishlist.add(session, reader, item)
        assert wishlist.add(session, reader, item).id == first.id
        session.commit()
        assert wishlist.on_wishlist(session, reader, item.id)
        assert wishlist.remove(session, reader, item.id)
        assert not wishlist.remove(session, reader, item.id)
        session.commit()
        assert session.query(WishlistItem).count() == 0


class TestApi:
    def _item(self, clean_db):
        site = Site(slug="api", name="Shop API", base_url="https://api.test/")
        clean_db.add(site)
        clean_db.flush()
        item = _gun(clean_db, site, "x", 450)
        clean_db.commit()
        return item.id

    def test_add_list_flag_and_remove(self, client, normal_user, clean_db):
        headers = normal_user["headers"]
        item_id = self._item(clean_db)
        assert client.put(f"/api/wishlist/{item_id}", headers=headers).status_code == 204
        assert client.put(f"/api/wishlist/{item_id}", headers=headers).status_code == 204
        body = client.get("/api/wishlist", headers=headers).json()
        assert [line["item"]["id"] for line in body["lines"]] == [item_id]
        assert body["lines"][0]["total"] == 450
        assert body["totals"]["count"] == 1
        assert client.get(f"/api/items/{item_id}", headers=headers).json()["wishlisted"] is True
        assert client.delete(f"/api/wishlist/{item_id}", headers=headers).status_code == 204
        assert client.get("/api/wishlist", headers=headers).json()["lines"] == []
        assert client.get(f"/api/items/{item_id}", headers=headers).json()["wishlisted"] is False

    def test_a_missing_listing_is_404(self, client, normal_user):
        assert client.put("/api/wishlist/999999", headers=normal_user["headers"]).status_code == 404

    def test_another_readers_list_is_not_yours(self, client, normal_user, admin_headers, clean_db):
        item_id = self._item(clean_db)
        client.put(f"/api/wishlist/{item_id}", headers=admin_headers)
        assert client.get("/api/wishlist", headers=normal_user["headers"]).json()["lines"] == []

    def test_the_license_is_saved_and_left_alone_when_unsent(self, client, normal_user):
        headers = normal_user["headers"]
        saved = client.put(
            "/api/preferences/costs",
            json={"ffl_transfer_fee": 30, "has_cr_license": True},
            headers=headers,
        ).json()
        assert saved == {"ffl_transfer_fee": 30.0, "has_cr_license": True}
        kept = client.put(
            "/api/preferences/costs", json={"ffl_transfer_fee": 20}, headers=headers
        ).json()
        assert kept == {"ffl_transfer_fee": 20.0, "has_cr_license": True}
        assert client.get("/api/wishlist", headers=headers).json()["has_cr_license"] is True


class TestSinceAdded:
    def test_the_price_when_added_is_kept_and_the_move_measured(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        wishlist.add(session, reader, item)
        item.current_price = 450.0
        session.commit()
        line = wishlist.build(session, reader).lines[0]
        assert (line.entry.price_when_added, line.since_added) == (500, -50)


class TestAlerts:
    def _on(self, session, reader, item):
        wishlist.add(session, reader, item)
        wishlist.set_alerts(session, reader, True)
        session.commit()

    def test_a_price_change_is_due_once(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        self._on(session, reader, item)
        assert wishlist.due_alerts(session) == {}
        item.current_price = 450.0
        session.commit()
        [update] = wishlist.due_alerts(session)[reader.id]
        assert (update.news, update.headline) == (News.CHEAPER, "Price dropped")
        wishlist.mark_told(update.entry, item, utcnow())
        session.commit()
        assert wishlist.due_alerts(session) == {}
        item.current_price = 480.0
        session.commit()
        assert wishlist.due_alerts(session)[reader.id][0].news is News.DEARER

    def test_sold_gone_and_back(self, world):
        session, shop, _bare, _k31, reader = world
        sold = _gun(session, shop, "s", 500)
        gone = _gun(session, shop, "g", 500)
        self._on(session, reader, sold)
        self._on(session, reader, gone)
        sold.is_sold, sold.is_active = True, False
        gone.is_active = False
        session.commit()
        news = [update.news for update in wishlist.due_alerts(session)[reader.id]]
        assert news == [News.SOLD, News.GONE]
        for update in wishlist.due_alerts(session)[reader.id]:
            wishlist.mark_told(update.entry, update.item, utcnow())
        gone.is_active = True
        session.commit()
        assert [u.news for u in wishlist.due_alerts(session)[reader.id]] == [News.BACK]

    def test_only_when_asked_and_switching_on_skips_the_backlog(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        wishlist.add(session, reader, item)
        item.current_price = 400.0
        session.commit()
        assert wishlist.due_alerts(session) == {}
        wishlist.set_alerts(session, reader, True)
        session.commit()
        assert wishlist.due_alerts(session) == {}

    def test_the_scheduler_sends_marks_and_pushes(self, world, app_config, monkeypatch):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500, title="Swiss K31 carbine")
        self._on(session, reader, item)
        item.current_price = 450.0
        session.commit()
        sent = []
        monkeypatch.setattr(
            digest.mailer, "send_html", lambda to, subject, body, **kw: sent.append(subject)
        )
        Scheduler(app_config)._dispatch_wishlist_alerts()
        assert sent == ["Milsurp Monitor: Swiss K31 carbine is now $450"]
        Scheduler(app_config)._dispatch_wishlist_alerts()
        assert len(sent) == 1

    def test_a_failed_send_is_tried_again(self, world, app_config, monkeypatch):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        self._on(session, reader, item)
        item.is_sold = True
        session.commit()

        def refuse(*_args, **_kwargs):
            raise digest.mailer.MailError("no")

        monkeypatch.setattr(digest.mailer, "send_html", refuse)
        Scheduler(app_config)._dispatch_wishlist_alerts()
        session.expire_all()
        assert list(wishlist.due_alerts(session)) == [reader.id]

    def test_the_subjects(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500, title="K31")
        entry = wishlist.add(session, reader, item)
        subject = digest._wishlist_subject
        assert subject([wishlist.Update(entry, item, News.SOLD)]).endswith("K31 sold")
        assert subject([wishlist.Update(entry, item, News.GONE)]).endswith("no longer listed")
        assert subject([wishlist.Update(entry, item, News.BACK)]).endswith("back in stock")
        both = [wishlist.Update(entry, item, News.SOLD)] * 2
        assert subject(both).endswith("2 changes on your wishlist")

    def test_the_push_says_what_happened(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 450, title="K31")
        entry = wishlist.add(session, reader, item)
        one = pushnotify.wishlist_alert_payload([wishlist.Update(entry, item, News.CHEAPER)])
        assert one == {
            "title": "Your wishlist changed",
            "body": "Price dropped: K31 — now $450",
            "url": f"/items/{item.id}",
        }
        two = pushnotify.wishlist_alert_payload([wishlist.Update(entry, item, News.SOLD)] * 2)
        assert two["url"] == "/wishlist"

    def test_the_watch_poll_reads_wishlists_with_alerts_on(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        wishlist.add(session, reader, item)
        session.commit()
        assert watchpoll.watched_items(session) == []
        wishlist.set_alerts(session, reader, True)
        session.commit()
        assert [found.id for found in watchpoll.watched_items(session)] == [item.id]


class TestDigest:
    def test_the_digest_has_a_wishlist_section(self, world, app_config):
        session, shop, _bare, _k31, reader = world
        session.add(
            EmailPreference(
                user_id=reader.id,
                enabled=True,
                frequency_hours=24,
                last_digest_cutoff=(utcnow() - timedelta(hours=2)).replace(tzinfo=None),
            )
        )
        item = _gun(session, shop, "a", 500, title="Swiss K31 carbine")
        wishlist.add(session, reader, item)
        item.is_sold = True
        item.is_active = False
        item.price_changed_at = utcnow().replace(tzinfo=None)
        session.commit()
        built = digest.build_digest(session, reader, app_config)
        assert built is not None
        subject, body = built[0], built[1]
        assert "wishlist: sold" in subject
        assert "On your wishlist" in body

    def test_a_listing_on_both_lists_is_said_once(self, world):
        session, shop, _bare, _k31, reader = world
        item = _gun(session, shop, "a", 500)
        wishlist.add(session, reader, item)
        item.is_sold = True
        item.price_changed_at = utcnow().replace(tzinfo=None)
        session.commit()
        since = utcnow() - timedelta(hours=1)
        assert len(wishlist.digest_updates(session, reader, since)) == 1
        assert wishlist.digest_updates(session, reader, since, skip={item.id}) == []


class TestApiMore:
    def _item(self, clean_db, title="Swiss K31", price=450.0):
        site = Site(slug="api2", name="Shop API", base_url="https://api.test/")
        clean_db.add(site)
        clean_db.flush()
        item = _gun(clean_db, site, "x", price, title=title)
        clean_db.commit()
        return item.id

    def test_settings_alerts_and_budget(self, client, normal_user):
        headers = normal_user["headers"]
        body = client.put(
            "/api/wishlist/settings", json={"alerts": True, "budget": 2000}, headers=headers
        ).json()
        assert (body["wishlist_alerts"], body["budget"]) == (True, 2000)
        kept = client.put("/api/wishlist/settings", json={"alerts": False}, headers=headers)
        assert (kept.json()["wishlist_alerts"], kept.json()["budget"]) == (False, 2000)
        cleared = client.put("/api/wishlist/settings", json={"budget": None}, headers=headers)
        assert cleared.json()["budget"] is None

    def test_the_browse_cards_know(self, client, normal_user, clean_db):
        headers = normal_user["headers"]
        item_id = self._item(clean_db)
        client.put(f"/api/wishlist/{item_id}", headers=headers)
        page = client.get("/api/items?availability=all", headers=headers).json()
        assert [row["wishlisted"] for row in page["items"]] == [True]

    def test_export_guards_formulas(self, client, normal_user, clean_db):
        headers = normal_user["headers"]
        item_id = self._item(clean_db, title="=HYPERLINK(evil)")
        client.put(f"/api/wishlist/{item_id}", headers=headers)
        response = client.get("/api/wishlist/export", headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.splitlines()
        assert lines[0].startswith("title,shop,url,status,price")
        assert lines[1].startswith("'=HYPERLINK(evil),Shop API")

    def test_bought_it_moves_it_to_the_collection(self, client, normal_user, clean_db):
        headers = normal_user["headers"]
        item_id = self._item(clean_db)
        client.put(f"/api/wishlist/{item_id}", headers=headers)
        response = client.post(f"/api/wishlist/{item_id}/bought", headers=headers)
        assert response.status_code == 201
        row = response.json()
        assert (row["title"], row["paid"], row["acquired_from"]) == ("Swiss K31", 450, "Shop API")
        assert client.get("/api/wishlist", headers=headers).json()["lines"] == []
        assert clean_db.query(CollectionItem).count() == 1
        again = client.post(f"/api/wishlist/{item_id}/bought", headers=headers)
        assert again.status_code == 404
