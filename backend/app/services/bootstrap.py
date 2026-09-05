"""First-run setup: create the schema, seed the site list and the admin account."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import migrations
from ..config import Config, get_config
from ..models import EmailPreference, Site, User, UserRole
from ..scrapers import available_slugs, iter_scrapers
from ..security import hash_password

log = logging.getLogger("milsurp.bootstrap")


def create_schema(config: Config | None = None) -> None:
    """Bring the database up to the newest migration.

    Alembic is the only thing that ever creates or alters a table, including on
    a brand new install: a fresh database is built by running the same migration
    chain an upgraded one runs, so the two can never drift apart. With nothing
    outstanding this is a no-op, so it is safe on every start.
    """
    migrations.upgrade(config or get_config())


def seed_sites(session: Session) -> tuple[int, int]:
    """Reconcile the ``sites`` table against the scraper registry.

    Returns ``(added, retired)``. Admin-owned columns -- ``enabled`` and
    ``scan_interval_minutes`` -- are never overwritten once a row exists, so a
    site an operator turned off stays off across upgrades.
    """
    existing = {site.slug: site for site in session.execute(select(Site)).scalars().all()}
    added = 0

    for scraper in iter_scrapers():
        site = existing.get(scraper.slug)
        if site is None:
            session.add(
                Site(
                    slug=scraper.slug,
                    name=scraper.name,
                    base_url=scraper.base_url,
                    description=scraper.description,
                    requires_browser=scraper.requires_browser,
                    scan_interval_minutes=scraper.default_interval_minutes,
                    enabled=True,
                    is_available=True,
                )
            )
            added += 1
            log.info("Registered new site: %s", scraper.slug)
        else:
            # Descriptive fields track the code; operator settings do not.
            site.name = scraper.name
            site.base_url = scraper.base_url
            site.description = scraper.description
            site.requires_browser = scraper.requires_browser
            site.is_available = True

    # A site whose scraper was removed keeps its rows and history, but cannot
    # be scanned and is shown as unavailable in the admin UI.
    slugs = set(available_slugs())
    retired = 0
    for slug, site in existing.items():
        if slug not in slugs and site.is_available:
            site.is_available = False
            retired += 1
            log.warning("Site %s has no registered scraper; marked unavailable", slug)

    session.commit()
    return added, retired


def seed_password_differs(user: User, config: Config) -> bool:
    """Whether the configured seed password would not sign this account in.

    Used only to decide whether to print a hint; a mismatch is not an error.
    """
    from ..security import verify_password

    if not config.admin.password:
        return False
    return not verify_password(config.admin.password, user.password_hash, config)


def ensure_admin(session: Session, config: Config | None = None) -> User | None:
    """Create the initial admin account from the config file, once.

    Runs only when there is no admin at all, so editing ``admin.password`` later
    does not silently reset a live account, and a rotated config file cannot
    resurrect a deleted administrator.
    """
    config = config or get_config()
    existing_admin = (
        session.execute(select(User).where(User.role == UserRole.ADMIN)).scalars().first()
    )
    if existing_admin is not None:
        return None

    seed = config.admin
    if not seed.password:
        log.error(
            "No admin account exists and admin.password is not set in %s — "
            "the application cannot be signed into. Set it and restart.",
            config.source_path or "the configuration file",
        )
        return None

    # A username taken by a normal user must not be silently promoted.
    clash = session.execute(select(User).where(User.username == seed.username)).scalars().first()
    if clash is not None:
        log.error(
            "Cannot seed the admin account: username %r already belongs to a " "non-admin user.",
            seed.username,
        )
        return None

    user = User(
        username=seed.username,
        email=seed.email,
        full_name="Administrator",
        password_hash=hash_password(seed.password, config),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.flush()
    session.add(EmailPreference(user_id=user.id))
    session.commit()
    log.warning(
        "Seeded initial admin account %r from the configuration file. Sign in and "
        "change the password, then clear admin.password from the config.",
        seed.username,
    )
    return user


def initialize(config: Config | None = None) -> None:
    """Everything that must happen before the app serves its first request."""
    from ..database import session_scope

    config = config or get_config()
    config.ensure_directories()
    create_schema(config)
    with session_scope() as session:
        seed_sites(session)
        ensure_admin(session, config)
