"""Pydantic request/response models.

Every datetime leaves this API as ISO-8601 with an explicit ``Z``. Columns are
stored naive-but-UTC, so :func:`utc` re-attaches the timezone on the way out and
the browser has something unambiguous to convert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator


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


class SiteUpdate(BaseModel):
    enabled: bool | None = None
    # Five minutes is the floor: anything tighter is abusive to the vendor and
    # would overlap with the previous run on a browser-driven site.
    scan_interval_minutes: int | None = Field(default=None, ge=5, le=43_200)
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None


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
    is_rifle: bool
    is_pistol: bool
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


class ItemDetail(ItemOut):
    description: str | None = None
    photos: list[PhotoOut] = Field(default_factory=list)
    price_history: list[PricePointOut] = Field(default_factory=list)


class FacetValue(BaseModel):
    value: str
    label: str | None = None
    count: int


class ItemFacets(BaseModel):
    sites: list[FacetValue] = Field(default_factory=list)
    categories: list[FacetValue] = Field(default_factory=list)
    calibers: list[FacetValue] = Field(default_factory=list)
    countries: list[FacetValue] = Field(default_factory=list)
    manufacturers: list[FacetValue] = Field(default_factory=list)
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
    display_timezone: str
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

    @field_validator("status", mode="before")
    @classmethod
    def _enum_value(cls, value: Any) -> Any:
        return getattr(value, "value", value)


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
    database_path: str
    images_path: str
    image_bytes: int
    email_enabled: bool
    scheduler: dict[str, Any]
    counts: dict[str, int]


TokenResponse.model_rebuild()
SiteOut.model_rebuild()
