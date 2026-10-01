"""For your guns, worth over time, shop scorecards, "will it drop?", and the
monthly market report.

Five readings of data the catalog already had, each with a rule that keeps it
honest -- and a test for that rule: the armory's precedence decides which
accessories fit a gun, a snapshot lines up by day, a shop needs ten cuts before
it has a habit, a first scan is not new stock, and a report never compares the
market with a day before anyone was watching it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.models import (
    ArmoryStatus,
    Caliber,
    CollectionItem,
    CollectionValuation,
    EmailPreference,
    EmailStatus,
    FirearmModel,
    Item,
    PriceHistory,
    ScanRun,
    ScanStatus,
    Site,
    User,
    UserRole,
    utcnow,
)
from app.security import hash_password
from app.services import armory, collection, foryourguns, marketreport, scorecards


def _naive_now() -> datetime:
    return utcnow().replace(tzinfo=None)


@pytest.fixture
def world(clean_db):
    session = clean_db
    shops = [
        Site(slug=f"o{n}", name=f"Shop {n}", base_url=f"https://o{n}.test/") for n in (1, 2, 3)
    ]
    owner = User(
        username="owner",
        email="owner@example.test",
        password_hash=hash_password("x" * 16),
        role=UserRole.NORMAL,
    )
    carcano_cal = Caliber(
        name="6.5x52mm Carcano", aliases="6.5mm Carcano", status=ArmoryStatus.APPROVED
    )
    moschetto = FirearmModel(
        name="Carcano M91 Cavalry Carbine",
        aliases="Moschetto 91",
        status=ArmoryStatus.APPROVED,
        position=900,
    )
    mosin = FirearmModel(name="Mosin-Nagant M91/30", aliases="M91/30", status=ArmoryStatus.APPROVED)
    session.add_all([*shops, owner, carcano_cal, moschetto, mosin])
    session.flush()
    moschetto.calibers = [carcano_cal]
    session.commit()
    armory.invalidate()
    scorecards.forget_habits()
    yield session, shops, owner, moschetto, mosin
    armory.invalidate()
    scorecards.forget_habits()


def _listing(session, site, key, title, *, price=100.0, gun=False, days_ago=3, **kwargs):
    item = Item(
        site_id=site.id,
        external_key=key,
        url=f"{site.base_url}{key}",
        title=title,
        current_price=price,
        is_rifle=gun,
        first_seen_at=_naive_now() - timedelta(days=days_ago),
        **kwargs,
    )
    session.add(item)
    session.flush()
    return item


class TestForYourGuns:
    def test_ammunition_by_caliber_and_accessories_by_model(self, world):
        session, shops, owner, moschetto, _mosin = world
        session.add(
            CollectionItem(
                user_id=owner.id,
                title="Carcano Carbine",
                firearm_model_id=moschetto.id,
                caliber="6.5mm Carcano",
            )
        )
        ammo = _listing(
            session, shops[0], "a", "6.5x52 Carcano ammo, 20 rounds", caliber="6.5x52mm Carcano"
        )
        clips = _listing(
            session, shops[0], "c", "Carcano en bloc clips, lot of 10", caliber="6.5x52mm Carcano"
        )
        bayonet = _listing(session, shops[1], "b", "Moschetto 91 folding bayonet")
        _listing(session, shops[1], "w", "8mm Mauser ammo", caliber="8mm Mauser")
        _listing(session, shops[1], "m", "Mosin M91/30 bayonet")
        _listing(session, shops[1], "g", "Moschetto 91 carbine", gun=True)
        _listing(session, shops[1], "s", "Moschetto 91 sling", is_sold=True)
        session.commit()

        (fit,) = foryourguns.for_user(session, owner)
        assert {item.id for item in fit.ammo} == {ammo.id, clips.id}
        assert [item.id for item in fit.accessories] == [bayonet.id]

    def test_a_magazine_saying_rounds_is_not_ammunition(self, world):
        session, shops, owner, moschetto, _mosin = world
        session.add(
            CollectionItem(
                user_id=owner.id,
                title="Carcano",
                firearm_model_id=moschetto.id,
                caliber="6.5mm Carcano",
            )
        )
        _listing(
            session, shops[0], "mag", "Moschetto 91 6 round magazine", caliber="6.5x52mm Carcano"
        )
        session.commit()
        (fit,) = foryourguns.for_user(session, owner)
        assert fit.ammo == [] and len(fit.accessories) == 1

    def test_the_armorys_precedence_decides(self, world):
        """A title naming two models belongs to the one the armory tries first."""
        session, shops, owner, _moschetto, mosin = world
        session.add(CollectionItem(user_id=owner.id, title="My Mosin", firearm_model_id=mosin.id))
        _listing(session, shops[0], "x", "Moschetto 91 bayonet, also fits M91/30 with filing")
        session.commit()
        (fit,) = foryourguns.for_user(session, owner)
        assert fit.accessories == []

    def test_the_digest_asks_only_for_what_is_new(self, world):
        session, shops, owner, moschetto, _mosin = world
        session.add(CollectionItem(user_id=owner.id, title="C", firearm_model_id=moschetto.id))
        _listing(session, shops[0], "old", "Moschetto 91 sling", days_ago=10)
        new = _listing(session, shops[0], "new", "Moschetto 91 cleaning rod", days_ago=1)
        session.commit()
        (fit,) = foryourguns.for_user(session, owner, since=_naive_now() - timedelta(days=2))
        assert [item.id for item in fit.accessories] == [new.id]

    def test_the_api(self, client, normal_user):
        response = client.get("/api/collection/for-your-guns", headers=normal_user["headers"])
        assert response.status_code == 200
        assert response.json() == []


class TestWorthOverTime:
    def _owned(self, session, shops, owner, model):
        for index in range(5):
            _listing(
                session,
                shops[index % 2],
                f"live{index}",
                f"Moschetto 91 #{index}",
                price=600,
                gun=True,
                firearm_model_id=model.id,
            )
        row = CollectionItem(user_id=owner.id, title="C", firearm_model_id=model.id)
        session.add(row)
        session.commit()
        return row

    def test_a_week_apart_and_lined_up_by_day(self, world):
        session, shops, owner, moschetto, _mosin = world
        self._owned(session, shops, owner, moschetto)
        day = date(2026, 10, 1)
        assert collection.snapshot_due(session, day) == 1
        session.commit()
        assert collection.snapshot_due(session, day + timedelta(days=3)) == 0
        assert collection.snapshot_due(session, day + timedelta(days=7)) == 1
        session.commit()
        assert [(d, v) for d, v, _g in collection.history(session, owner.id)] == [
            (day, 600.0),
            (day + timedelta(days=7), 600.0),
        ]

    def test_a_gun_added_on_the_snapshot_day_joins_it(self, world):
        session, shops, owner, moschetto, _mosin = world
        self._owned(session, shops, owner, moschetto)
        day = date(2026, 10, 1)
        collection.snapshot_due(session, day)
        session.commit()
        session.add(CollectionItem(user_id=owner.id, title="D", firearm_model_id=moschetto.id))
        session.commit()
        assert collection.snapshot_due(session, day) == 1
        session.commit()
        assert collection.history(session, owner.id)[0][2] == 2
        assert session.query(CollectionValuation).count() == 2

    def test_a_gun_that_cannot_be_valued_is_left_out(self, world):
        session, _shops, owner, _moschetto, _mosin = world
        session.add(CollectionItem(user_id=owner.id, title="Unknown"))
        session.commit()
        assert collection.snapshot_due(session, date(2026, 10, 1)) == 0


class TestShops:
    def _scanned(self, session, site, at):
        session.add(
            ScanRun(site_id=site.id, status=ScanStatus.SUCCESS, started_at=at, finished_at=at)
        )

    def test_price_against_the_market_and_arrivals(self, world):
        """Each shop against the *other* shops' listings of the same model."""
        session, shops, _owner, moschetto, _mosin = world
        first_scan = _naive_now() - timedelta(days=20)
        for shop in shops:
            self._scanned(session, shop, first_scan)
        # Shop 1 asks 120; shops 2 and 3 ask 100 -- five each.
        for index in range(5):
            _listing(
                session,
                shops[0],
                f"a{index}",
                "Moschetto 91",
                price=120,
                gun=True,
                firearm_model_id=moschetto.id,
                days_ago=2,
            )
            _listing(
                session,
                shops[1],
                f"b{index}",
                "Moschetto 91",
                price=100,
                gun=True,
                firearm_model_id=moschetto.id,
                days_ago=30,
            )
            _listing(
                session,
                shops[2],
                f"c{index}",
                "Moschetto 91",
                price=100,
                gun=True,
                firearm_model_id=moschetto.id,
                days_ago=30,
            )
        session.commit()
        cards = {card.slug: card for card in scorecards.scorecards(session)}
        # Shop 1 against shops 2 and 3: 120 / 100.
        assert cards["o1"].price_vs_market == pytest.approx(1.2, rel=1e-3)
        # Shop 2 against shops 1 and 3, whose median is 110: never against itself.
        assert cards["o2"].price_vs_market == pytest.approx(100 / 110, rel=1e-3)
        # Shop 2's stock was there before the first scan: not new, not arrivals.
        assert (cards["o1"].new_this_week, cards["o2"].new_this_week) == (5, 0)
        assert sum(cards["o2"].arrivals_by_weekday) == 0
        assert cards["o1"].busiest_day is not None

    def test_one_other_shop_is_not_a_market(self, world):
        session, shops, _owner, moschetto, _mosin = world
        for index in range(6):
            _listing(
                session,
                shops[0],
                f"a{index}",
                "Moschetto 91",
                price=120,
                gun=True,
                firearm_model_id=moschetto.id,
            )
            _listing(
                session,
                shops[1],
                f"b{index}",
                "Moschetto 91",
                price=100,
                gun=True,
                firearm_model_id=moschetto.id,
            )
        session.commit()
        cards = {card.slug: card for card in scorecards.scorecards(session)}
        assert cards["o1"].price_vs_market is None

    def test_a_habit_needs_ten_cuts(self, world):
        session, shops, _owner, _moschetto, _mosin = world
        start = _naive_now() - timedelta(days=40)
        for index in range(11):
            item = _listing(
                session, shops[0], f"h{index}", f"Rifle {index}", price=90, gun=True, days_ago=40
            )
            item.first_seen_at = start
            session.add_all(
                [
                    PriceHistory(item_id=item.id, price=100, observed_at=start),
                    PriceHistory(item_id=item.id, price=90, observed_at=start + timedelta(days=12)),
                ]
            )
        for index in range(3):
            item = _listing(
                session, shops[1], f"k{index}", f"Rifle k{index}", price=90, gun=True, days_ago=40
            )
            session.add_all(
                [
                    PriceHistory(item_id=item.id, price=100, observed_at=start),
                    PriceHistory(item_id=item.id, price=90, observed_at=start + timedelta(days=5)),
                ]
            )
        session.commit()
        found = scorecards.habits(session)
        assert shops[1].id not in found
        habit = found[shops[0].id]
        assert (habit.drops, habit.median_day, habit.median_pct) == (11, 12.0, 10.0)
        assert habit.share == 1.0

    def test_a_listing_page_says_so(self, client, admin_headers, seeded):
        site = seeded.query(Site).order_by(Site.id).first()
        start = _naive_now() - timedelta(days=30)
        for index in range(10):
            item = Item(
                site_id=site.id,
                external_key=f"cut{index}",
                url=f"{site.base_url}cut{index}",
                title=f"Cut rifle {index}",
                current_price=90.0,
                is_rifle=True,
                first_seen_at=start,
            )
            seeded.add(item)
            seeded.flush()
            seeded.add_all(
                [
                    PriceHistory(item_id=item.id, price=100, observed_at=start),
                    PriceHistory(item_id=item.id, price=90, observed_at=start + timedelta(days=9)),
                ]
            )
        seeded.commit()
        scorecards.forget_habits()
        detail = client.get(f"/api/items/{item.id}", headers=admin_headers).json()
        assert detail["markdown_habit"]["drops"] == 10
        assert detail["markdown_habit"]["median_day"] == 9.0
        assert detail["markdown_habit"]["listed_days"] == 30
        assert client.get("/api/market/shops", headers=admin_headers).status_code == 200
        scorecards.forget_habits()


