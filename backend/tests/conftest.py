"""Shared pytest fixtures.

Every test runs against a throwaway SQLite database in a temp directory, built
by the same Alembic migration chain production uses — so the suite exercises the
real schema rather than a `create_all()` approximation that could drift from it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


def _tesseract_is_installed() -> bool:
    from app.scrapers import flyer

    return flyer.ocr_available()


#: For a test that reads a flyer. OCR needs the tesseract binary, which is a
#: system package rather than a Python one, so a checkout can be complete and
#: still not have it.
#:
#: Defined here rather than in each file because it is one policy, and having
#: it in only one of the two files that needed it is how six OCR tests reached
#: CI and blew up there instead of skipping: the guard was in test_flyer.py and
#: not in test_hunters_lodge.py. CI installs tesseract, so these run there.
needs_ocr = pytest.mark.skipif(not _tesseract_is_installed(), reason="tesseract is not installed")


@pytest.fixture(scope="session")
def _test_config_file(tmp_path_factory) -> Path:
    """A config file pointing every path at a temp directory."""
    root = tmp_path_factory.mktemp("milsurp")
    config_path = root / "config.yaml"
    config_path.write_text(
        f"""
database:
  path: {root / 'test.db'}
images:
  path: {root / 'images'}
security:
  # Long enough to satisfy the HMAC-SHA256 key-length guidance; the values
  # themselves are throwaway.
  password_pepper: "test-pepper-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  jwt_secret: "test-jwt-secret-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  # The lowest cost Argon2 accepts: the suite hashes a lot of passwords, and
  # the tests are about behavior, not about how slow the KDF is.
  argon2_time_cost: 1
  argon2_memory_cost: 8
  argon2_parallelism: 1
admin:
  username: admin
  email: admin@example.com
  password: "test-admin-passphrase"
email:
  enabled: false
scheduler:
  # The background thread would start real scans against live vendor sites.
  enabled: false
scraping:
  request_delay: 0
  download_images: false
  # The scraper tests mock a vendor's pages, not its robots.txt, and an
  # unmocked robots fetch fails closed by design. Enforcement has tests of its
  # own -- see test_robots.py and TestRobotsIsEnforced in test_scrapers_base.py.
  obey_robots: false
""",
        encoding="utf-8",
    )
    return config_path


@pytest.fixture(autouse=True, scope="session")
def _configure_environment(_test_config_file):
    os.environ["MILSURP_ENV"] = "dev"
    os.environ["MILSURP_CONFIG"] = str(_test_config_file)
    from app import config as config_module

    config_module.get_config(reload=True)
    return


@pytest.fixture(scope="session")
def app_config(_configure_environment):
    from app.config import get_config

    return get_config()


@pytest.fixture(scope="session")
def _database(app_config):
    """Build the schema once per session, via the real migration chain."""
    from app import migrations
    from app.database import reset_engine

    reset_engine()
    app_config.ensure_directories()
    migrations.upgrade(app_config)
    yield
    reset_engine()


@pytest.fixture
def session(_database):
    """A database session that rolls everything back afterward."""
    from app.database import get_session_factory

    db = get_session_factory()()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture(autouse=True)
def _forget_compiled_manufacturers():
    """Drop the process-wide maker registry between tests.

    It is a cache over a table, and a test that changes the table would
    otherwise be read by the next one through the previous one's rules.
    """
    from app.services import manufacturers

    manufacturers.invalidate()
    yield
    manufacturers.invalidate()


@pytest.fixture
def ctx_factory(app_config):
    """Build a ScrapeContext with particular hooks, and close it afterwards."""
    from app.scrapers import ScrapeContext

    made = []

    def build(**kwargs):
        context = ScrapeContext(app_config, **kwargs)
        made.append(context)
        return context

    yield build
    for context in made:
        context.close()


@pytest.fixture
def clean_db(_database):
    """Truncate every table so a test starts from a known-empty database."""
    from sqlalchemy import text

    from app.database import get_session_factory

    db = get_session_factory()()
    try:
        # Reverse dependency order so foreign keys never block a delete.
        for table in (
            "email_logs",
            "email_preference_sites",
            "email_preferences",
            "price_history",
            "item_photos",
            "items",
            "scan_runs",
            "sites",
            "manufacturer_models",
            "manufacturers",
            "users",
        ):
            db.execute(text(f"DELETE FROM {table}"))
        db.commit()
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded(clean_db, app_config):
    """A database with the site list and the admin account seeded."""
    from app.services import bootstrap

    bootstrap.seed_sites(clean_db)
    bootstrap.ensure_admin(clean_db, app_config)
    return clean_db


@pytest.fixture
def client(seeded):
    """A TestClient with the app's lifespan skipped.

    The lifespan would start the scheduler and re-run bootstrap; the fixtures
    above have already done the useful half of that, deterministically.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def admin_token(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-passphrase"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def normal_user(client, admin_headers):
    """A non-admin account, returned with its own auth headers."""
    response = client.post(
        "/api/users",
        json={
            "username": "viewer",
            "email": "viewer@example.com",
            "password": "viewer-long-passphrase",
            "role": "normal",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    login = client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "viewer-long-passphrase"},
    )
    return {
        "user": response.json(),
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }
