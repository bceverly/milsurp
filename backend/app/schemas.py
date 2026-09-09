"""Pydantic request/response models.

Every datetime leaves this API as ISO-8601 with an explicit ``Z``. Columns are
stored naive-but-UTC, so :func:`utc` re-attaches the timezone on the way out and
the browser has something unambiguous to convert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

from .models import ArmoryStatus, FirearmKind


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class UTCModel(BaseModel):
    """Base model that stamps every naive datetime as UTC when serializing."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _serialize_datetimes(self, value: Any) -> Any:
        if isinstance(value, datetime):
            aware = utc(value)
            # utc() only returns None for a None input, which isinstance
            # already excluded; the check keeps the type checker honest.
            if aware is not None:
                return aware.isoformat().replace("+00:00", "Z")
        return value


Username = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")]
#: Only a sane hard bound. The real minimum is `security.min_password_length`
#: and is enforced by security.validate_password, so the policy lives in one
#: place and a configured value of, say, 8 is not silently overridden here.
Password = Annotated[str, Field(min_length=1, max_length=1024)]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(UTCModel):
    access_token: str
    # Not a credential: this is the RFC 6750 token type.
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_at: datetime
    user: "UserOut"


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: Password


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserOut(UTCModel):
    id: int
    username: str
    email: str
    full_name: str | None = None
    role: Literal["admin", "normal"]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    @field_validator("role", mode="before")
    @classmethod
    def _enum_value(cls, value: Any) -> Any:
        return getattr(value, "value", value)


class UserCreate(BaseModel):
    username: Username
    email: EmailStr
    password: Password
    full_name: str | None = Field(default=None, max_length=128)
    role: Literal["admin", "normal"] = "normal"
    is_active: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=128)
    role: Literal["admin", "normal"] | None = None
    is_active: bool | None = None
    # Admin-initiated reset; the user's own change goes through /auth/password.
    password: Password | None = None


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------
class SiteOut(UTCModel):
    id: int
    slug: str
    name: str
    base_url: str
    description: str | None = None
    enabled: bool
    scan_interval_minutes: int
    requires_browser: bool
    is_available: bool
    last_scan_at: datetime | None = None
    last_success_at: datetime | None = None
    next_scan_at: datetime | None = None
    # Rolled up for the at-a-glance admin list.
    item_count: int = 0
    active_item_count: int = 0
    is_scanning: bool = False
    last_run: "ScanRunOut | None" = None
    #: Seconds until this site's host may be asked for anything again, or None
    #: when it is free. Every fetching process obeys this, so a site that is
    #: resting will not be scanned by the scheduler either — which is worth
    #: saying on the page rather than leaving somebody to wonder why nothing
    #: is happening.
    resting_seconds: int | None = None
    resting_reason: str | None = None


class SiteUpdate(BaseModel):
    enabled: bool | None = None
    # Five minutes is the floor: anything tighter is abusive to the vendor and
    # would overlap with the previous run on a browser-driven site.
    scan_interval_minutes: int | None = Field(default=None, ge=5, le=43_200)
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None


# ---------------------------------------------------------------------------
# Manufacturers
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The armory: models, calibers, and what an admin does to them
# ---------------------------------------------------------------------------
class CaliberOut(UTCModel):
    id: int
    name: str
    #: Every other way the trade writes the same cartridge, one per line.
    #: ".32 ACP" and "7.65mm Browning" are one round, and this is where that
    #: is said.
    aliases: str | None = None
    status: ArmoryStatus
    notes: str | None = None
    #: The listing titles a pending row was proposed from, so whoever is
    #: judging it can see what it came from.
    first_seen_in: str | None = None
    #: What it was folded into, when it was.
    merged_into: str | None = None
    #: How many listings currently carry this spelling, and how many models
    #: name it -- both are what a merge is about to move.
    item_count: int = 0
    model_count: int = 0


class CaliberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    status: ArmoryStatus = ArmoryStatus.PENDING
    notes: str | None = Field(default=None, max_length=4000)


class CaliberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    status: ArmoryStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)


class FirearmModelOut(UTCModel):
    id: int
    name: str
    aliases: str | None = None
    kind: FirearmKind | None = None
    #: Where the pattern comes from, spelled as the classifier spells it so
    #: that a model's answer and a title's answer land in the same bucket.
    country: str | None = None
    #: What it chambers. A list because a model built across decades is often
    #: chambered in more than one round: a Steyr M95 may be 8x50mmR or 8x56mmR.
    caliber_ids: list[int] = Field(default_factory=list)
    calibers: list[str] = Field(default_factory=list)
    #: Every firm that built one. A list because several is normal: the M1
    #: Carbine had nine, and a listing may name any of them or none.
    manufacturer_ids: list[int] = Field(default_factory=list)
    manufacturers: list[str] = Field(default_factory=list)
    wikipedia_url: str | None = None
    status: ArmoryStatus
    position: int
    enabled: bool
    notes: str | None = None
    first_seen_in: str | None = None
    merged_into: str | None = None
    #: How many stored listings this model currently matches.
    item_count: int = 0


class FirearmModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    kind: FirearmKind | None = None
    country: str | None = Field(default=None, max_length=64)
    caliber_ids: list[int] = Field(default_factory=list)
    manufacturer_ids: list[int] = Field(default_factory=list)
    wikipedia_url: str | None = Field(default=None, max_length=500)
    status: ArmoryStatus = ArmoryStatus.PENDING
    position: int = Field(default=1000, ge=0, le=100_000)
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=4000)


class FirearmModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    kind: FirearmKind | None = None
    country: str | None = Field(default=None, max_length=64)
    caliber_ids: list[int] | None = None
    manufacturer_ids: list[int] | None = None
    wikipedia_url: str | None = Field(default=None, max_length=500)
    status: ArmoryStatus | None = None
    position: int | None = Field(default=None, ge=0, le=100_000)
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ArmoryIds(BaseModel):
    """The rows an action applies to."""

    ids: list[int] = Field(min_length=1, max_length=500)


class ArmoryMerge(BaseModel):
    """Fold one row into another: "Mosin" into "Mosin-Nagant"."""

    source_id: int
    target_id: int


class ArmoryAction(UTCModel):
    """What an action did, in the terms the admin page reports it."""

    changed: int = 0
    #: Listings restamped as a side effect. A merge rewrites every listing
    #: carrying the old name, which is worth saying out loud.
    items_restamped: int = 0
    message: str = ""


class ArmorySummary(UTCModel):
    """How much is waiting on somebody, for the badge in the navigation."""

    models: int = 0
    calibers: int = 0
    manufacturers: int = 0

    @property
    def total(self) -> int:
        return self.models + self.calibers + self.manufacturers


class ArmoryKind(UTCModel):
    """One choice for the Kind selector, with the label to show for it."""

    value: str
    label: str
    #: Whether the browse page counts this as a handgun. Shown in the admin
    #: page so the effect of the choice is visible where it is made.
    is_handgun: bool


class ManufacturerOut(UTCModel):
    id: int
    name: str
    aliases: str | None = None
    #: How many models the armory says this firm built. The models themselves
    #: are rows there, each carrying all of its makers, rather than a block of
    #: text on the maker — which is what let "M1 Carbine" belong to nine firms
    #: without becoming nine M1 Carbines.
    model_count: int = 0
    position: int
    enabled: bool
    notes: str | None = None
    #: Awaiting approval or in production, exactly as for a model or a caliber.
    #:
    #: This was missing, and the admin page reads it: with no status in the
    #: payload every one of the fifty-one makers drew the "Awaiting approval"
    #: chip -- which is the fallback for a status it does not recognize -- and
    #: promoting them changed nothing visible, because they were approved
    #: already and the next payload still carried no status.
    status: ArmoryStatus = ArmoryStatus.APPROVED
    #: What it was folded into, when it was.
    merged_into: str | None = None
    #: The listing titles a pending row was proposed from.
    first_seen_in: str | None = None
    #: How many listings currently carry this name, so the admin page can show
    #: what an edit is about to affect.
    item_count: int = 0


class ManufacturerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    #: Approved by default, and deliberately unlike a caliber or a model.
    #:
    #: Those arrive pending because filling a form in is not the same as having
    #: checked it. A maker is different in one respect that decides it: saving
    #: one **re-files every listing it can reach and reports how many moved**,
    #: which is the whole point of the page. A pending maker matches nothing,
    #: so defaulting this to pending would make that number always zero and the
    #: feature silently useless.
    #:
    #: A maker a *scan* proposes is another matter and does arrive pending --
    #: see :func:`app.services.armory.propose_manufacturer`.
    status: ArmoryStatus = ArmoryStatus.APPROVED
    #: Other spellings, one per line. Matched as literal text, never as a
    #: pattern -- see app/services/manufacturers.py.
    aliases: str | None = Field(default=None, max_length=4000)
    position: int = Field(default=1000, ge=0, le=100_000)
    enabled: bool = True
    notes: str | None = Field(default=None, max_length=4000)


class ManufacturerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    status: ArmoryStatus | None = None
    position: int | None = Field(default=None, ge=0, le=100_000)
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ManufacturerWrite(UTCModel):
    """What an edit did, including what it cost the catalog."""

    manufacturer: ManufacturerOut | None = None
    #: Listings whose maker changed as a result. Reported because an edit to
    #: one row can silently rewrite hundreds of listings.
    listings_changed: int = 0


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------
class ScanRunOut(UTCModel):
    id: int
    site_id: int
    status: Literal["running", "success", "partial", "failed", "canceled"]
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    items_found: int
    items_new: int
    items_updated: int
    items_delisted: int
    price_changes: int
    price_drops: int
    images_downloaded: int
    error_message: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _enum_value(cls, value: Any) -> Any:
        return getattr(value, "value", value)


class ScanRunDetail(ScanRunOut):
    log: str | None = None
    site_name: str | None = None


class ScanStartResponse(BaseModel):
    scan_run_id: int
    site_id: int
    message: str


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
class PricePointOut(UTCModel):
    price: float
    currency: str
    observed_at: datetime


class PhotoOut(BaseModel):
    id: int
    position: int
    # Paths to the authenticated image endpoint; never filesystem paths.
    url: str
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None


class ItemOut(UTCModel):
    id: int
    site_id: int
    site_name: str | None = None
    url: str
    title: str
    category: str | None = None
    caliber: str | None = None
    country: str | None = None
    manufacturer: str | None = None
    condition: str | None = None
    #: The armory model this listing matched, when one did. The name to show,
    #: and the id because that is what a filter on it uses — a model renamed
    #: in the armory keeps its listings, which a name filter would not.
    model: str | None = None
    firearm_model_id: int | None = None
    is_rifle: bool
    is_pistol: bool
    is_bayonet: bool = False
    is_parts_kit: bool = False
    is_sold: bool
    is_active: bool
    current_price: float | None = None
    previous_price: float | None = None
    lowest_price: float | None = None
    currency: str
    first_seen_at: datetime
    last_seen_at: datetime
    price_changed_at: datetime | None = None
    delisted_at: datetime | None = None
    thumbnail_url: str | None = None
    price_drop: float | None = None
    #: The opening of the description, for the list view.
    #:
    #: Truncated here rather than in the browser: a page of 192 listings would
    #: otherwise carry 192 full descriptions, some of them a dealer's several
    #: paragraphs, to render two lines each.
    blurb: str | None = None


class ItemDetail(ItemOut):
    description: str | None = None
    photos: list[PhotoOut] = Field(default_factory=list)
    price_history: list[PricePointOut] = Field(default_factory=list)
    #: What the armory knows about the matched model, for the facts panel.
    #: Absent when nothing matched, which is most listings on most days.
    model_kind: str | None = None
    model_makers: list[str] = Field(default_factory=list)
    model_calibers: list[str] = Field(default_factory=list)
    model_reference_url: str | None = None


class FacetValue(BaseModel):
    value: str
    label: str | None = None
    count: int


class ItemFacets(BaseModel):
    sites: list[FacetValue] = Field(default_factory=list)
    categories: list[FacetValue] = Field(default_factory=list)
    #: The armory models the current results match. A filter on this is a
    #: filter on a fact somebody vouched for, rather than on a string a vendor
    #: happened to type — which is the whole difference from the others.
    models: list[FacetValue] = Field(default_factory=list)
    calibers: list[FacetValue] = Field(default_factory=list)
    countries: list[FacetValue] = Field(default_factory=list)
    manufacturers: list[FacetValue] = Field(default_factory=list)
    #: One entry per Type, plus an empty-string entry for "Anything". Counted
    #: over every other filter but not over the Type itself, so each says what
    #: choosing it would show rather than what the current choice already did.
    kinds: list[FacetValue] = Field(default_factory=list)
    total: int = 0


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int
    page: int
    per_page: int
    pages: int
    facets: ItemFacets | None = None


