"""Filling a listing's blank fields from better-described listings elsewhere.

A flyer read by OCR gives a title like ``JAP ARISIKA BBL REC .T-99, T-38`` and
no prose at all, so the caliber, the country and the maker are simply not on
the page. Another vendor sells the same rifle with a paragraph of description
and every field parsed. The words the two listings have in common -- "arisaka",
"t99" -- are enough to carry the second one's facts onto the first.

Only titles are compared. A title is the vendor's statement of what the thing
is; a description is prose about it, and on a flyer read by OCR it is prose
about whatever else happened to be printed nearby. Matching on descriptions was
tried against the live catalog and was not merely useless but confidently
wrong: a Russian 91/30 was declared a 6.5x52mm Carcano made by Remington, on
the strength of words the two paragraphs happened to share.

Four things keep this from being reckless:

* **It only fills gaps.** A value the vendor stated or the rules derived is
  never overwritten. This runs last, on what is still empty.
* **Common words carry no weight.** Every shared word is scored by how rare it
  is across the catalog, so "rifle" and "surplus" decide nothing and "gahendra"
  decides a great deal. A match has to clear a score, not a count.
* **It says nothing about what the listing is.** Type -- rifle, handgun,
  neither -- stays with the rules in :mod:`app.services.classify`, which have
  the vetoes. A sling for a Mauser shares every distinctive word with the
  Mauser and is still a sling.
* **Donor and recipient must agree on that type.** The same point from the
  other side: a rifle's caliber is no use to a shovel, and a listing that
  shares a word with a rifle without being one is nearly always a part or an
  accessory *for* it.

On a small catalog this finds very little, which is expected: it is worth more
with every vendor added, and worth nothing on the first one.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Item

#: Words too common in this trade to identify anything. Rarity scoring would
#: discount most of these on its own; they are listed because a catalog small
#: enough to make "rifle" look rare is exactly the case this has to survive.
_NOISE_WORDS = (
    # Grammar.
    "a an and are as at be by for from in into is it its of on or the this to with "
    "all any both each other same some such very only "
    # What everything on these pages is.
    "rifle rifles carbine carbines pistol pistols revolver revolvers shotgun shotguns "
    "gun guns firearm firearms handgun handguns musket muskets "
    "part parts kit kits set sets piece pieces lot lots pair pairs "
    "semi auto automatic assault arms grade "
    # How it is described.
    "barrel barrels stock stocks frame frames receiver receivers action actions bolt "
    "good fair poor excellent nice clean fine bore bores condition new old used "
    "serial number numbers model models type types cal caliber calibre "
    "live original surplus military army issue issued production "
    "unissued matching mismatched refurbished sporterized "
    "price sale sold shipping free"
)

NOISE = frozenset(_NOISE_WORDS.split())

#: Below this many characters a word is an abbreviation or a fragment, and the
#: ones worth having ("k98", "vz24", "c96") all clear it.
MIN_TOKEN_LENGTH = 3

#: A match has to be worth this much in summed rarity, and be made of at
#: least this many words.
#:
#: Both numbers were raised sharply after the first run against a real
#: catalog, which was not dry but wrong: it decided US T-handle trench shovels
#: were chambered in 6.5x52mm Carcano and made by Remington, and that a
#: Bulgarian AK-74 furniture set was made by Mauser. One moderately uncommon
#: word in common is not evidence that two listings are the same product, and
#: on a catalog of a few hundred rows one such word scores about 4.
#: A word carries 1.0 when it appears in exactly one listing and falls towards
#: 0 as it is shared more widely, so 1.5 is "two words, both nearly unique to this
#: product". The scale is normalized against the size of the catalog on
#: purpose: raw inverse document frequency grows as log(N), so a fixed
#: threshold over it silently loosens as the catalog fills up, which is the
#: opposite of what more data should buy.
MIN_SCORE = 1.5
MIN_SHARED_WORDS = 2

#: The shared words must also be this much of the *smaller* of the two
#: vocabularies. Rarity alone rewards a long description for containing more
#: chances to collide; this asks instead that the two listings be largely
#: about the same thing.
MIN_COVERAGE = 0.34

_WORD = re.compile(r"[a-z0-9]+(?:[./\-][a-z0-9]+)*")
_SEPARATORS = str.maketrans("", "", "./-")


def tokens(*texts: str | None) -> frozenset[str]:
    """The distinctive words in some text, with the trade's vocabulary removed.

    Separators inside a designation are dropped so the same gun spelled three
    ways lands on one token: ``T-99``, ``t.99`` and ``T99`` are all ``t99``,
    and ``7.62x39`` is ``76239`` wherever it is written.
    """
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for word in _WORD.findall(text.lower()):
            normalized = word.translate(_SEPARATORS)
            if len(normalized) < MIN_TOKEN_LENGTH or normalized in NOISE:
                continue
            if word in NOISE:  # "7.62" reads as noise before separators go
                continue
            found.add(normalized)
    return frozenset(found)


@dataclass(frozen=True)
class Entry:
    """One listing as a possible donor."""

    item_id: int
    site_id: int
    title: str
    words: frozenset[str]
    caliber: str | None
    country: str | None
    manufacturer: str | None
    #: What the rules made of it. A donor has to agree with the listing it is
    #: lending to: a rifle's caliber is no use to a shovel.
    kind: tuple[bool, bool]

    @property
    def has_anything_to_give(self) -> bool:
        return any((self.caliber, self.country, self.manufacturer))


@dataclass(frozen=True)
class Hint:
    """What one donor offers, and the evidence for it."""

    caliber: str | None
    country: str | None
    manufacturer: str | None
    source_id: int
    source_title: str
    score: float
    shared: tuple[str, ...]


#: The fields a hint can supply, in the order they are reported.
BORROWABLE = ("caliber", "country", "manufacturer")


class CatalogIndex:
    """Every described listing, indexed by the words that distinguish it.

    Built once and asked many times: the alternative is a query per listing,
    which on a re-derivation of the whole catalog is one query per row against
    every other row.
    """

    def __init__(self, entries: Iterable[Entry]) -> None:
        self._entries = [entry for entry in entries if entry.has_anything_to_give]
        self._by_word: dict[str, list[Entry]] = {}
        document_frequency: Counter[str] = Counter()
        for entry in self._entries:
            for word in entry.words:
                self._by_word.setdefault(word, []).append(entry)
                document_frequency[word] += 1

        total = len(self._entries)
        # Inverse document frequency, divided through by its own maximum so a
        # word that appears once scores 1.0 whatever the size of the catalog.
        # With fewer than two listings there is no evidence about rarity at
        # all, and every word scores nothing.
        self._total = total
        self._ceiling = math.log(total) if total > 1 else 0.0
        self._df = document_frequency

    def _rarity(self, others: int) -> float:
        """What a shared word is worth: how few *other* listings also have it.

        ``others`` is the number of listings that would match on this word
        besides the one asking. A word unique to one pair scores 1.0 whatever
        the size of the catalog, and one every listing uses scores nothing.

        Counting listings rather than occurrences is what makes a pair
        legible: plain document frequency scores a word shared by exactly two
        listings as though it were twice as common as a word nobody shares,
        which had two identical Arisaka titles failing to recognize each
        other.
        """
        if others < 1 or not self._ceiling:
            return 0.0
        return math.log(self._total / others) / self._ceiling

    def __len__(self) -> int:
        return len(self._entries)

    @classmethod
    def build(cls, session: Session, *, active_only: bool = True) -> CatalogIndex:
        query = select(Item)
        if active_only:
            query = query.where(Item.is_active.is_(True))
        return cls(
            Entry(
                item_id=item.id,
                site_id=item.site_id,
                title=item.title,
                words=tokens(item.title),
                caliber=item.caliber,
                country=item.country,
                manufacturer=item.manufacturer,
                kind=(bool(item.is_rifle), bool(item.is_pistol)),
            )
            for item in session.execute(query).scalars()
        )

    def suggest(
        self,
        title: str,
        *,
        kind: tuple[bool, bool] = (False, False),
        exclude_item_id: int | None = None,
        exclude_site_id: int | None = None,
        wanted: Iterable[str] = BORROWABLE,
    ) -> Hint | None:
        """The best-matching described listing, or ``None`` when nothing fits.

        ``exclude_site_id`` asks the rest of the market rather than the same
        vendor. A vendor who leaves the caliber blank on one listing tends to
        leave it blank on the near-identical one beside it, so their own
        catalog is the least likely place to find the answer -- and when two
        vendors independently describe the same rifle, the agreement is worth
        more than one vendor's habit.

        ``kind`` is the ``(is_rifle, is_pistol)`` the rules reached for the
        listing being filled, and a donor must match it. This is the cheapest
        of the guards and it catches the worst mistakes, because a listing
        that shares a word with a rifle without being one is almost always a
        part or an accessory *for* that rifle.
        """
        wanted = tuple(wanted)
        words = tokens(title)
        if not words:
            return None
        # A listing being filled is normally in the index too, and must not be
        # counted among the listings it is competing with.
        indexed = 1 if exclude_item_id is not None else 0

        scores: dict[int, float] = defaultdict(float)
        shared_count: Counter[int] = Counter()
        candidates: dict[int, Entry] = {}
        for word in words:
            weight = self._rarity(self._df.get(word, 0) - indexed)
            if not weight:
                continue
            for entry in self._by_word.get(word, ()):
                if entry.item_id == exclude_item_id or entry.site_id == exclude_site_id:
                    continue
                if entry.kind != kind:
                    continue
                if not any(getattr(entry, field) for field in wanted):
                    continue
                scores[entry.item_id] += weight
                shared_count[entry.item_id] += 1
                candidates[entry.item_id] = entry

        if not scores:
            return None

        best_id, best_score = max(scores.items(), key=lambda pair: (pair[1], -pair[0]))
        if best_score < MIN_SCORE or shared_count[best_id] < MIN_SHARED_WORDS:
            return None

        entry = candidates[best_id]
        shared = tuple(
            sorted(
                words & entry.words,
                key=lambda w: -self._rarity(self._df.get(w, 0) - indexed),
            )
        )
        if len(shared) / min(len(words), len(entry.words)) < MIN_COVERAGE:
            return None
        return Hint(
            caliber=entry.caliber,
            country=entry.country,
            manufacturer=entry.manufacturer,
            source_id=entry.item_id,
            source_title=entry.title,
            score=round(best_score, 2),
            shared=shared,
        )


@dataclass(frozen=True)
class Filled:
    """One field on one listing, and where its value came from."""

    item_id: int
    title: str
    field: str
    value: str
    source_title: str
    score: float


def fill_gaps(
    session: Session,
    *,
    site_id: int | None = None,
    same_site: bool = False,
) -> list[Filled]:
    """Fill empty caliber/country/manufacturer across the catalog.

    Returns one :class:`Filled` per value borrowed, so a caller can show its
    working. Nothing is overwritten, so running it twice changes nothing the
    second time.
    """
    index = CatalogIndex.build(session)
    filled: list[Filled] = []

    query = select(Item).where(Item.is_active.is_(True))
    if site_id is not None:
        query = query.where(Item.site_id == site_id)

    for item in session.execute(query).scalars():
        missing = [field for field in BORROWABLE if not getattr(item, field)]
        if not missing:
            continue
        hint = index.suggest(
            item.title,
            kind=(bool(item.is_rifle), bool(item.is_pistol)),
            exclude_item_id=item.id,
            exclude_site_id=None if same_site else item.site_id,
            wanted=missing,
        )
        if hint is None:
            continue
        for name in missing:
            value = getattr(hint, name)
            if value:
                setattr(item, name, value)
                filled.append(
                    Filled(
                        item_id=item.id,
                        title=item.title,
                        field=name,
                        value=value,
                        source_title=hint.source_title,
                        score=hint.score,
                    )
                )
    return filled


# ---------------------------------------------------------------------------
# What a caliber says about a maker
# ---------------------------------------------------------------------------
#: A great many surplus cartridges were designed for one rifle and chambered in
#: almost nothing else, so the caliber names the maker. Where the cartridge's
#: *name* says so — "8mm Mauser", "6.5x52mm Carcano" — reading it needs no
#: catalog at all, and manufacturers.extract() does that directly.
#:
#: This is for the rest: 7.62x54R is a Mosin-Nagant cartridge and does not say
#: so anywhere. Rather than a list written from memory, the catalog is asked.
#:
#: The thresholds are the whole design, because the obvious version of this is
#: dangerous. Measured against the catalog as it stood:
#:
#:     caliber              n   share  vendors  top maker
#:     7.62x54R            47    100%        2  Mosin-Nagant
#:     8mm Lebel           14    100%        1  Berthier
#:     7.7x58mm Arisaka     7    100%        2  Arisaka
#:     9mm                 30     93%        1  Luger
#:     .22 LR               7     86%        2  CZ
#:     .30 Carbine          3    100%        1  Marlin
#:
#: "High share wins" would have filed thirty-two M1 Carbines under Marlin on
#: the strength of three rows, and arbitrary 9mm pistols under Luger. Neither
#: sample size nor share separates those from the good ones. What separates
#: them is that 7.62x54R was made for one rifle and 9mm is made for everything,
#: which a catalog cannot see directly — but it can see that a general-purpose
#: cartridge does not command *unanimous* agreement across *independent*
#: vendors, because one dealer's stock reflects that dealer's buying.
#:
#: Hence: unanimous, two vendors or more, and enough rows to mean it. That
#: admits Mosin-Nagant and Arisaka and rejects every trap above. It also
#: rejects 8mm Lebel, which is correct but known from one vendor only — a false
#: negative worth having, and one that fixes itself as vendors are added.
MIN_CALIBER_SAMPLES = 5
MIN_CALIBER_VENDORS = 2


def makers_by_caliber(session: Session) -> dict[str, str]:
    """Calibers the catalog agrees name exactly one maker."""
    makers: dict[str, Counter[str]] = defaultdict(Counter)
    vendors: dict[str, set[int]] = defaultdict(set)
    rows = session.execute(
        select(Item.caliber, Item.manufacturer, Item.site_id).where(
            Item.is_active.is_(True),
            Item.caliber.is_not(None),
            Item.manufacturer.is_not(None),
        )
    ).all()
    for caliber, manufacturer, site_id in rows:
        makers[caliber][manufacturer] += 1
        vendors[caliber].add(site_id)

    agreed: dict[str, str] = {}
    for caliber, counter in makers.items():
        total = sum(counter.values())
        maker, count = counter.most_common(1)[0]
        if (
            count == total
            and total >= MIN_CALIBER_SAMPLES
            and len(vendors[caliber]) >= MIN_CALIBER_VENDORS
        ):
            agreed[caliber] = maker
    return agreed


def fill_makers_from_caliber(session: Session) -> list[Filled]:
    """Give a listing the maker its caliber implies, where nothing else did."""
    agreed = makers_by_caliber(session)
    if not agreed:
        return []

    filled: list[Filled] = []
    for item in session.execute(
        select(Item).where(
            Item.is_active.is_(True),
            Item.manufacturer.is_(None),
            Item.caliber.is_not(None),
        )
    ).scalars():
        maker = agreed.get(item.caliber or "")
        if not maker:
            continue
        item.manufacturer = maker
        filled.append(
            Filled(
                item_id=item.id,
                title=item.title,
                field="manufacturer",
                value=maker,
                source_title=f"every {item.caliber} in the catalog",
                score=1.0,
            )
        )
    return filled