class TestTheMarketReport:
    def _market(self, session, shops, model, *, days_ago, then_price, now_price):
        """Eight listings seen days_ago at then_price, now at now_price."""
        seen = _naive_now() - timedelta(days=days_ago)
        for index in range(marketreport.MIN_LISTINGS):
            item = _listing(
                session,
                shops[index % 3],
                f"r{model.id}-{index}",
                f"{model.name} {index}",
                price=now_price,
                gun=True,
                firearm_model_id=model.id,
                days_ago=days_ago,
            )
            item.first_seen_at = seen
            session.add_all(
                [
                    PriceHistory(item_id=item.id, price=then_price, observed_at=seen),
                    PriceHistory(
                        item_id=item.id,
                        price=now_price,
                        observed_at=_naive_now() - timedelta(days=2),
                    ),
                ]
            )
        session.commit()

    def test_what_got_cheaper(self, world):
        session, shops, _owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=60, then_price=1000, now_price=800)
        report = marketreport.build(session)
        assert report.days == 30
        (move,) = report.cheaper
        assert (move.model, move.then, move.now) == ("Carcano M91 Cavalry Carbine", 1000, 800)
        assert report.dearer == []

    def test_a_sale_with_no_date_is_not_on_either_shelf(self, world):
        """Centerfire keeps sold guns up with no date of sale; 137 K98ks read
        as for sale then and gone now, and the model looked twice as dear."""
        session, shops, _owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=60, then_price=1000, now_price=1000)
        for index in range(20):
            _listing(
                session,
                shops[0],
                f"sold{index}",
                "Moschetto 91",
                price=300,
                gun=True,
                firearm_model_id=moschetto.id,
                days_ago=60,
                is_sold=True,
            )
        session.commit()
        report = marketreport.build(session)
        assert report.cheaper == [] and report.dearer == [] and report.scarcer == []

    def test_a_changed_mix_is_not_a_price_move(self, world):
        session, shops, _owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=60, then_price=1000, now_price=800)
        for index in range(20):
            _listing(
                session,
                shops[1],
                f"new{index}",
                "Moschetto 91",
                price=300,
                gun=True,
                firearm_model_id=moschetto.id,
                days_ago=2,
            )
        session.commit()
        report = marketreport.build(session)
        assert report.cheaper == []

    def test_the_window_is_what_the_data_covers(self, world):
        """Production's history began on 5 September: a 30-day window on 1
        October would compare the market with a day before anyone looked."""
        session, shops, _owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=20, then_price=1000, now_price=800)
        report = marketreport.build(session)
        assert report.days == 13

    def test_too_little_history_says_nothing(self, world):
        session, shops, _owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=10, then_price=1000, now_price=800)
        assert marketreport.build(session) is None

    def test_a_render(self, world, app_config):
        session, shops, owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=60, then_price=1000, now_price=800)
        subject, body, _images = marketreport.render(owner, marketreport.build(session), app_config)
        assert "the market" in subject
        assert "down 20%" in body

    def test_once_a_month_to_whoever_asked(self, world, app_config, monkeypatch):
        from app.scheduler import Scheduler
        from app.services import digest

        session, shops, owner, moschetto, _mosin = world
        self._market(session, shops, moschetto, days_ago=60, then_price=1000, now_price=800)
        session.add(EmailPreference(user_id=owner.id, market_report=True))
        session.commit()
        sent = []
        monkeypatch.setattr(
            digest.mailer, "send_html", lambda to, subject, body, **kw: sent.append(to)
        )
        # Report day is today, so the history above, written relative to the
        # real clock, is the history the report reads.
        monkeypatch.setattr(marketreport, "due", lambda now=None: True)
        scheduler = Scheduler(app_config)
        scheduler._dispatch_market_report()
        scheduler._dispatch_market_report()
        assert sent == [owner.email]

    def test_not_before_the_first_at_one(self):
        assert not marketreport.due(datetime(2026, 11, 2, 14, tzinfo=UTC))
        assert not marketreport.due(datetime(2026, 11, 1, 9, tzinfo=UTC))
        assert marketreport.due(datetime(2026, 11, 1, 13, tzinfo=UTC))

    def test_send_now_and_the_preference(self, client, normal_user):
        headers = normal_user["headers"]
        saved = client.put("/api/preferences/email", json={"market_report": True}, headers=headers)
        assert saved.json()["market_report"] is True
        # Email is off in the test configuration.
        assert (
            client.post("/api/preferences/email/market-report", headers=headers).status_code == 409
        )

    def test_an_empty_catalog_skips_rather_than_sending(self, world, app_config):
        session, _shops, owner, _moschetto, _mosin = world
        assert marketreport.send(session, owner, app_config).status is EmailStatus.SKIPPED