# ---------------------------------------------------------------------------
# Email preferences
# ---------------------------------------------------------------------------
class EmailPreferenceOut(UTCModel):
    enabled: bool
    frequency_hours: int
    include_new_items: bool
    new_items_per_site_limit: int
    include_price_drops: bool
    price_drops_per_site_limit: int
    minimum_price_drop: float
    skip_when_empty: bool
    #: None means the user has never chosen one, so the UI is free to offer
    #: the browser's own zone. Digest rendering falls back to UTC.
    display_timezone: str | None
    site_ids: list[int] = Field(default_factory=list)
    last_sent_at: datetime | None = None
    next_send_at: datetime | None = None


class EmailPreferenceUpdate(BaseModel):
    enabled: bool | None = None
    frequency_hours: int | None = Field(default=None, ge=1, le=8760)
    include_new_items: bool | None = None
    # Capped at 100: the point of the limit is to keep the email readable.
    new_items_per_site_limit: int | None = Field(default=None, ge=1, le=100)
    include_price_drops: bool | None = None
    price_drops_per_site_limit: int | None = Field(default=None, ge=1, le=100)
    minimum_price_drop: float | None = Field(default=None, ge=0, le=1_000_000)
    skip_when_empty: bool | None = None
    display_timezone: str | None = Field(default=None, max_length=64)
    # None leaves the selection alone; an empty list means "every site".
    site_ids: list[int] | None = None


#: What the email-limit dropdown offers, and the only values accepted.
#:
#: A fixed set rather than any number in a range: the control that sets it is a
#: select box, and a value it does not offer is one it cannot then show back --
#: it would render blank, which reads as "unset" for something that is very
#: much set. Nothing else in the application can write this field, so closing
#: the set here closes it everywhere.
#:
#: Mirrored by LIMITS in frontend/src/pages/SavedSearches.jsx.
SAVED_SEARCH_LIMITS = (5, 10, 20, 30, 50, 100)
SavedSearchLimit = Literal[5, 10, 20, 30, 50, 100]


class SavedSearchOut(UTCModel):
    id: int
    name: str
    #: The browse page's own query string, canonical. The UI navigates to
    #: ``/?<query>`` to run it, which is why nothing here needs to describe
    #: the filters themselves.
    query: str
    sort: str
    email_enabled: bool
    email_item_limit: int
    last_emailed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    #: How many listings it matches right now — the whole result set, not the
    #: email's capped view of it.
    match_count: int = 0


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str = Field(default="", max_length=2000)
    email_enabled: bool = False
    email_item_limit: SavedSearchLimit = 10


class SavedSearchUpdate(BaseModel):
    """Every field optional: the list page toggles email without resending the
    query, and the browse page re-saves a query without touching the email."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    query: str | None = Field(default=None, max_length=2000)
    email_enabled: bool | None = None
    email_item_limit: SavedSearchLimit | None = None


class EmailLogOut(UTCModel):
    id: int
    user_id: int
    username: str | None = None
    status: Literal["sent", "failed", "skipped"]
    sent_at: datetime
    subject: str | None = None
    new_item_count: int
    price_drop_count: int
    error_message: str | None = None
    #: Whether the message itself was kept, so the list can offer to show it
    #: without carrying fifty rendered digests to draw a table.
    has_body: bool = False

    @field_validator("status", mode="before")
    @classmethod
    def _enum_value(cls, value: Any) -> Any:
        return getattr(value, "value", value)


class EmailBodyOut(UTCModel):
    """One message, as it was sent."""

    id: int
    sent_at: datetime
    subject: str | None = None
    body_html: str | None = None
    body_text: str | None = None


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
class PolicyOut(BaseModel):
    """Rules the UI needs so it can validate before hitting the server."""

    password_min_length: int
    password_require_uppercase: bool = False
    password_require_lowercase: bool = False
    password_require_numeric: bool = False
    password_require_special: bool = False
    #: The active rules as readable phrases, derived server-side so the text
    #: shown to the user can never drift from what is actually enforced.
    password_requirements: list[str] = Field(default_factory=list)


class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str
    mode: str
    server_time: str


class SystemStatusOut(BaseModel):
    version: str
    mode: str
    config_path: str | None
    #: Where the data is. A file path under SQLite, a "postgresql://user@host:port/name" DSN under PostgreSQL.
    database_path: str
    database_engine: str = "sqlite"
    images_path: str
    image_bytes: int
    email_enabled: bool
    scheduler: dict[str, Any]
    counts: dict[str, int]


TokenResponse.model_rebuild()
SiteOut.model_rebuild()
