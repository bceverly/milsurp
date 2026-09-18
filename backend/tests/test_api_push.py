"""Subscribing a browser to notifications, and what happens when one dies.

A subscription belongs to a *device*, not to an account: the same person on a
phone and a desktop has two, and a reinstalled browser has a new one rather
than an edited old one. The endpoint is the whole capability -- anyone holding
it can notify that device -- so it is unique, never rendered, and never
returned.

The part worth testing hardest is the pruning. Browsers rotate subscriptions,
people clear site data, phones are replaced; a push service says so with 404 or
410, and a subscription nobody removes is a message sent into nothing forever.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.config import get_config
from app.models import PushSubscription, User, UserRole
from app.services import pushnotify, webpush


def _with_keys(config, private: str = "", public: str = ""):
    """A copy of the config carrying (or deliberately lacking) VAPID keys.

    `replace` rather than assignment: the config is a frozen dataclass, which
    is the right shape for something read from a file on every request and the
    reason a test cannot simply poke a value into it.
    """
    return replace(
        config,
        security=replace(
            config.security,
            vapid_private_key=private,
            vapid_public_key=public,
            vapid_subject="mailto:ops@example.test",
        ),
    )


@pytest.fixture
def push_keys(app_config, client):
    """A deployment with keys, which is what makes the feature exist at all.

    Injected through FastAPI's own override rather than by patching a module:
    `get_config` is captured in the dependency at import time, so patching the
    name it came from changes nothing the endpoints see.
    """
    private, public = webpush.generate_keys()
    config = _with_keys(app_config, private, public)
    client.app.dependency_overrides[get_config] = lambda: config
    yield config
    client.app.dependency_overrides.pop(get_config, None)


@pytest.fixture
def no_push_keys(app_config, client):
    config = _with_keys(app_config)
    client.app.dependency_overrides[get_config] = lambda: config
    yield config
    client.app.dependency_overrides.pop(get_config, None)


@pytest.fixture
def subscription_body():
    _private, public = webpush.generate_keys()
    return {
        "endpoint": "https://push.test/wpush/v2/abcdef",
        "p256dh": public,
        "auth": webpush.b64(b"0123456789abcdef"),
    }


class TestWhetherItIsOfferedAtAll:
    def test_a_deployment_with_no_keys_says_so(self, client, admin_headers, no_push_keys):
        body = client.get("/api/push", headers=admin_headers).json()
        assert body["available"] is False
        assert body["public_key"] is None

    def test_and_refuses_to_take_a_subscription(
        self, client, admin_headers, no_push_keys, subscription_body
    ):
        response = client.post("/api/push", json=subscription_body, headers=admin_headers)
        assert response.status_code == 503

    def test_a_configured_one_hands_over_the_public_key(self, client, admin_headers, push_keys):
        """Not a secret: every browser that subscribes is given it."""
        body = client.get("/api/push", headers=admin_headers).json()
        assert body["available"] is True
        assert body["public_key"] == push_keys.security.vapid_public_key


class TestSubscribing:
    def test_a_browser_is_recorded(self, client, admin_headers, push_keys, subscription_body):
        response = client.post("/api/push", json=subscription_body, headers=admin_headers)
        assert response.status_code == 201, response.text
        assert client.get("/api/push", headers=admin_headers).json()["subscriptions"]

    def test_the_endpoint_never_comes_back(
        self, client, admin_headers, push_keys, subscription_body
    ):
        """It is the only thing standing between a stranger and the ability to
        notify that device, so nothing on a page needs it."""
        created = client.post("/api/push", json=subscription_body, headers=admin_headers).json()
        assert "endpoint" not in created
        assert "auth" not in created

        listed = client.get("/api/push", headers=admin_headers).json()["subscriptions"][0]
        assert "endpoint" not in listed

    def test_subscribing_twice_does_not_duplicate(
        self, client, admin_headers, push_keys, subscription_body
    ):
        """A browser hands back the same endpoint whenever the page asks, so
        reloading the settings page must not make a second row or an error."""
        client.post("/api/push", json=subscription_body, headers=admin_headers)
        client.post("/api/push", json=subscription_body, headers=admin_headers)
        assert len(client.get("/api/push", headers=admin_headers).json()["subscriptions"]) == 1

    def test_it_records_which_browser(self, client, admin_headers, push_keys, subscription_body):
        client.post(
            "/api/push",
            json=subscription_body,
            headers={**admin_headers, "user-agent": "Firefox on a Pixel"},
        )
        listed = client.get("/api/push", headers=admin_headers).json()["subscriptions"][0]
        assert listed["user_agent"] == "Firefox on a Pixel"

    def test_an_endpoint_that_moves_account_follows_it(
        self, clean_db, client, admin_headers, normal_user, push_keys, subscription_body
    ):
        """Whoever is holding the browser owns the subscription. A shared
        machine where two people sign in must not notify the first about the
        second's watchlist."""
        client.post("/api/push", json=subscription_body, headers=admin_headers)
        client.post("/api/push", json=subscription_body, headers=normal_user["headers"])

        assert client.get("/api/push", headers=admin_headers).json()["subscriptions"] == []
        assert client.get("/api/push", headers=normal_user["headers"]).json()["subscriptions"]

    def test_signing_in_is_required(self, client, subscription_body):
        assert client.post("/api/push", json=subscription_body).status_code == 401


