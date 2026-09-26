"""What a vendor's email offers that its pages never show: codes and deadlines.

"10% off with code SWEDE10 through Sunday" changes no product page, so no scan
can see it. This reads it out of the email's text (``vendor_emails.body_text``,
URLs removed first) into an offer: the discount, the code, the terms, and when
it ends.

**Conservative on purpose.** Only explicit wording is read:

- a discount: "5% off", "$10 off", "free shipping";
- a code: a token of letters *and* digits, 6 to 24 long, following the word
  "code" within a sentence or two ("Use promo code: OSW2QQ550", "use on your
  first order DQV8UU7PYS541", "the code below … CF6LZLK82H");
- an end: "valid for 30 days", "72 hours only", or "through / until / ends /
  expires" followed by a date ("9/30", "October 1") or a weekday ("Sunday").

Anything vaguer leaves the end empty, and the offer simply stops being shown
after :data:`UNDATED_DAYS`. A code is never applied to a price: a price you get
only at checkout with a code is not the shelf price, and treating it as one
would corrupt the price bands and hot deals.

**Personal codes stay private.** A welcome email's code, or one "for your first
order", belongs to the notification account -- the shops send each subscriber
their own, often single-use. Those are marked ``personal``, shown only to
administrators, and never put in anything mailed to readers.

Measured on the shops' first mail (September 2026): Botach, IMA-USA and
Centerfire sent personal welcome codes; Officer Store a free-shipping code;
AIM Surplus a discount with no code in the email at all. Joe Salter's "Ending
Time: 10/1/2026 3:10 PM" lines are GunBroker auction ends with no discount, and
read as no offer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: An offer with no end date stops being shown this long after the email.
UNDATED_DAYS = 14

_URL = re.compile(r"\(?https?://\S+\)?")

_PERCENT = re.compile(r"(\d{1,2})\s*%\s*off", re.I)
_DOLLARS = re.compile(r"\$\s?(\d{1,4})\s*off", re.I)
_SHIPPING = re.compile(r"free\s+shipping", re.I)

#: The word that introduces a code, and how far after it the code may sit.
_CODE_WORD = re.compile(r"\bcode\b", re.I)
_CODE_REACH = 160
_CODE = re.compile(r"(?<![\w/=.-])([A-Za-z0-9][A-Za-z0-9-]{4,22}[A-Za-z0-9])(?![\w/=.-])")

_TERMS = (
    re.compile(r"first\s+(?:order|purchase)", re.I),
    re.compile(r"next\s+(?:order|purchase)", re.I),
    re.compile(r"orders?\s+(?:over\s+)?\$\s?\d+\+?", re.I),
    re.compile(r"regular[\s-]priced\s+items\s+only", re.I),
    re.compile(r"in[\s-]stock\s+only", re.I),
)

#: What makes a code this subscriber's own rather than the shop's sale code.
_PERSONAL = re.compile(
    r"first\s+(?:order|purchase)|next\s+(?:order|purchase)|welcome|thanks?\s+for\s+"
    r"(?:joining|subscribing|signing)",
    re.I,
)

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]

_END_WORD = r"(?:through|thru|until|till|ends?|ending|expires?|valid\s+(?:through|until))"
_VALID_FOR = re.compile(r"valid\s+for\s+(\d{1,3})\s+(day|hour)s?", re.I)
_HOURS_ONLY = re.compile(r"\b(\d{1,3})[\s-]hours?\s+only\b", re.I)
_END_NUMERIC = re.compile(
    rf"\b{_END_WORD}\s+(?:\w+day,?\s+)?(\d{{1,2}})/(\d{{1,2}})(?:/(\d{{2,4}}))?", re.I
)
_END_MONTH = re.compile(
    rf"\b{_END_WORD}\s+(?:\w+day,?\s+)?({'|'.join(_MONTHS)})\.?\s+(\d{{1,2}})", re.I
)
_END_WEEKDAY = re.compile(rf"\b{_END_WORD}\s+({'|'.join(_WEEKDAYS)})\b", re.I)


@dataclass(frozen=True)
class Offer:
    discount: str | None
    code: str | None
    terms: str | None
    personal: bool
    ends_at: datetime | None


def _plain(text: str) -> str:
    return " ".join(_URL.sub(" ", text or "").split())


def _discount(text: str) -> str | None:
    if found := _PERCENT.search(text):
        return f"{found.group(1)}% off"
    if found := _DOLLARS.search(text):
        return f"${found.group(1)} off"
    if _SHIPPING.search(text):
        return "free shipping"
    return None


def _code(text: str) -> str | None:
    """The first code-shaped token after the word "code": letters and digits
    both, so neither a word nor a number is taken for one."""
    for word in _CODE_WORD.finditer(text):
        window = text[word.end() : word.end() + _CODE_REACH]
        for token in _CODE.findall(window):
            if re.search(r"\d", token) and re.search(r"[A-Za-z]", token):
                return str(token)
    return None


def _terms(text: str) -> str | None:
    found = [match.group(0) for pattern in _TERMS for match in pattern.finditer(text)]
    return "; ".join(dict.fromkeys(" ".join(term.split()) for term in found)) or None


def _end_of_day(day: datetime) -> datetime:
    """The end of a shop's day, read as US Eastern and stated in UTC."""
    return datetime(day.year, day.month, day.day, 23, 59, tzinfo=UTC) + timedelta(hours=5)


def _ends_at(text: str, sent: datetime) -> datetime | None:
    if found := _VALID_FOR.search(text):
        amount = int(found.group(1))
        unit = timedelta(days=1) if found.group(2).lower() == "day" else timedelta(hours=1)
        return sent + amount * unit
    if found := _HOURS_ONLY.search(text):
        return sent + timedelta(hours=int(found.group(1)))
    if found := _END_NUMERIC.search(text):
        month, day, year = int(found.group(1)), int(found.group(2)), found.group(3)
        return _dated(sent, month, day, int(year) if year else None)
    if found := _END_MONTH.search(text):
        month = _MONTHS.index(found.group(1).lower()) + 1
        return _dated(sent, month, int(found.group(2)), None)
    if found := _END_WEEKDAY.search(text):
        wanted = _WEEKDAYS.index(found.group(1).lower())
        ahead = (wanted - sent.weekday()) % 7
        return _end_of_day(sent + timedelta(days=ahead))
    return None


def _dated(sent: datetime, month: int, day: int, year: int | None) -> datetime | None:
    if year is not None and year < 100:
        year += 2000
    try:
        when = datetime(year or sent.year, month, day, tzinfo=UTC)
    except ValueError:
        return None
    # "Through 1/5" in a December email means next January.
    if year is None and when < sent - timedelta(days=1):
        when = when.replace(year=when.year + 1)
    return _end_of_day(when)


def read(subject: str, body_text: str, sent: datetime) -> Offer | None:
    """The offer in one email, or None when it offers nothing."""
    text = _plain(f"{subject}. {body_text}")
    discount = _discount(text)
    code = _code(text)
    if discount is None and code is None:
        return None
    return Offer(
        discount=discount,
        code=code,
        terms=_terms(text),
        personal=bool(_PERSONAL.search(text)),
        ends_at=_ends_at(text, sent),
    )
