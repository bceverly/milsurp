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
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
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
    saved_searches: Mapped[list["SavedSearch"]] = relationship(
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


class FirearmKind(str, enum.Enum):
    """What a model *is*, as a collector would name it.

    Finer than the rifle/handgun split the browse filter uses, because the
    ignition system is half of what a muzzleloader is: a flintlock pistol and
    a percussion revolver are different things to somebody who collects them,
    and both are "handgun" to the filter. :meth:`is_handgun` is where the two
    views meet, so the browse page keeps its five buttons.

    A carbine is its own form and not a short rifle. A Trapdoor Carbine and a
    Trapdoor Rifle are different guns, priced differently and collected
    separately, and the same is true either side of the cartridge era -- which
    is why the list is really *ignition* by *form* and carbine has a slot in
    each row. Without percussion_carbine a Sharps or a Burnside, of which the
    Civil War produced a great many, has nowhere to go but "rifle".

    Variants within a model -- the years, the arsenals, the marks -- are
    aliases on the model rather than kinds. "Model 1873 Trapdoor Carbine" and
    "1873 Carbine" are two ways of writing one thing; a carbine and a rifle
    are two things.
    """

    RIFLE = "rifle"
    CARBINE = "carbine"
    SHOTGUN = "shotgun"
    PISTOL = "pistol"
    REVOLVER = "revolver"
    FLINTLOCK_RIFLE = "flintlock_rifle"
    FLINTLOCK_CARBINE = "flintlock_carbine"
    FLINTLOCK_PISTOL = "flintlock_pistol"
    PERCUSSION_RIFLE = "percussion_rifle"
    PERCUSSION_CARBINE = "percussion_carbine"
    PERCUSSION_PISTOL = "percussion_pistol"
    PERCUSSION_REVOLVER = "percussion_revolver"

    @property
    def is_handgun(self) -> bool:
        return self in {
            FirearmKind.PISTOL,
            FirearmKind.REVOLVER,
            FirearmKind.FLINTLOCK_PISTOL,
            FirearmKind.PERCUSSION_PISTOL,
            FirearmKind.PERCUSSION_REVOLVER,
        }

    @property
    def is_long_gun(self) -> bool:
        return not self.is_handgun


class ArmoryStatus(str, enum.Enum):
    """Whether a reference row has been looked at by a person.

    Rows arrive two ways. An admin adds one deliberately, and it is approved
    from the start. A scan meets a name nothing in the table explains and
    proposes one, and that is *pending* until somebody says otherwise.

    A pending row is inert: it never fills in a listing's caliber and never
    decides what kind of thing a listing is. It is a question, not a fact, and
    the point of keeping it is that the question is asked once and then sits
    somewhere an admin can answer it -- rather than being asked again on every
    scan and answered by nobody.
    """

    PENDING = "pending"
    APPROVED = "approved"
    #: Kept, but folded into another row. See :attr:`Caliber.merged_into_id`.
    MERGED = "merged"


#: What a model chambers. A list for the same reason the makers are: a model
#: made across decades is often chambered in more than one round. The Steyr
#: M95 was built in 8x50mmR and rebarreled wholesale to 8x56mmR between the
#: wars, and both are correct for a rifle sold today as "an M95".
firearm_model_calibers = Table(
    "firearm_model_calibers",
    Base.metadata,
    Column(
        "firearm_model_id",
        ForeignKey("firearm_models.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("caliber_id", ForeignKey("calibers.id", ondelete="CASCADE"), primary_key=True),
)


#: Which model made which. A model has several makers far more often than the
#: one-maker-per-model table this replaces could say: the M1 Carbine was built
#: by Inland, Winchester, Rock-Ola, IBM, Underwood, Quality Hardware, National
#: Postal Meter, Standard Products and Saginaw, and a listing may name any of
#: them, or none.
firearm_model_manufacturers = Table(
    "firearm_model_manufacturers",
    Base.metadata,
    Column(
        "firearm_model_id",
        ForeignKey("firearm_models.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "manufacturer_id",
        ForeignKey("manufacturers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


def _spellings(name: str, aliases: str | None) -> list[str]:
    """The canonical name first, then each alias line, without repeats.

    Case-insensitive on the repeat check only: what is stored is what the
    admin typed, and a spelling that differs only in case is the same string
    to every matcher in the application.
    """
    found = [name.strip()]
    for line in (aliases or "").splitlines():
        alias = line.strip()
        if alias and alias.lower() not in {item.lower() for item in found}:
            found.append(alias)
    return found


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

    #: A maker a scan proposed, which nobody has confirmed yet, is pending and
    #: takes no part in matching. See :class:`ArmoryStatus`.
    status: Mapped[ArmoryStatus] = mapped_column(
        Enum(ArmoryStatus, native_enum=False, length=16),
        default=ArmoryStatus.APPROVED,
        nullable=False,
        index=True,
    )
    #: Set when this maker was folded into another -- "Mosin" into
    #: "Mosin-Nagant". The row stays so listings already carrying the old name
    #: can be followed to the new one.
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="SET NULL"), index=True
    )
    first_seen_in: Mapped[str | None] = mapped_column(Text)

    merged_into: Mapped["Manufacturer | None"] = relationship(remote_side="Manufacturer.id")
    models: Mapped[list["ManufacturerModel"]] = relationship(
        back_populates="manufacturer",
        cascade="all, delete-orphan",
        order_by="ManufacturerModel.name",
    )
    firearm_models: Mapped[list["FirearmModel"]] = relationship(
        secondary=firearm_model_manufacturers,
        back_populates="manufacturers",
        order_by="FirearmModel.name",
    )

    @property
    def model_names(self) -> list[str]:
        return [model.name for model in self.models]

    @property
    def spellings(self) -> list[str]:
        """Every string that means this maker, canonical name first."""
        return _spellings(self.name, self.aliases)


class ManufacturerModel(Base, TimestampMixin):
    """A model this maker made: "M44" for Mosin-Nagant, "ZB37" for CZ.

    Separate from :attr:`Manufacturer.aliases`, which is the same firm spelled
    differently. A model is a different kind of fact — "the thing named this was
    made by that firm" — and dealers name the model far more often than the
    maker: "RUSSIAN M44 CARBINES" and "WW2 RUSSIAN 91/30 RIFLES" are both
    Mosin-Nagants that never say Mosin, or Nagant, anywhere.

    Kept as rows rather than as more lines in the aliases box so that a model
    has somewhere to grow: its caliber, its type, the years it was made are all
    facts about a model rather than about a firm.
    """

    __tablename__ = "manufacturer_models"
    __table_args__ = (
        UniqueConstraint("manufacturer_id", "name", name="uq_model_per_manufacturer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    manufacturer_id: Mapped[int] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: As a dealer writes it. Matched as literal text on word boundaries, like
    #: an alias, and never as a pattern.
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    manufacturer: Mapped["Manufacturer"] = relationship(back_populates="models")


class Caliber(Base, TimestampMixin):
    """A cartridge, and every way the trade writes it.

    The aliases are the whole point. A dealer writes ".32 ACP" and another
    writes "7.65mm Browning" and they are the same round; ".30-06" and
    "7.62x63mm" are the same round; "7.62x54R" and "7.62 R" and "7,62x54R" are
    the same round. Until they are one row, a filter on either shows half the
    listings and a missing caliber cannot be filled in from a model at all.

    Matched as literal text on word boundaries, like a maker's aliases, and for
    the same reason: these come from a form.
    """

    __tablename__ = "calibers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The canonical spelling, and what gets written onto a listing.
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    #: The other spellings, one per line.
    aliases: Mapped[str | None] = mapped_column(Text)
    #: Pending by default. A row nobody has looked at is not production,
    #: whether it arrived from a scan, from the shipped armory file, or from
    #: an admin who has not finished filling it in. The column default in
    #: migration 0011 is the opposite, and deliberately: that one only ever
    #: applies to rows that existed before this table did, which were already
    #: curated.
    status: Mapped[ArmoryStatus] = mapped_column(
        Enum(ArmoryStatus, native_enum=False, length=16),
        default=ArmoryStatus.PENDING,
        nullable=False,
        index=True,
    )
    #: Set when this row was merged into another: ".30-06 Sprg" into ".30-06".
    #: The row stays so that a listing already carrying the old spelling can be
    #: followed to the new one, and so an admin can see what became of it.
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("calibers.id", ondelete="SET NULL"), index=True
    )
    #: Where the name was first seen, for a pending row an admin has to judge.
    first_seen_in: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    merged_into: Mapped["Caliber | None"] = relationship(remote_side="Caliber.id")

    @property
    def spellings(self) -> list[str]:
        """Every string that means this cartridge, canonical name first."""
        return _spellings(self.name, self.aliases)


class FirearmModel(Base, TimestampMixin):
    """A model of gun: what it is called, who made it, and what it chambers.

    This is the canonical list the rest of the application asks. A listing that
    matches a model here takes that model's kind and, when its own caliber
    could not be read, that model's caliber -- which is the whole reason for
    the table. "RUSSIAN M44 CARBINES" says neither Mosin-Nagant nor 7.62x54R
    and is both.

    It replaces ``manufacturer_models``, which could only give a model one
    maker. That was wrong for most of the interesting ones and it forced a
    second rule on top: a model two makers claimed was dropped from matching
    entirely, because picking whichever row came first would have been an
    accident of ordering. Here both makers are simply on the model, and the
    model still identifies the gun.
    """

    __tablename__ = "firearm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: As the trade names it: "M1 Carbine", "Model 1873 Trapdoor", "K98k".
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    #: Other spellings, one per line. "M1 Carbine" is also "US M1 Carbine",
    #: ".30 M1 Carbine" and "Carbine, Cal .30, M1".
    aliases: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[FirearmKind | None] = mapped_column(
        Enum(FirearmKind, native_enum=False, length=32), index=True
    )

    #: Where the pattern comes from: "Russia" for a Mosin-Nagant, whoever
    #: happened to build the individual rifle.
    #:
    #: A property of the *design*, not of the gun in front of you, and the
    #: distinction is the whole reason this is worth storing. A K98k assembled
    #: in Brno after the war is a German pattern made in Czechoslovakia; a
    #: listing that says so keeps what it says, because the armory only ever
    #: fills a blank here. What it answers is the case where nobody says
    #: anything at all -- "M1 GARANDS, EXC" names no country and is American,
    #: and until this existed the browse page's country filter simply had no
    #: opinion about it.
    #:
    #: Spelled the way :data:`app.services.classify.COUNTRY_PATTERNS` spells
    #: it, because the same column holds both and a filter offering both
    #: "Russia" and "USSR" would split one country in two.
    country: Mapped[str | None] = mapped_column(String(64), index=True)

    #: Pending by default, for the reason given on :class:`Caliber`.
    status: Mapped[ArmoryStatus] = mapped_column(
        Enum(ArmoryStatus, native_enum=False, length=16),
        default=ArmoryStatus.PENDING,
        nullable=False,
        index=True,
    )
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("firearm_models.id", ondelete="SET NULL"), index=True
    )
    #: Lower is tried first, for the same reason it is on Manufacturer:
    #: "Mosin-Nagant M44" has to be tried before "M44".
    position: Mapped[int] = mapped_column(Integer, default=1000, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    #: Where to read about it. Optional, and expected to stay that way for a
    #: long tail of models nobody has written an article about -- but for the
    #: ones that have it, it is the fastest way for whoever is approving a
    #: pending row to check what they are approving.
    #:
    #: Stored as the whole URL rather than an article title. Wikipedia is the
    #: obvious source and not the only one: a milsurp reference site or a
    #: collector's association page is often better on a variant, and a column
    #: called wikipedia_url that holds one of those would be a lie.
    wikipedia_url: Mapped[str | None] = mapped_column(String(500))
    #: The listing title a pending row was proposed from, so an admin judging
    #: it can see what it came from without going hunting.
    first_seen_in: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    calibers: Mapped[list["Caliber"]] = relationship(
        secondary=firearm_model_calibers,
        order_by="Caliber.name",
    )
    merged_into: Mapped["FirearmModel | None"] = relationship(remote_side="FirearmModel.id")
    manufacturers: Mapped[list["Manufacturer"]] = relationship(
        secondary=firearm_model_manufacturers,
        back_populates="firearm_models",
        order_by="Manufacturer.name",
    )

    @property
    def spellings(self) -> list[str]:
        return _spellings(self.name, self.aliases)

    @property
    def manufacturer_names(self) -> list[str]:
        return [maker.name for maker in self.manufacturers]

    @property
    def caliber_names(self) -> list[str]:
        return [cartridge.name for cartridge in self.calibers]

    @property
    def only_caliber(self) -> str | None:
        """The cartridge, when there is exactly one and so no choice to make.

        With several, the model genuinely does not say which one a particular
        rifle is -- an M95 may be 8x50mmR or 8x56mmR -- so it says nothing
        rather than picking. Same rule as :attr:`manufacturers`, and for the
        same reason: a guess dressed as a fact is worse than a blank.
        """
        return self.calibers[0].name if len(self.calibers) == 1 else None


class ScanRun(Base):
    """One execution of one site's scraper."""

    __tablename__ = "scan_runs"
    __table_args__ = (Index("ix_scan_runs_site_started", "site_id", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Which process is running this, so another one can tell a live scan from
    #: a row left behind by a crash. A scan used to claim a site in a
    #: process-local dictionary, which meant the CLI and the web application
    #: could not see each other's runs: both would scan the same vendor at the
    #: same time, at twice the agreed request rate, and both got 429ed for it.
    owner_host: Mapped[str | None] = mapped_column(String(128))
    owner_pid: Mapped[int | None] = mapped_column(Integer)

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
    #: Which armory model this listing matched, when one did.
    #:
    #: A foreign key rather than the name in text, unlike the maker and the
    #: caliber beside it. Those are free strings a vendor may have supplied;
    #: this is only ever set from a row somebody vouched for, so it can point
    #: at that row and carry everything on it -- the kind, the makers, the
    #: reference link -- rather than duplicating any of it.
    #:
    #: SET NULL rather than CASCADE: deleting a model from the armory is a
    #: statement about the armory, not a reason to delete a $4,000 rifle.
    firearm_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("firearm_models.id", ondelete="SET NULL"), index=True
    )
    is_rifle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_pistol: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Separate flags rather than one "kind", because a listing can be several
    #: of these at once: a parts kit is a firearm minus its serialized part, so
    #: "ENFIELD NO1 MK2 PARTS KITS" is a handgun and a parts kit both.
    is_bayonet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_parts_kit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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
    firearm_model: Mapped["FirearmModel | None"] = relationship()
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

    #: How many times this photo has been asked for and not arrived.
    #:
    #: A queued photo is a row with no ``filename``, so without a counter a URL
    #: that can never succeed is indistinguishable from one that has not been
    #: reached yet — and gets retried on every scan forever. The queue is
    #: ordered by this, so a dead row drifts to the back rather than occupying
    #: the per-scan budget ahead of photos that would work.
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: Why the last attempt failed, for whoever is wondering where the picture
    #: went. Cleared on success.
    last_error: Mapped[str | None] = mapped_column(Text)

    item: Mapped["Item"] = relationship(back_populates="photos")


class HostCooldown(Base):
    """A host that has told us to go away, and when it becomes polite to ask again.

    Per *host* rather than per site, because that is the unit a rate limiter
    actually works on: a vendor's pages and their uploads directory are usually
    the same host, and the CDN in front of both is the thing counting.

    Shared through the database because nothing else is shared. The scheduler,
    the CLI and a `make photos` run are separate processes, and a limit learned
    in one of them used to be unlearned the moment it exited.
    """

    __tablename__ = "host_cooldowns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    #: When it becomes reasonable to ask this host for something again.
    until: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    #: Consecutive refusals, which is what makes the wait grow. Reset by a
    #: request that succeeds.
    refusals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    first_refused_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_refused_at: Mapped[datetime | None] = mapped_column(DateTime)


class BackupSetting(Base, TimestampMixin):
    """How often the database is snapshotted, and how many are kept.

    **One row, id 1.** A schedule is a property of the installation, not of a
    user, and there is nothing to key it by.

    These three settings used to live in config.yaml. They moved here because
    an administrator is the person who should decide how often a backup is
    taken and how many to keep, and editing a YAML file on the server and
    restarting is not a thing an administrator should have to do to change a
    retention window. What stayed in config.yaml is ``backups.directory``:
    where files land on disk is an operator's decision about the machine, not
    an administrator's about policy, and a text box that can point the writer
    at any path is a worse idea than an unchangeable default.

    The values in config.yaml seed this row the first time it is created, so a
    deployment that had configured them keeps what it had.
    """

    __tablename__ = "backup_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Hours between snapshots. Measured against the newest file on disk rather
    #: than against a timer, so a process that restarts twice a day still
    #: produces one backup a day. See services.backup.is_due.
    interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    #: How many to keep. The oldest beyond this are deleted after each run.
    keep: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    #: What happened last time, so the admin page can say so without reading a
    #: log. Set by both the scheduler and the "Back up now" button.
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_bytes: Mapped[int | None] = mapped_column(Integer)


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
class SavedSearch(Base, TimestampMixin):
    """A named set of browse filters, optionally mailed every digest.

    **The query is stored as the browse page's own query string**, not as a
    column per filter. The filter set has grown four times already and a column
    each would mean a migration each time; this way "run this search" is a
    redirect and nothing more. It is canonicalized on the way in -- sorted,
    with the paging parameters dropped -- so two searches built by the same
    clicks in a different order are one search.

    It is *validated* on the way in too, by the same code the browse endpoint
    uses. A saved search is run unattended, and a row that has rotted into an
    unknown parameter would otherwise mail an empty result with nobody to see
    the error.
    """

    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    query: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    #: Also inside ``query``; kept here so the list page can show it and the
    #: digest can order by it without re-parsing.
    sort: Mapped[str] = mapped_column(String(32), nullable=False, default="newest")

    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    #: How many listings the email carries. The cap is on the *email* only:
    #: running the search from its own page returns everything it matches.
    email_item_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    last_emailed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped["User"] = relationship(back_populates="saved_searches")


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

    #: What was actually sent. Both parts, because they answer different
    #: questions: the HTML is the message as it arrived, and the text is the
    #: one worth reading in a table or searching through.
    #:
    #: NULL on a row written before this was recorded, and on a SKIPPED row
    #: where no message was ever built.
    body_html: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="email_logs")
