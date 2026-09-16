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
    #: A six-digit authenticator code, or a recovery code. Optional because the
    #: sign-in is two exchanges: the first says whether one is wanted, and only
    #: an account with two-factor turned on is asked. Sending the password
    #: again with the code is what the second exchange does.
    totp_code: str | None = Field(default=None, max_length=64)


class TwoFactorRequired(BaseModel):
    """The answer to a first exchange for an account that wants a code.

    A 200 with this shape rather than a 401, because nothing has gone wrong:
    the password was right, and the server is asking for the other half. A 401
    would be indistinguishable from a wrong password to the page and to
    anything reading the logs.
    """

    two_factor_required: bool = True
    #: Said plainly so the prompt can offer both without a second link.
    detail: str = "Enter the code from your authenticator, or a recovery code."


class SessionOut(UTCModel):
    """One sign-in, as the person who owns it sees it."""

    id: int
    user_agent: str | None = None
    ip_address: str | None = None
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    expires_at: datetime
    #: Whether this is the session making the request. The list is useless
    #: without it -- "which one is this browser?" is the first thing anybody
    #: asks, and signing yourself out by accident is the obvious mistake.
    current: bool = False


class AuditEventOut(UTCModel):
    """One thing somebody did."""

    id: int
    action: str
    #: Kept beside the id so a deleted account's actions still say who.
    actor_name: str | None = None
    actor_id: int | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_label: str | None = None
    detail: str | None = None
    ip_address: str | None = None
    created_at: datetime | None = None


class TotpStart(BaseModel):
    """A freshly issued secret, shown once and never retrievable again."""

    secret: str
    #: The same secret in blocks, for reading off a screen and typing into a
    #: phone. Rendered rather than a QR code: a QR would mean a new frontend
    #: dependency for one screen, and on a phone the URI below opens the
    #: authenticator directly.
    secret_grouped: str
    otpauth_uri: str


class TotpConfirm(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class TotpStatus(BaseModel):
    enabled: bool = False
    confirmed_at: datetime | None = None
    recovery_codes_left: int = 0


class RecoveryCodesOut(BaseModel):
    """Shown once, when two-factor is turned on. There is deliberately no way
    to see them again: a list of second factors retrievable by anybody already
    signed in is not a second factor."""

    codes: list[str]


class TokenResponse(UTCModel):
    #: The session also arrives as an HttpOnly cookie, and that is what the
    #: browser uses. This field stays for scripts and for the test suite, which
    #: need a way to obtain a bearer token -- there is no other.
    #:
    #: **It is the one place the raw token is still visible to script**, and
    #: worth being straight about: the sign-in response can be read by an XSS
    #: that is already running and able to intercept it. What the cookie ends
    #: is the far larger exposure, a token sitting in `sessionStorage` for the
    #: whole session where any script could read it at any moment.
    access_token: str
    # Not a credential: this is the RFC 6750 token type.
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    #: Echoed back in X-CSRF-Token on unsafe requests. Not secret -- it is in a
    #: readable cookie too. It defends by being unreadable to *other* origins.
    csrf_token: str
    expires_at: datetime
    user: "UserOut"


class ResetLinkOut(BaseModel):
    """What an administrator is told after sending a link.

    The link itself is returned **only when the mail did not go** -- a
    self-hosted deployment with no SMTP configured would otherwise have a
    button that silently does nothing. It is not a leak: an admin can already
    set the password outright, so handing them the link grants no power they
    did not have, and it is the difference between a working feature and one
    that needs an email server first.
    """

    sent: bool
    #: Where it went, so the admin can see it is the address they expected.
    email: str
    expires_at: datetime
    #: Present only when `sent` is false.
    url: str | None = None
    detail: str


class PasswordResetRedeem(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: Password


class PasswordResetCheck(BaseModel):
    """Whether a link is still good, asked before the form is shown.

    So somebody who clicks an expired link is told so, rather than typing a new
    password twice and then being refused.
    """

    valid: bool
    username: str | None = None


class PasswordConfirm(BaseModel):
    """Prove it is still you, for a change that weakens the account."""

    password: str = Field(min_length=1, max_length=1024)


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


class PlannedSiteOut(BaseModel):
    """A vendor the roadmap intends to read but nothing can scan yet.

    Deliberately not a :class:`SiteOut` with the interesting fields blank: it
    has no id, no history and nothing to enable, and giving it the shape of one
    would invite the page to offer controls that cannot work.
    """

    slug: str
    name: str
    base_url: str
    platform: str
    blocker: str


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
    #: Off takes it out of matching without deleting it. See migration 0018:
    #: deleting is not how a row gets rejected here.
    enabled: bool = True


class CaliberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    status: ArmoryStatus = ArmoryStatus.PENDING
    notes: str | None = Field(default=None, max_length=4000)
    enabled: bool = True


class CaliberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    status: ArmoryStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None


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


class ArmoryPrimaryName(BaseModel):
    """Which of a row's own spellings should be its name.

    Only a spelling it already has. Inventing one here would be a rename in
    disguise, and a rename has to go through the duplicate check that stops two
    rows claiming one string.
    """

    name: str = Field(min_length=1, max_length=128)


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
    #: Where the firm is. The last and weakest answer to a listing with no
    #: country of its own -- see :attr:`app.models.Manufacturer.country`.
    country: str | None = None


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
    country: str | None = Field(default=None, max_length=64)


class ManufacturerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: str | None = Field(default=None, max_length=4000)
    status: ArmoryStatus | None = None
    position: int | None = Field(default=None, ge=0, le=100_000)
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=4000)
    country: str | None = Field(default=None, max_length=64)


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
    is_police_surplus: bool = False
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
    #: Where the pattern is from, as the armory row states it. Not the same
    #: question as the listing's own ``country`` beside it, which is where
    #: this particular gun is said to be from -- so both are shown, and a
    #: disagreement between them is information rather than a bug.
    model_country: str | None = None

    #: Whether *this* reader is watching it, and on what terms. Carried on the
    #: detail response rather than fetched separately: the star has to render
    #: in its true state on first paint, and a second request to find that out
    #: shows an empty star for a moment on a listing somebody is watching --
    #: which reads as having lost the watch.
    watched: bool = False
    watch_target_price: float | None = None
    watch_note: str | None = None
    watch_alert_immediately: bool = False
    #: Whether a person has vouched for the row. A pending row decided nothing
    #: about this listing, and saying so is the difference between "the armory
    #: thinks" and "the armory has been asked and not answered".
    model_status: str | None = None
    #: What the row says it chambers, separately from what this listing does.
    #: A model with several says nothing about which this one is, and the
    #: panel showing both is how that stops looking like a contradiction.
    model_notes: str | None = None


class SimilarListingOut(BaseModel):
    """One listing worth looking at beside the one on screen, and why.

    The reason travels with the row rather than grouping the response into
    sections: the page shows one list, and a row that cannot say why it is
    there is a recommendation the reader has to take on trust.
    """

    item: ItemOut
    #: The band it came in on -- "same_gun", "same_model", and so on.
    rung: str
    #: What to print for that band. Server-side, so the page and the service
    #: cannot drift on the wording the way two copies of a label do.
    label: str


class PricePositionOut(BaseModel):
    """Where one listing sits among the others of the same gun.

    The bar this draws is scaled by *rank*, not by price: surplus prices are
    skewed hard enough that a dollar axis puts nine listings in ten in its
    leftmost tenth. See services/pricing.py for the measurements.
    """

    count: int
    vendors: int
    low: float
    high: float
    q1: float
    median: float
    q3: float
    price: float
    #: How many peers this listing undercuts, as a percentage -- the ones
    #: dearer than it. A statistic, for the sentence; not where the marker
    #: goes. See services/pricing.py.
    cheaper_than: int
    #: Where the marker goes, 0 to 100: the rank across the whole bar, so the
    #: cheapest sits hard left and the dearest hard right.
    position: float
    model: str | None = None
    manufacturer: str | None = None
    caliber: str | None = None


class FacetValue(BaseModel):
    value: str
    label: str | None = None
    count: int


class ItemOverrideIn(BaseModel):
    """A correction to one listing.

    Every field optional, and an omitted one means "leave this as it is" while
    an empty one means "stop overriding this". The distinction matters: a form
    that posted every box on every save would assert an opinion about fields
    nobody touched.
    """

    caliber: str | None = None
    country: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    kind: str | None = None
    note: str | None = None


class ItemOverrideOut(UTCModel):
    caliber: str | None = None
    country: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    kind: str | None = None
    note: str | None = None
    #: Kept beside the id so the record survives the account being deleted.
    set_by_name: str | None = None
    updated_at: datetime | None = None


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
    #: The finer kind — revolver, carbine, percussion pistol. A second question
    #: from ``kinds``: that one picks which of the five buckets a listing is in,
    #: this one narrows within it. See Item.kind.
    forms: list[FacetValue] = Field(default_factory=list)
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


class WatchCreate(BaseModel):
    """Starting to watch a listing, or changing the terms of one.

    Both fields optional: starring with no target is the common case -- "keep
    an eye on this" -- and a target is the stronger statement somebody makes
    when they have decided what they will pay.
    """

    target_price: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=200)
    #: Mail me the moment it reaches the target rather than in the next digest.
    #: Meaningless without a target, and ignored when there is none.
    alert_immediately: bool = False