class TestUnsubscribing:
    def test_a_device_can_be_forgotten(self, client, admin_headers, push_keys, subscription_body):
        created = client.post("/api/push", json=subscription_body, headers=admin_headers).json()
        assert client.delete(f"/api/push/{created['id']}", headers=admin_headers).status_code == 204
        assert client.get("/api/push", headers=admin_headers).json()["subscriptions"] == []

    def test_but_only_your_own(
        self, client, admin_headers, normal_user, push_keys, subscription_body
    ):
        created = client.post("/api/push", json=subscription_body, headers=admin_headers).json()
        response = client.delete(f"/api/push/{created['id']}", headers=normal_user["headers"])
        # 404 rather than 403: whether somebody else's subscription exists is
        # not a question this should answer.
        assert response.status_code == 404
        assert client.get("/api/push", headers=admin_headers).json()["subscriptions"]


class TestSendingToAUser:
    @pytest.fixture
    def subscribed(self, clean_db, seeded, push_keys):
        user = User(
            username="watcher",
            email="watcher@example.test",
            role=UserRole.NORMAL,
            is_active=True,
            password_hash="x",
        )
        clean_db.add(user)
        clean_db.flush()
        _private, public = webpush.generate_keys()
        clean_db.add(
            PushSubscription(
                user_id=user.id,
                endpoint="https://push.test/one",
                p256dh=public,
                auth=webpush.b64(b"0123456789abcdef"),
            )
        )
        clean_db.commit()
        return clean_db, user

    def test_a_delivered_message_is_counted(self, subscribed, push_keys, monkeypatch):
        session, user = subscribed
        monkeypatch.setattr(webpush, "send", lambda *a, **k: None)
        assert pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys) == 1

    def test_a_gone_subscription_is_deleted_rather_than_retried(
        self, subscribed, push_keys, monkeypatch
    ):
        session, user = subscribed

        def gone(*args, **kwargs):
            raise webpush.PushError("gone", gone=True)

        monkeypatch.setattr(webpush, "send", gone)
        assert pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys) == 0
        session.commit()
        assert pushnotify.subscriptions_for(session, user) == []

    def test_an_ordinary_failure_is_counted_not_deleted(self, subscribed, push_keys, monkeypatch):
        """Three nights of a push service being unreachable is a push service
        problem, not a dead browser."""
        session, user = subscribed

        def busy(*args, **kwargs):
            raise webpush.PushError("busy")

        monkeypatch.setattr(webpush, "send", busy)
        pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys)
        session.commit()
        remaining = pushnotify.subscriptions_for(session, user)
        assert len(remaining) == 1
        assert remaining[0].failures == 1

    def test_but_a_run_of_them_eventually_is(self, subscribed, push_keys, monkeypatch):
        session, user = subscribed

        def busy(*args, **kwargs):
            raise webpush.PushError("busy")

        monkeypatch.setattr(webpush, "send", busy)
        for _ in range(pushnotify.MAX_FAILURES):
            pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys)
        session.commit()
        assert pushnotify.subscriptions_for(session, user) == []

    def test_a_success_forgives_the_earlier_failures(self, subscribed, push_keys, monkeypatch):
        session, user = subscribed
        monkeypatch.setattr(
            webpush, "send", lambda *a, **k: (_ for _ in ()).throw(webpush.PushError("busy"))
        )
        pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys)
        monkeypatch.setattr(webpush, "send", lambda *a, **k: None)
        pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys)
        session.commit()
        assert pushnotify.subscriptions_for(session, user)[0].failures == 0

    def test_it_never_raises(self, subscribed, push_keys, monkeypatch):
        """The caller is a scheduler tick. A notification that can break the
        thing it reports on is worse than one that does not arrive."""
        session, user = subscribed

        def explode(*args, **kwargs):
            raise RuntimeError("something unexpected")

        monkeypatch.setattr(webpush, "send", explode)
        # The layer below really does raise...
        with pytest.raises(RuntimeError):
            webpush.send("", "", "", {}, keys=None, subject="")
        # ...and the layer the scheduler calls still returns a number.
        assert pushnotify.send_to_user(session, user, {"body": "hi"}, push_keys) == 0

    def test_a_deployment_with_no_keys_sends_nothing_quietly(self, subscribed, app_config):
        session, user = subscribed
        assert pushnotify.send_to_user(session, user, {"body": "hi"}, _with_keys(app_config)) == 0


class TestWhatAWatchAlertSays:
    def test_one_listing_names_it_and_its_price(self):
        class Item:
            id = 42
            title = "Mosin-Nagant M91/30"
            current_price = 695.0

        class Update:
            item = Item()

        payload = pushnotify.watch_alert_payload([Update()])
        assert "Mosin-Nagant M91/30" in payload["body"]
        assert "$695" in payload["body"]
        assert payload["url"] == "/items/42"

    def test_several_are_counted_rather_than_listed(self):
        """A notification is read in a glance, and a list of five titles is a
        list nobody finishes."""

        class Item:
            id = 1
            title = "Mosin-Nagant M91/30"
            current_price = 695.0

        class Update:
            item = Item()

        payload = pushnotify.watch_alert_payload([Update(), Update(), Update()])
        assert "2 more" in payload["body"]
        assert payload["url"] == "/watchlist"
