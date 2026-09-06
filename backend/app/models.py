"""ORM models.

Every ``DateTime`` column in this schema stores **UTC**. Nothing here is ever
localized; the API serializes timestamps as ISO-8601 with a ``Z`` suffix and the
browser converts them to the viewer's own timezone.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive column value so it can be compared with utcnow().

    Every datetime in this schema is UTC, but SQLite has no timezone type, so
    values read back from a column are naive while :func:`utcnow` is aware.
    Comparing the two raises ``TypeError`` — and if that happens inside a
    background loop that catches exceptions per iteration, the loop simply
    stops doing its job with nothing obviously broken. That is exactly how the
    scheduler quietly stopped running scheduled scans: the first scan of a site
    worked because ``next_scan_at`` was NULL, and every one after it compared a
    naive column against an aware now and threw.

    Use this on any column value before comparing or doing arithmetic with it.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    NORMAL = "normal"


class ScanStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # finished, but some pages or images failed
    FAILED = "failed"
    CANCELED = "canceled"


class EmailStatus(str, enum.Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"  # nothing to report, so no message was sent


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Users and access control
# ---------------------------------------------------------------------------
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(128))
    # Argon2id PHC string: algorithm, parameters and per-password salt included.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16), default=UserRole.NORMAL, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bumped whenever the password changes, which invalidates issued tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    email_preference: Mapped["EmailPreference | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    email_logs: Mapped[list["EmailLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


# ---------------------------------------------------------------------------
# Sites and scan history
# ---------------------------------------------------------------------------
class Site(Base, TimestampMixin):
    """A vendor whose listings we crawl.

    Rows are seeded from the scraper registry at startup; the admin-editable
    fields (enabled, scan_interval_minutes) are never overwritten by that seed.
    """

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Matches the registered scraper's slug; this is what binds a row to code.
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    scan_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    # True when the scraper drives a headless browser (Selenium) rather than
    # plain HTTP, which the admin UI surfaces as a warning.
    requires_browser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set when the registry no longer offers a scraper for this slug.
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    items: Mapped[list["Item"]] = relationship(back_populates="site", cascade="all, delete-orphan")
    scan_runs: Mapped[list["ScanRun"]] = relationship(
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="ScanRun.started_at.desc()",
    )


class Manufacturer(Base, TimestampMixin):
    """A maker's name, and the spellings that mean it.

    The list started life as a tuple of regular expressions in
    :mod:`app.services.classify`, which meant that recognizing one more maker
    was a code change, a review and a deploy — for a fact about the world that
    the person running the site knows and the programmer does not. It lives
    here instead so it can be edited from the admin pages.

    ``aliases`` holds the other spellings, one per line. They are matched as
    literal text on word boundaries, never as patterns: they come from a form,
    and a regular expression from a form is both a way to hang the process and
    a way to get a match nobody intended.

    ``position`` decides which rule is tried first, and it matters. "Mosin-
    Nagant" has to be tried before "Nagant" or every Mosin-Nagant in the
    catalog is filed under Nagant.
    """

    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The canonical spelling, and what gets written onto a listing.
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    #: Other spellings, one per line. "S&W" for Smith & Wesson, "P-08" for Luger.
    aliases: Mapped[str | None] = mapped_column(Text)
    #: Where this rule sits in the order rules are tried. Lower goes first.
    position: Mapped[int] = mapped_column(Integer, default=1000, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    #: A note for whoever edits this next.
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def spellings(self) -> list[str]:
        """Every string that means this maker, canonical name first."""
        found = [self.name.strip()]
        for line in (self.aliases or "").splitlines():
            alias = line.strip()
            if alias and alias.lower() not in {item.lower() for item in found}:
                found.append(alias)
        return found


class ScanRun(Base):
    """One execution of one site's scraper."""

    __tablename__ = "scan_runs"
    __table_args__ = (Index("ix_scan_runs_site_started", "site_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, native_enum=False, length=16),
        default=ScanStatus.RUNNING,
        nullable=False,
        index=True,
    )
    # "scheduled" | "manual" | "cli"
    trigger: Mapped[str] = mapped_column(String(16), default="scheduled", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    items_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_delisted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_changes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_drops: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    images_downloaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_message: Mapped[str | None] = mapped_column(Text)
    # Human-readable progress log, shown when drilling into a scan.
    log: Mapped[str | None] = mapped_column(Text)

    site: Mapped["Site"] = relationship(back_populates="scan_runs")
    prices: Mapped[list["PriceHistory"]] = relationship(back_populates="scan_run")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class Item(Base, TimestampMixin):
    """A single firearm (or accessory) listing on a vendor site."""

    __tablename__ = "items"
    __table_args__ = (
        # The scraper's stable per-site key drives idempotent upserts, so a
        # re-scrape updates rows in place instead of duplicating them.
        UniqueConstraint("site_id", "external_key", name="uq_item_site_key"),
        Index("ix_items_site_active", "site_id", "is_active"),
        Index("ix_items_first_seen", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)

    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text)
    # Vendor's own section, e.g. "Antiques", "Hand Select", "rifle".
    category: Mapped[str | None] = mapped_column(String(64), index=True)

    caliber: Mapped[str | None] = mapped_column(String(64), index=True)
    country: Mapped[str | None] = mapped_column(String(64), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(128), index=True)
    condition: Mapped[str | None] = mapped_column(String(64))
    is_rifle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_pistol: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_sold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # False once the listing stops appearing in a scan (de-listed).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    #: When a scraper last supplied this listing's *complete* record — the
    #: detail page, with its description and full gallery.
    #:
    #: This is what tells a scraper whether it still owes a detail fetch, and it
    #: has to be an explicit fact rather than an inference. Guessing it from
    #: "does the row have any photos yet" got Royal Tiger badly wrong: an
    #: interrupted scan left 210 listings holding photo *rows* with no files, a
    #: later scan read that as "already complete", skipped every detail page,
    #: and the catalog-grid thumbnail then replaced galleries of six and seven
    #: photos with one.
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When the vendor says the listing was posted, when the site tells us.
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Denormalized from price_history so list queries stay a single scan.
    current_price: Mapped[float | None] = mapped_column(Float, index=True)
    previous_price: Mapped[float | None] = mapped_column(Float)
    lowest_price: Mapped[float | None] = mapped_column(Float)
    highest_price: Mapped[float | None] = mapped_column(Float)
    price_changed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    site: Mapped["Site"] = relationship(back_populates="items")
    photos: Mapped[list["ItemPhoto"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ItemPhoto.position"
    )
    prices: Mapped[list["PriceHistory"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="PriceHistory.observed_at.desc()",
    )

    @property
    def price_drop_amount(self) -> float | None:
        if self.previous_price is None or self.current_price is None:
            return None
        delta = self.previous_price - self.current_price
        return delta if delta > 0 else None


class ItemPhoto(Base):
    """A photo stored on disk in the secure image directory.

    Each photo is kept at two resolutions, both generated locally while the scan
    runs: the original download (``filename``) and a down-sized thumbnail
    (``thumb_filename``). List views ask for the thumbnail so a grid of fifty
    listings stays light on a phone; the detail view asks for the full image.
    """

    __tablename__ = "item_photos"
    __table_args__ = (UniqueConstraint("item_id", "source_url", name="uq_photo_item_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Path relative to the configured image root, e.g. "royal-tiger/12/ab34.jpg".
    # Photos are never served as static files; they go through an authenticated
    # API endpoint that resolves this against the image root.
    filename: Mapped[str | None] = mapped_column(String(512))
    #: Down-sized copy, generated on our side during the scan.
    thumb_filename: Mapped[str | None] = mapped_column(String(512))
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(64))
    bytes: Mapped[int | None] = mapped_column(Integer)
    thumb_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)

    item: Mapped["Item"] = relationship(back_populates="photos")


class PriceHistory(Base):
    """Every price observation, so a listing's price over time is queryable.

    A row is written only when the observed price differs from the last one for
    that item, keeping the table proportional to real changes rather than to the
    number of scans.
    """

    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_item_observed", "item_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="SET NULL"), index=True
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )

    item: Mapped["Item"] = relationship(back_populates="prices")
    scan_run: Mapped["ScanRun | None"] = relationship(back_populates="prices")


# ---------------------------------------------------------------------------
# Email digests
# ---------------------------------------------------------------------------
class EmailPreference(Base, TimestampMixin):
    """Per-user digest settings."""

    __tablename__ = "email_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    frequency_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)

    include_new_items: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Hard per-site cap so a big scan cannot produce a hundred-item email.
    new_items_per_site_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    include_price_drops: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_drops_per_site_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    # Ignore trivial markdowns below this dollar amount.
    minimum_price_drop: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Don't email when there is nothing new to say.
    skip_when_empty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # IANA name used only to render times inside the email body, where there is
    # no browser to do the conversion. Storage stays UTC.
    #: NULL means "never chosen", so the UI can offer the browser's own zone
    #: rather than silently defaulting everyone to UTC. Readers fall back to
    #: UTC; only an explicit choice is stored.
    display_timezone: Mapped[str | None] = mapped_column(String(64))

    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_send_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    # Watermark: items first seen after this point are "new" in the next digest.
    last_digest_cutoff: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="email_preference")
    sites: Mapped[list["EmailPreferenceSite"]] = relationship(
        back_populates="preference", cascade="all, delete-orphan"
    )

    @property
    def site_ids(self) -> list[int]:
        return [link.site_id for link in self.sites]


class EmailPreferenceSite(Base):
    """Which sites a user wants included in their digest.

    No rows for a preference means every enabled site is included.
    """

    __tablename__ = "email_preference_sites"
    __table_args__ = (UniqueConstraint("preference_id", "site_id", name="uq_pref_site"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    preference_id: Mapped[int] = mapped_column(
        ForeignKey("email_preferences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    preference: Mapped["EmailPreference"] = relationship(back_populates="sites")
    site: Mapped["Site"] = relationship()


class EmailLog(Base):
    """Record of every digest attempt, for the admin's delivery view."""

    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus, native_enum=False, length=16), nullable=False, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(512))
    new_item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_drop_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="email_logs")