class WatchOut(UTCModel):
    """One watched listing, with the listing itself along for the ride.

    The item is nested rather than flattened: a watchlist row shows a price, a
    photo and a vendor, all of which are the *item's* and all of which change
    under the watch. Copying them up would be a second version of the truth.
    """

    id: int
    item: ItemOut
    target_price: float | None = None
    note: str | None = None
    alert_immediately: bool = False
    #: When this watch last triggered an immediate alert, so the page can say
    #: so rather than leaving somebody wondering whether it works.
    alerted_at: datetime | None = None
    created_at: datetime
    #: What the digest would say about it right now, or null for "nothing since
    #: your last email". Computed from the same rule the digest uses, so the
    #: page and the email cannot disagree about what counts as news.
    headline: str | None = None


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


class BackupSettingsOut(UTCModel):
    """UTCModel, not BaseModel: these columns are naive-but-UTC like every
    other datetime here, and without the serializer they reach the browser with
    no timezone at all -- which Date.parse reads as *local*, putting "last run"
    hours out on the very page whose job is to say when the last run was."""

    enabled: bool
    interval_hours: int
    keep: int
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_bytes: int | None = None


class BackupSettingsUpdate(BaseModel):
    """Every field optional: the page sends the one that changed."""

    enabled: bool | None = None
    interval_hours: int | None = None
    keep: int | None = None


class BackupSnapshotOut(BaseModel):
    name: str
    bytes: int
    taken_at: str
    #: Per file, not per configuration: a backup directory outlives a move
    #: between engines and afterwards holds both kinds.
    engine: str
    restore_hint: str


class BackupStateOut(BaseModel):
    settings: BackupSettingsOut
    #: Where they land. Shown, not editable -- see api/backups.py.
    directory: str
    engine: str
    restore_hint: str
    snapshots: list[BackupSnapshotOut]
    total_bytes: int
    #: The choices the page offers, so the two ends cannot disagree about them.
    interval_choices: list[int]
    keep_choices: list[int]


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
