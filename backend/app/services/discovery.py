"""Reading candidate armory rows out of listings nobody has curated yet.

The armory only ever knew what the shipped seed file said and what an admin
typed. A scan read it and never wrote to it, so meeting a rifle the table had
never heard of recorded nothing at all -- and the "awaiting approval" queue
that the whole design is built around was filled by hand.

This is the other half. Every scan ends by reading what it just stored and
writing down the cartridges, firms and designations the armory cannot explain,
as *pending* rows. Nothing here decides anything: a pending row is inert until
somebody promotes it, which is exactly what makes it safe to propose from a
guess.

**The risk this module is designed around is not missing things. It is junk.**
A queue nobody reads is worse than no queue, and the way to get one is to
propose every capitalized word in a title. So each of the three has a rule
measured over the 2,014 stored listings before it was kept, and each rule is
tighter than the obvious version:

============  ===========================================================
Calibers      The classifier's own reading, which is either a name from a
              closed vocabulary or a well-formed cartridge like
              "10.35x22mm". Highest precision of the three by a distance:
              51 candidates over the catalog and no junk in them, because
              something already had to look like a cartridge.
Models        Designation *shapes* -- "Model 1873", "Type 99", "K98k",
              "No.4 Mk.I", "vz.24", "M91/30", "CZ75" -- taken only from a
              listing that is a firearm and that the armory cannot already
              match. Measured at 293 candidates, nearly all real.
Manufacturers The hardest by far, and the only one with a sightings
              threshold. A firm's name has no shape to recognize, so it is
              read positionally: the capitalized words immediately before a
              designation, which is how the trade writes it ("Bernardelli
              M1934", "Norinco Type 56"). Measured precision is around two
              in three even after the filters, so a candidate must appear
              in :data:`MIN_MAKER_SIGHTINGS` different listings before it is
              written down. A real firm that stocks a shop appears more than
              once; a mangled phrase usually does not.
============  ===========================================================

Every candidate is also checked against what is already known, so approving a
row is what stops it being proposed again -- including under another spelling,
which is the case that matters. "7.65mm Browning" stops being offered the
moment ".32 ACP" carries it as an alias.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Item
from . import armory, classify, manufacturers

#: How many different listings must name a maker candidate before it is
#: written down. Calibers and models are proposed on first sight; a firm's
#: name is a positional guess rather than a shape, so it has to corroborate.
MIN_MAKER_SIGHTINGS = 2

#: How many different listings must name the same maker-and-year before it is
#: written down as a model. Same reasoning as MIN_MAKER_SIGHTINGS and the same
#: number: a bare year is a positional guess rather than a shape, so it has to
#: corroborate. Over the stored catalog the threshold drops 207 one-off
#: candidates and keeps 92 covering 944 listings.
MIN_YEAR_SIGHTINGS = 2

#: A model designation as the trade writes one.
#:
#: **Case-sensitive on purpose**, with one exception noted below. The first
#: version of this was case-insensitive and the bare-initials branch immediately
#: matched "with 4" out of "Pistol with 4 magazines". Designations are
#: capitalized wherever they are written.
DESIGNATION = re.compile(
    r"""(?<![\w/.-])(?:
      # The prefix vocabulary is the one part of this read case-insensitively.
      # It is a closed list of literal words each anchored to a number, so
      # "MODEL 1917" cannot match anything a lowercase "model" would not --
      # and the vendors who write a whole title in capitals are the ones whose
      # listings are terse enough to need it. 106 listings gained a
      # designation from this, "MODELE 1950" and "MLE 1874" among them.
      # "Model *of* 1917" is how the American ordnance style writes it.
        (?i:Model|Mod\.|Modele|Modelo|Mle|Type|Pattern|Gewehr|Gew\.|Karabiner|Kar\.|wz\.?)
        \s*(?i:of\s*)?\d{1,4}(?:/\d{1,2}){0,2}[A-Za-z]?
      | (?:vz\.?|VZ)\s?\d{2}(?:/\d{2})?
      | No\.?\s?\d\s*M[kK]\.?\s*(?:[IVX]+|\d)
      | M\d{1,4}[A-Z]?\d?(?:/\d{1,2}){0,2}
      | K\d{2,3}[a-z]?
      # Three digits as well as two: the SIG P210 is 48 listings here and
      # P\.?\d{2} could not see it.
      | P\.?\d{2,3}
      # One letter and two or three digits -- the Mauser C96, the Walther P38,
      # the Walther G43. 98 C96s sat unlinked because the branch below wants
      # two letters. A serial is longer than three digits, and the trailing
      # guard rejects it.
      | [A-Z]\d{2,3}[A-Z]?
      # The space is the point: "DSM 34" and "KKW 34" are how the German .22
      # trainers are written, and "DSM-34" was the only form that matched.
      | [A-Z]{2,4}\s?-?\s?\d{1,3}[A-Z]?
      # A pattern year carrying its update -- "1896/11", "96/11", "06/24".
      # The slash is what makes it a designation rather than a date, so a bare
      # year is deliberately not here; see year_candidates.
      | \d{2,4}/\d{1,2}
    # A slash after the match means the match stopped too early: "WF BERN
    # 96/11" gave "BERN 96" until this was here, because the letters-and-digits
    # branch starts further left than the year branch and so wins. Every branch
    # that legitimately carries a slash consumes it itself.
    )(?![\w/-])""",
    re.X,
)

#: Things with a designation's shape that are not one. Each earned its place
#: against the live catalog: ".380 ACP 3.5\"" produced "ACP 3", and a boxed
#: pistol produced "NIB 2".
_NOT_A_DESIGNATION = frozenset(
    (
        "acp",
        "lr",
        "ga",
        "mm",
        "wcf",
        "smg",
        "nato",
        "wsm",
        "spl",
        "gen",
        "lot",
        "sku",
        "ser",
        "nib",
        "exc",
        "vg",
        "unf",
        "ffl",
        "oal",
        "ww",
        "ww1",
        "ww2",
        "wwi",
        "wwii",
        "us",
        "usa",
        "uk",
        "cr",
        # An ordinary English word carrying a number after it. These all came
        # from widening the letters-and-digits branch to allow a space, which
        # is what "DSM 34" and "KKW 34" needed and which also turned every
        # short capitalized word before a number into a designation: "COLT
        # COMMANDER ... FACTORY CASE 45 ACP" proposed "CASE 45", "FN (HERSTAL)
        # AUTO 22" proposed "AUTO 22" and "Pistol WITH 2 Magazines" proposed
        # "WITH 2".
        "auto",
        "box",
        "cal",
        "carb",
        "case",
        "co",
        "code",
        "line",
        # "no" is deliberately absent: the head of "No.4 Mk.I" is "No".
        "of",
        "sbs",
        "sxs",
        "with",
    )
)


#: What the trade writes about a gun, as opposed to who made it. Used only to
#: stop a maker candidate, so a word here is never lost from a designation.
_TRADE_WORDS = frozenset(
    (
        "original",
        "antique",
        "vintage",
        "rare",
        "scarce",
        "fine",
        "very",
        "good",
        "excellent",
        "fair",
        "poor",
        "nice",
        "surplus",
        "military",
        "police",
        # How a dealer labels the *shelf*, not the gun. These are capitalized,
        # they sit immediately before the maker, and nothing above stopped
        # them: five of eleven pending maker proposals were "LEO Trade-in
        # Armalite", "PD Trade Bushmaster", "Trade-In Daniel Defense", "Trade
        # Rock River" and "River Arms LAR-15". A police trade-in section is
        # the fastest-growing kind of vendor on this list, so the queue was
        # filling with names no firm has ever had.
        "leo",
        "pd",
        "trade",
        "trade-in",
        "trade-ins",
        "tradein",
        "used",
        "unissued",
        "refurbished",
        "midlength",
        "contract",
        "commercial",
        "semi",
        "auto",
        "automatic",
        "bolt",
        "action",
        "lever",
        "pump",
        "single",
        "double",
        "rifle",
        "rifles",
        "carbine",
        "carbines",
        "pistol",
        "pistols",
        "revolver",
        "revolvers",
        "shotgun",
        "shotguns",
        "musket",
        "muskets",
        "machine",
        "gun",
        "guns",
        "receiver",
        "barrel",
        "stock",
        "grips",
        "holster",
        "magazine",
        "mag",
        "round",
        "rounds",
        "caliber",
        "cal",
        "condition",
        "sniper",
        "target",
        "sporting",
        "training",
        "display",
        "inert",
        "deactivated",
        "dummy",
        "replica",
        "matching",
        "mismatched",
        "refurbished",
        "midlength",
        "arsenal",
        "refinished",
        "import",
        "marked",
        "unissued",
        "issued",
        "used",
        "new",
        "boxed",
        "minty",
        "pre",
        "ban",
        "post",
        "eligible",
        "elig",
        "collection",
        "private",
        "from",
        "with",
        "without",
        "and",
        "the",
        "for",
        "all",
        "early",
        "late",
        "model",
        "type",
        "pattern",
        "grade",
        "parts",
        "kit",
        "kits",
        "set",
        "sets",
        "straight",
        "pull",
        "flintlock",
        "percussion",
        "caplock",
        "era",
        "civil",
        "war",
        "world",
        "factory",
        "bring",
        "back",
        "deluxe",
        "gauge",
        "series",
        "wwi",
        "wwii",
        "ww1",
        "ww2",
        "ww",
        "anib",
        "nib",
        "mint",
        "configuration",
        # "of" is not part of a name, and reading it as one proposed the model
        # "OF 1917" from "U.S. MODEL OF 1917".
        "of",
        # A date is not a designation, and these are the words that say a
        # number is one. They stop the walk-back dead, so "Original Circa 1850
        # Belgian ... Pistol" offers neither a maker nor a pattern year.
        "circa",
        "ca",
        "dated",
        "dtd",
        "built",
        "made",
        "mfg",
        "mfr",
        "mfd",
        "manufactured",
        "production",
        "prod",
        "born",
    )
)

#: Words that make the year *after* them a date. The set above stops a name
#: being read leftward through one; this is the other side, "1971 MFR".
_A_DATE = frozenset(
    (
        "circa",
        "ca",
        "dated",
        "dtd",
        "built",
        "made",
        "mfg",
        "mfr",
        "mfd",
        "manufactured",
        "production",
        "prod",
        "year",
        "born",
        "vintage",
    )
)

#: Years a gun can be *named* for, as opposed to made in.
#:
#: Ordnance named a pattern for its year of adoption, and the practice had died
#: out by the end of the second war -- every later year in this catalog is a
#: date of manufacture ("Ruger Blackhawk ... 1970", "NORINCO MODEL 213 ... 1966
#: MFR", "BROWNING HI POWER ... 1971 MFR"). The lower bound is a century before
#: the oldest thing on the shelves.
_PATTERN_YEARS = range(1800, 1946)

#: A four-digit number standing on its own. Deliberately not a DESIGNATION
#: branch: a bare year is a date far more often than it is a name, and what
#: tells them apart is the words around it rather than the shape.
_BARE_YEAR = re.compile(r"(?<![\w/.-])(\d{4})(?![\w/-])")


@dataclass
class Discovered:
    """What one pass proposed, in the terms the scan log reports it.

    Distinct names rather than sightings. A scan meeting the same unknown
    cartridge in forty listings has found one thing, and a line saying it
    proposed forty calibers would be forty times wrong.

    ``added`` counts the rows that did not exist before, which is what changes
    the badge on the armory page. The name sets are wider than that: they
    include candidates already pending, which only picked up another sighting.
    """

    calibers: set[str] = field(default_factory=set)
    manufacturers: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    #: New rows per table, from the pending counts either side of the pass.
    added: dict[str, int] = field(default_factory=dict)

    @property
    def total_added(self) -> int:
        return sum(self.added.values())

    def summary(self) -> str:
        return ", ".join(
            f"{self.added.get(table, 0)} {label}"
            for table, label in (
                ("models", "model(s)"),
                ("calibers", "caliber(s)"),
                ("manufacturers", "manufacturer(s)"),
            )
        )


# ---------------------------------------------------------------------------
# Reading one listing
# ---------------------------------------------------------------------------
def _strip_noise(title: str, caliber: str | None) -> str:
    """The title with everything that is not a name taken out.

    Parentheses go first because that is where vendors put lot and SKU codes --
    "(L2026-10870)", "(FG389)" -- every one of which has a designation's shape.
    """
    text = re.sub(r"\([^)]*\)", " ", title or "")
    text = re.sub(r"(?i)\b(?:serial(?:\s*number)?|s/n|sku|lot)\b.*$", " ", text)
    if caliber:
        text = text.replace(caliber, " ")
    # Any remaining cartridge or measurement. "7.62x25mm" and "26.5mm" both
    # end in a designation-shaped fragment once the digits are split off.
    text = re.sub(r"[\d.]+\s*(?:[x×]\s*\d+)?\s*(?:mm|MM)\b", " ", text)
    text = re.sub(r'\b[\d.]+\s*(?:"|inch|in\b)', " ", text)
    return text


def _designations(text: str) -> Iterable[re.Match[str]]:
    for match in DESIGNATION.finditer(text):
        head = re.split(r"[\s.-]", match.group(0))[0].lower()
        if head in _NOT_A_DESIGNATION or match.group(0).lower() in _NOT_A_DESIGNATION:
            continue
        yield match


def model_candidates(session: Session, title: str, caliber: str | None) -> list[str]:
    """Designations in this title that could be a model."""
    found: list[str] = []
    for match in _designations(_strip_noise(title, caliber)):
        text = " ".join(match.group(0).split())
        # A cartridge is not a model. "GP11" has the shape and is the Swiss
        # service round, and it reached the queue before this line existed.
        if armory.canonical_caliber(session, text):
            continue
        if text not in found:
            found.append(text)
    return found


def _name_before(text: str, index: int) -> str:
    """The firm's name reading leftward from *index*, or "" if there is none.

    Shared by the two positional rules below, which walk back from a
    designation and from a pattern year respectively and want the same answer
    to "whose name is this".
    """
    words = re.findall(r"[A-Za-z][\w&.'+-]*", text[:index])
    take: list[str] = []
    for word in reversed(words):
        bare = word.strip(".'+-").lower()
        if not word[:1].isupper() or len(bare) < 2 or bare in _TRADE_WORDS:
            break
        # A nationality is not a firm. Asked of the word itself rather than
        # pattern-matched, so "Yugoslavian" and "Czechoslovakian" are
        # caught by the same list the classifier uses on titles.
        if classify.extract_country(word):
            break
        # Neither is a model number. A title naming two designations makes
        # this run twice, and the second run walks back over the first
        # one: "LEO Trade-In Armalite M15 16in ... AR15 Rifle" proposed
        # "Armalite" from the M15 and then "Armalite M15" from the AR15.
        # A firm's name does not contain a model designation, and the
        # existing fullmatch guard only caught a candidate that was
        # nothing else.
        if DESIGNATION.fullmatch(word):
            break
        take.append(word)
        if len(take) == 3:
            # Three, because two truncated "James River Armory" to "River
            # Armory" -- a name that is wrong rather than merely short.
            break
    return " ".join(reversed(take))


def maker_candidates(title: str) -> list[str]:
    """Capitalized words immediately before a designation.

    "Bernardelli M1934", "Norinco Type 56", "Grendel P.30" -- maker then
    designation is how the trade names a gun, and it is the only positional
    signal here strong enough to be worth acting on. A leading-capitals rule
    was tried first and measured at about half junk: it proposed "U.S.",
    "Ben's", "ANIB" and "Vietnam Bring-Back Chinese" as firms.
    """
    text = _strip_noise(title, None)
    found: list[str] = []
    for match in _designations(text):
        name = _name_before(text, match.start())
        if name and not DESIGNATION.fullmatch(name) and name not in found:
            found.append(name)
    return found


def year_candidates(title: str, caliber: str | None) -> list[str]:
    """Maker-and-pattern-year designations: "WF BERN 1911", "DWM 1906".

    The Swiss, Swedish and Luger trades name a gun by the year its pattern was
    adopted and nothing else, so a whole shelf of listings reads "CARL GUSTAFS
    1896" or "DWM 1900" -- 944 of them here -- and :data:`DESIGNATION` cannot
    see any of it, because a bare four-digit number has no shape that tells it
    from a date. So this rule is context rather than shape, and it is the
    loosest thing in the module:

    * the year must be one a gun could be *named* for -- see _PATTERN_YEARS;
    * a firm's name must sit immediately to its left, by the same walk-back
      the maker rule uses, which is what stops "Built 1966" and "Circa 1850";
    * no date word may follow it, which is what stops "1971 MFR";
    * and the same name must turn up in MIN_YEAR_SIGHTINGS listings.

    The maker is kept in the proposed name on purpose. A bare "1911" would
    match every Colt automatic in the catalog, and "1896" would match a serial
    number; "WF BERN 1911" matches the listings it was read from and nothing
    else, which is the right thing for a row somebody still has to approve.
    """
    text = _strip_noise(title, caliber)
    found: list[str] = []
    for match in _BARE_YEAR.finditer(text):
        if int(match.group(1)) not in _PATTERN_YEARS:
            continue
        following = re.match(r"\s*([A-Za-z]+)", text[match.end() :])
        if following and following.group(1).lower() in _A_DATE:
            continue
        maker = _name_before(text, match.start())
        name = f"{maker} {match.group(1)}" if maker else ""
        if name and name not in found:
            found.append(name)
    return found


# ---------------------------------------------------------------------------
# A whole pass
# ---------------------------------------------------------------------------
def discover(session: Session, items: Iterable[Item]) -> Discovered:
    """Propose what these listings name and the armory cannot explain.

    Everything proposed arrives pending, so this is safe to run at the end of
    every scan: it records questions, and answering them is somebody's job
    rather than this function's.
    """
    found = Discovered()
    before = armory.pending_counts(session)
    # Keyed by the lowercased name so two spellings corroborate each other,
    # holding the first spelling seen and the titles it came from.
    maker_sightings: dict[str, tuple[str, list[str]]] = {}
    # Same shape, for the pattern-year rule -- see year_candidates.
    year_sightings: dict[str, tuple[str, list[str]]] = {}

    for item in items:
        title = item.title or ""
        if not title:
            continue

        caliber = item.caliber or classify.extract_caliber(title, item.description)
        if (
            caliber
            and not armory.canonical_caliber(session, caliber)
            and armory.propose_caliber(session, caliber, title) is not None
        ):
            found.calibers.add(caliber)

        # Models and makers are only read out of something that is a gun. A
        # bayonet listing names the rifle it fits, and proposing that rifle's
        # designation from it teaches the armory nothing it can trust.
        if not (item.is_rifle or item.is_pistol):
            continue

        if not armory.match(session, title).model:
            named = model_candidates(session, title, caliber)
            for name in named:
                if armory.propose_model(session, name, title) is not None:
                    found.models.add(name)
            # Only where nothing with a designation's shape was found. A
            # listing that says "M91/30" has already answered the question,
            # and reading a year out of it as well would propose the date it
            # was made alongside the name it goes by.
            if not named:
                for name in year_candidates(title, caliber):
                    year_sightings.setdefault(name.lower(), (name, []))[1].append(title)

        if not manufacturers.registry(session).extract(title):
            for name in maker_candidates(title):
                maker_sightings.setdefault(name.lower(), (name, []))[1].append(title)

    _propose_corroborated(
        session, year_sightings, found.models, MIN_YEAR_SIGHTINGS, armory.propose_model
    )
    _propose_makers(session, maker_sightings, found)

    # Counted from the tables rather than from what was appended, because a
    # candidate that was already pending is not a new row and must not be
    # reported as one.
    session.flush()
    after = armory.pending_counts(session)
    found.added = {table: max(after.get(table, 0) - count, 0) for table, count in before.items()}
    return found


def _propose_makers(
    session: Session, sightings: dict[str, tuple[str, list[str]]], found: Discovered
) -> None:
    """Write down the corroborated maker candidates -- see MIN_MAKER_SIGHTINGS."""
    _propose_corroborated(
        session, sightings, found.manufacturers, MIN_MAKER_SIGHTINGS, armory.propose_manufacturer
    )


def _propose_corroborated(
    session: Session,
    sightings: dict[str, tuple[str, list[str]]],
    into: set[str],
    threshold: int,
    propose: Callable[[Session, str, str], object | None],
) -> None:
    """Write down the candidates seen in at least *threshold* listings."""
    for spelling, titles in sightings.values():
        if len(titles) < threshold:
            continue
        row = None
        for title in titles[:threshold]:
            # Each sighting is offered so the pending row carries more than one
            # title, which is what somebody judging it actually reads.
            row = propose(session, spelling, title)
        if row is not None:
            into.add(spelling)
