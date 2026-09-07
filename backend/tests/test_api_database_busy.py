"""What the API says when SQLite is busy.

A scan of a large vendor holds the write lock in short bursts for as long as it
runs, so a request can arrive during one, wait out its busy timeout and fail.
Signing in writes a last-seen timestamp, so signing in was one of them — and it
was answered "500 Internal Server Error", which is not what happened. Nothing
was broken, the request was not refused, and it would have worked a moment
later.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.main import RETRY_AFTER_SECONDS, _is_locked


def raising(error: Exception):
    def dependency():
        raise error
        yield  # pragma: no cover - never reached

    return dependency


def locked() -> OperationalError:
    """The shape SQLAlchemy wraps SQLite's SQLITE_BUSY in."""
    import sqlite3

    return OperationalError("UPDATE users …", {}, sqlite3.OperationalError("database is locked"))


class TestRecognizingALock:
    @pytest.mark.parametrize(
        "message",
        ["database is locked", "database table is locked", "database schema is locked"],
    )
    def test_sqlite_says_it_several_ways(self, message):
        import sqlite3

        assert _is_locked(OperationalError("…", {}, sqlite3.OperationalError(message)))

    @pytest.mark.parametrize(
        "message",
        ["no such table: items", "disk I/O error", "attempt to write a readonly database"],
    )
    def test_a_real_fault_is_not_a_lock(self, message):
        """Or a broken database would spend its life being politely retried."""
        import sqlite3

        assert not _is_locked(OperationalError("…", {}, sqlite3.OperationalError(message)))


class TestWhatTheClientIsTold:
    @pytest.fixture
    def busy(self, client, admin_headers):
        """The database is locked from here on.

        Depends on admin_headers so the sign-in that mints the token happens
        *before* the lock is installed — otherwise the fixture cannot get a
        token, which is the very failure under test.
        """
        client.app.dependency_overrides[get_db] = raising(locked())
        yield client
        client.app.dependency_overrides.clear()

    def test_a_lock_is_503_and_not_500(self, busy, admin_headers):
        response = busy.get("/api/items", headers=admin_headers)
        assert response.status_code == 503

    def test_it_says_when_to_come_back(self, busy, admin_headers):
        response = busy.get("/api/items", headers=admin_headers)
        assert response.headers["Retry-After"] == str(RETRY_AFTER_SECONDS)
        assert int(response.headers["Retry-After"]) > 0

    def test_it_says_why(self, busy, admin_headers):
        """A person retrying by hand should know it is not their fault."""
        detail = busy.get("/api/items", headers=admin_headers).json()["detail"]
        assert "busy" in detail.lower()
        assert "scan" in detail.lower()

    def test_signing_in_gets_the_same_answer(self, busy):
        """The request that started this. It writes, so it is the one that
        loses a race with a scan."""
        response = busy.post(
            "/api/auth/login", json={"username": "admin", "password": "irrelevant"}
        )
        assert response.status_code == 503

    def test_a_genuine_database_fault_still_reads_as_a_fault(self, client, admin_headers):
        import sqlite3

        broken = OperationalError("…", {}, sqlite3.OperationalError("no such table: items"))
        client.app.dependency_overrides[get_db] = raising(broken)
        try:
            response = client.get("/api/items", headers=admin_headers)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 500
        assert "Retry-After" not in response.headers
