"""What a collector checks first: import marks, matching numbers, the finish.

For surplus these set the price more than the model does. An all-matching,
unmarked K98k and a Century-stamped mixmaster are different objects at the
same model number, and the market bands, the hot deals and anybody browsing
were all treating them as one. The vendors say which is which -- in prose,
each in their own words -- and this reads it.

**Evidence, with the vendor's own words kept.** Each reading stores the phrase
it came from, so the page can quote it rather than assert a conclusion: "All
matching" beside "matching serial numbers except the bolt" would be a claim the
vendor did not make, and the quote is what lets a reader see that it was not.

**Three states each, and silence is the common one.** Measured over 9,970
active firearms on production (2026-09-30): 2,698 mention an import mark, 217
of them to say there is none; 2,680 say their numbers match and 931 describe a
mismatch; 667 describe a refinish or an arsenal refurbishment and 441 an
original finish. Everything else says nothing, and nothing is stored for it --
not "no", which would be a claim.

**The four ways prose goes wrong, and what each rule does about it.**

* *A denial contains the word.* "Not import marked" and "no import marks
  found" contain "import mark", so the words before a match are read for a
  negation, the way curio reads "not C&R" first.
* *Generic prose.* "Surviving examples, especially with matching numbers and
  original finish, are highly desirable" describes the model, not this gun. A
  match preceded by one of the words that introduce that kind of sentence --
  especially, examples, collectors, desirable, if, when -- is not read.
* *Hedging.* "May have been refinished at some point", "appears to be an old
  refinish", "whether the rifle has been refinished". The vendor is not
  saying, so neither is this.
* *The wrong part.* A refinished *stock* is not a refinished gun, and the
  finish question a collector asks is about the metal: a clause that names the
  wood is not read for the finish. A "non-matching bayonet" is an accessory
  that came with it, not a mismatched rifle.

**The condition grade** puts the vendor's word for the whole gun on one scale,
so "Excellent+" and "excellent" are one answer and a filter can ask for "very
good or better". It is read from a sentence stating the overall condition and
never from the ``condition`` column, which holds bore grades -- see
:func:`_overall_grade`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_ as sa_and
from sqlalchemy import or_ as sa_or

#: Where each quote is kept in ``Item.trait_quotes``.
IMPORT = "import"
NUMBERS = "numbers"
FINISH = "finish"
CONDITION = "condition"

#: The longest quote kept. A sentence is usually shorter; a run-on dealer
#: paragraph with no full stop is not, and the page shows this in a line.
QUOTE_CHARS = 140

_SENTENCE_END = re.compile(r"[.!?;\n]")

#: Words that introduce a sentence about the model rather than this gun.
_GENERIC = re.compile(
    r"\b(?:especially|particularly|examples|collectors?|desirable|sought|premium|"
    r"rarely|hard\s+to\s+find|look\s+for|if|when|whether|typically|usually)\b",
    re.IGNORECASE,
)

#: Words that mean the vendor is not saying.
_HEDGE = re.compile(
    r"\b(?:may|might|possibly|perhaps|probably|likely|suggest\w*|think|believe|"
    r"consistent\s+with|whether|can'?t\s+say|cannot\s+(?:say|confirm)|unsure)\b",
    re.IGNORECASE,
)

#: And for the finish, "appears" too. "All numbers appear matching" is a
#: dealer reading the numbers off the gun; "appears to be an old refinish" is
#: one guessing at its history.
_FINISH_HEDGE = re.compile(r"\b(?:appears?|seems?|looks\s+like)\b", re.IGNORECASE)

#: A denial just before the match: at most four words between, and none of
#: them a conjunction or a verb -- "no pitting and an import mark on the
#: barrel" is a mark, and "no visible import marks" or "no signs of having
#: been refinished" is not.
_NEGATION = re.compile(
    r"(?:\b(?:no|not|non|without|never|free\s+of|lacks?|lacking|absent|absence\s+of|"
    r"can'?t\s+find|cannot\s+find|could\s*n[o']t\s+find|did\s*n[o']t\s+find|nor)"
    r"|n[\u2019']t)"
    r"(?:[\s\-]+(?!(?:and|but|with|is|are|was|were|on|in)\b)[\w'\u2019]+){0,4}[\s\-]*$",
    re.IGNORECASE,
)

# -- import marks ------------------------------------------------------------

_IMPORT = re.compile(
    r"\bimport(?:er)?(?:'?s)?[\s\-]*(?:mark(?:s|ed|ings?)?|stamp(?:s|ed|ings?)?)\b",
    re.IGNORECASE,
)

# -- matching numbers --------------------------------------------------------

#: What came *with* the gun: a non-matching bayonet, holster or shoulder stock
#: is an accessory that does not match, not a gun that does not.
_ACCESSORY = (
    r"(?:\s+[\w\-]+){0,2}?\s+(?:bayonets?|holsters?|slings?|scabbards?|cases?|box(?:es)?|"
    r"targets?|shoulder\s+stocks?|cleaning\s+rods?|pouch(?:es)?)\b"
)

#: Anything that says a numbered part does not match. One is enough: "matching
#: bolt, mis-match magazine" is not an all-matching rifle.
_MISMATCH = re.compile(
    r"\bmis[\s\-]*match(?:ed|ing)?\b(?!" + _ACCESSORY + r")"
    r"|\bnon[\s\-]*matching\b(?!" + _ACCESSORY + r")"
    r"|\bnot\s+(?:all\s+)?matching\b"
    r"|\b(?:do|does)\s*(?:not|n't)\s+match\b"
    r"|\bforce[\s\-]*match(?:ed)?\b"
    r"|\bre[\s\-]*numbered\b"
    r"|\belectro[\s\-]*pencil(?:ed|led)?\b"
    r"|\bmostly\s+matching\b",
    re.IGNORECASE,
)

#: The ways a listing says the numbers match.
_ALL_MATCHING = re.compile(
    r"\ball[\s\-]+matching\b"
    r"|\ball\s+(?:visible\s+|main\s+|primary\s+|numbered\s+|original\s+)?(?:serial\s+)?"
    r"(?:numbers|parts|serials)\s+(?:are\s+|appear\s+(?:to\s+be\s+)?|bear\s+)?match(?:ing)?\b"
    r"|\b(?:serial\s+)?numbers?[\s\-]+(?:are\s+|appear\s+(?:to\s+be\s+)?)?matching\b"
    r"|\bnumbered\s+parts\s+(?:are\s+)?matching\b"
    r"|\bmatching[\s\-]+(?:serial[\s\-]+)?(?:numbers?|serials)\b"
    r"|\b(?:it|this\s+one|the\s+(?:gun|rifle|pistol|carbine|revolver))\s+is\s+(?:all\s+)?matching\b",
    re.IGNORECASE,
)

#: "...matching numbers except the bolt" is a mismatch said politely.
_EXCEPT = re.compile(
    r"^[^.;]{0,60}?\b(?:except|minus|but\s+(?:the|for)|other\s+than|save\s+for)\b"
    # "...all matching numbers in excellent condition except for the bore" is
    # an exception to the condition, not to the numbers.
    r"(?!\s+(?:for\s+)?(?:the\s+|some\s+)?(?:bore|finish|wear|condition|pitting|rust|"
    r"patina|bluing|dings?|scratch))",
    re.IGNORECASE,
)

#: An accessory named just *before* a mismatch -- "original box (mismatched
#: serial number)", "a shoulder board stock which does not match the pistol".
_ACCESSORY_BEFORE = re.compile(
    r"\b(?:bayonets?|holsters?|slings?|scabbards?|box(?:es)?|cases?|targets?|"
    r"shoulder\s+(?:\w+\s+)?stocks?|holster\s+stocks?)\b[^.;,]{0,25}$",
    re.IGNORECASE,
)

# -- finish ------------------------------------------------------------------

_REFINISHED = re.compile(
    r"\bre[\s\-]*finish(?:ed)?\b"
    r"|\bre[\s\-]*blu(?:ed|ing|e)\b"
    r"|\bre[\s\-]*park(?:erized|ed)\b"
    r"|\bre[\s\-]*nickel(?:ed|led)\b"
    r"|\brefurbished\b"
    r"|\barsenal\s+(?:refurbish(?:ed|ment)|re[\s\-]*work(?:ed)?|rebuil[dt]|reconditioned)\b",
    re.IGNORECASE,
)

_ORIGINAL = re.compile(
    r"\boriginal\s+(?:factory\s+)?(?:blued?\s+|parkerized\s+|nickel\s+|military\s+)?finish(?:es)?\b"
    r"|\bfactory\s+(?:original\s+)?finish\b",
    re.IGNORECASE,
)

#: A clause about the wood, whose finish is not the question.
_WOOD = re.compile(
    r"\b(?:stocks?|grips?|handguards?|wood|forend|fore-?end|butt\s*stock|lacquer\w*|"
    r"varnish\w*|shellac|cartouches?|panels?)\b",
    re.IGNORECASE,
)

_CLAUSE_BREAK = re.compile(r"[,;:()]|\band\b|\bwith\b|\bbut\b", re.IGNORECASE)

#: "retains about 93-94% of its original finish", "95%+ original finish",
#: "its original finish rates roughly 85%".
_PERCENT_BEFORE = re.compile(
    r"(\d{1,3})(?:\s*[-\u2013]\s*\d{1,3})?\s*%\s*\+?\s*(?:of\s+(?:its|the)\s+)?(?:original\s+)?"
    r"(?:factory\s+)?(?:blue|bluing|blueing|finish|nickel|parkerizing)",
    re.IGNORECASE,
)
_PERCENT_AFTER = re.compile(
    r"original\s+finish\s+(?:rates?|remaining|remains|of|is)?\s*"
    r"(?:roughly|about|approximately|around|some|nearly|at)?\s*(?:somewhere\s+between\s+)?"
    r"(\d{1,3})(?:\s*[-\u2013]\s*\d{1,3})?\s*%",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reading:
    """What a listing's text says, with the words it said it in.

    Each is True, False or None -- the vendor said so, said the opposite, or
    said nothing. ``refinished`` is True for a refinish and False where the
    vendor called the finish original.
    """

    import_marked: bool | None = None
    numbers_match: bool | None = None
    refinished: bool | None = None
    finish_percent: int | None = None
    #: The whole gun's condition on :data:`GRADES`' scale, where it was stated.
    grade: str | None = None
    quotes: dict[str, str] = field(default_factory=dict)

    @property
    def says_anything(self) -> bool:
        return any(
            value is not None
            for value in (
                self.import_marked,
                self.numbers_match,
                self.refinished,
                self.finish_percent,
                self.grade,
            )
        )


def _sentence(text: str, start: int, end: int) -> tuple[str, int]:
    """The sentence around a match, and where the match starts within it."""
    left = start
    while left > 0 and not _SENTENCE_END.match(text[left - 1]):
        left -= 1
    right = end
    while right < len(text) and not _SENTENCE_END.match(text[right]):
        right += 1
    return text[left:right], start - left


def _quote(text: str, start: int, end: int) -> str:
    sentence, offset = _sentence(text, start, end)
    sentence = " ".join(sentence.split())
    if len(sentence) <= QUOTE_CHARS:
        return sentence
    # Centered on the match, so a long sentence still shows the words that
    # were read -- and marked as cut at whichever end was.
    match_at = len(" ".join(text[start - offset : start].split()))
    begin = max(0, min(match_at - QUOTE_CHARS // 3, len(sentence) - QUOTE_CHARS))
    if begin > 0:
        # To the next word, so the quote does not open on half of one.
        space = sentence.find(" ", begin)
        begin = space + 1 if 0 <= space < match_at else begin
    cut = sentence[begin : begin + QUOTE_CHARS].strip()
    return ("…" if begin > 0 else "") + cut + ("…" if begin + QUOTE_CHARS < len(sentence) else "")


def _before(text: str, start: int) -> str:
    """The words before a match, back to the start of its sentence."""
    sentence, offset = _sentence(text, start, start)
    return sentence[:offset]


def _clause(text: str, start: int, end: int) -> str:
    """The clause a match sits in: its sentence, cut at commas and conjunctions."""
    sentence, offset = _sentence(text, start, end)
    left = [m.end() for m in _CLAUSE_BREAK.finditer(sentence, 0, offset)]
    right = _CLAUSE_BREAK.search(sentence, offset + (end - start))
    return sentence[(left[-1] if left else 0) : (right.start() if right else len(sentence))]


#: The metal, named between a wood word and a finish word, means the finish
#: is the metal's after all: "walnut stock, blued receiver refinished".
_METAL = re.compile(
    r"\b(?:metal|metalwork|blu(?:e|ed|ing)|finish|receiver|barrel|slide|frame|action|"
    r"pistol|rifle|carbine|revolver|gun|handgun)\b",
    re.IGNORECASE,
)


def _about_the_wood(text: str, start: int, end: int) -> bool:
    """Whether a finish word is about the stock or the grips.

    Two places to look. After it, in its own clause -- "the refinished stock".
    And before it, anywhere earlier in the sentence with no metal named in
    between -- "the stock has been sanded and refinished", "plain walnut
    stock, lightly refinished". "Original blued finish, walnut stock" is the
    metal: the wood comes after, in a clause of its own.
    """
    sentence, offset = _sentence(text, start, end)
    clause = _clause(text, start, end)
    after = clause[clause.lower().find(text[start:end].lower()) + (end - start) :]
    if _WOOD.search(after):
        return True
    earlier = list(_WOOD.finditer(sentence, 0, offset))
    if not earlier:
        return False
    between = sentence[earlier[-1].end() : offset]
    return not _METAL.search(between)


def _is_generic(text: str, start: int) -> bool:
    return bool(_GENERIC.search(_before(text, start)))


def _is_hedged(text: str, start: int, end: int) -> bool:
    sentence, _ = _sentence(text, start, end)
    return bool(_HEDGE.search(sentence))


#: "We do not see any signs that it was refinished": the denial is a clause
#: away from the word it denies, so it is looked for anywhere before it.
_NO_SIGN = re.compile(
    r"\b(?:no|not\s+see\s+any|n[\u2019']t\s+see\s+any|without\s+any|nor\s+any)\s+"
    r"(?:signs?|evidence|indications?|traces?)\b",
    re.IGNORECASE,
)


def _is_negated(text: str, start: int) -> bool:
    before = _before(text, start)
    return bool(_NEGATION.search(before) or _NO_SIGN.search(before))


def _import_marks(text: str) -> tuple[bool | None, str | None]:
    """Marked, unmarked, or not said -- and a mark anywhere wins.

    A listing can say both: "no import marks on the receiver; small import mark
    under the barrel". The law puts a mark somewhere on the gun, not
    everywhere, so one mark that is there answers the question.
    """
    denied: str | None = None
    for match in _IMPORT.finditer(text):
        if _is_generic(text, match.start()) or _is_hedged(text, match.start(), match.end()):
            continue
        if _is_negated(text, match.start()):
            denied = denied or _quote(text, match.start(), match.end())
            continue
        return True, _quote(text, match.start(), match.end())
    return (False, denied) if denied else (None, None)


def _numbers(text: str) -> tuple[bool | None, str | None]:
    """All matching, not all matching, or not said. Any mismatch wins."""
    for match in _MISMATCH.finditer(text):
        if _is_generic(text, match.start()) or _is_hedged(text, match.start(), match.end()):
            continue
        if _ACCESSORY_BEFORE.search(_before(text, match.start())):
            continue
        return False, _quote(text, match.start(), match.end())
    for match in _ALL_MATCHING.finditer(text):
        if _is_generic(text, match.start()) or _is_hedged(text, match.start(), match.end()):
            continue
        if _is_negated(text, match.start()):
            return False, _quote(text, match.start(), match.end())
        quote = _quote(text, match.start(), match.end())
        if _EXCEPT.search(text[match.end() :]):
            return False, quote
        return True, quote
    return None, None


def _finish(text: str) -> tuple[bool | None, str | None]:
    """Refinished, original, or not said -- about the metal."""
    original: str | None = None
    for match in _REFINISHED.finditer(text):
        start, end = match.start(), match.end()
        if _about_the_wood(text, start, end):
            continue
        if _is_generic(text, start) or _is_hedged(text, start, end):
            continue
        if _FINISH_HEDGE.search(_sentence(text, start, end)[0]):
            continue
        if _is_negated(text, start):
            # "Not refinished", "never been re-blued" -- which is the vendor
            # calling the finish original.
            original = original or _quote(text, start, end)
            continue
        return True, _quote(text, start, end)
    if original:
        return False, original
    for match in _ORIGINAL.finditer(text):
        start, end = match.start(), match.end()
        if _about_the_wood(text, start, end):
            continue
        if _is_generic(text, start) or _is_hedged(text, start, end):
            continue
        return False, _quote(text, start, end)
    return None, None


def _finish_percent(text: str) -> int | None:
    """How much of the original finish remains, where the vendor put a number on it.

    The lower end of a range, because "93-94%" promises 93. Only 5 to 100:
    anything else is a percentage of something other than a finish.
    """
    for pattern in (_PERCENT_BEFORE, _PERCENT_AFTER):
        for match in pattern.finditer(text):
            if _about_the_wood(text, match.start(), match.end()):
                continue
            value = int(match.group(1))
            if 5 <= value <= 100:
                return value
    return None


# ---------------------------------------------------------------------------
# The condition grade
# ---------------------------------------------------------------------------
#: Best first. The order a filter offers them in, and what "or better" means.
GRADES: tuple[str, ...] = ("like_new", "excellent", "very_good", "good", "fair", "poor")

GRADE_LABELS = {
    "like_new": "Like new",
    "excellent": "Excellent",
    "very_good": "Very good",
    "good": "Good",
    "fair": "Fair",
    "poor": "Poor",
}

#: Words, tried in order -- "very good" before "good", "near mint" before
#: "mint" -- against the vendor's word with its pluses taken off.
_GRADE_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:new|factory[\s\-]*new|like[\s\-]*new|unfired|as\s+new)$"), "like_new"),
    (re.compile(r"^(?:near[\s\-]+)?mint$"), "like_new"),
    (re.compile(r"^excellent$"), "excellent"),
    (re.compile(r"^very\s+good$"), "very_good"),
    (re.compile(r"^good$"), "good"),
    (re.compile(r"^fair$"), "fair"),
    (re.compile(r"^poor$"), "poor"),
)

#: "Poor to fair": a range is graded by its lower end, which is the promise.
_RANGE = re.compile(r"^(.+?)\s+to\s+(.+)$")


def grade_word(word: str | None) -> str | None:
    """One condition word on the common scale: "Excellent+" is "excellent"."""
    if not word:
        return None
    value = " ".join(word.lower().replace("+", " ").replace(" plus", " ").split())
    ranged = _RANGE.match(value)
    if ranged:
        known = [g for g in (grade_word(part) for part in ranged.groups()) if g]
        return max(known, key=GRADES.index) if known else None
    for pattern, answer in _GRADE_WORDS:
        if pattern.match(value):
            return answer
    return None


_WORD = (
    r"((?:(?:excellent|very\s+good|good|fair|poor)\s+to\s+)?"
    r"(?:excellent|very\s+good|good|fair|poor|like[\s\-]+new|near[\s\-]+mint|mint|"
    r"factory[\s\-]+new|new)(?:\s*\+|\s+plus)?)"
)

#: The three ways a listing states the whole gun's condition. "Overall
#: condition is good", "Condition: Excellent", "The rifle is in very good
#: overall condition" -- and the last only with a condition word after it, so
#: "in good shape" and "in good working order" are not read as grades.
_OVERALL = re.compile(
    r"\b(?:overall|general)\s+condition\s*(?:is|:|of|rates?|remains|-)?\s*(?:in\s+)?"
    r"(?:an?\s+)?" + _WORD + r"\b"
    r"|\bcondition\s*:\s*" + _WORD + r"\b"
    r"|\b(?:is|are|remains|in|overall)\s+(?:in\s+)?(?:an?\s+)?"
    + _WORD
    + r"\s+(?:overall\s+|original\s+|used\s+|surplus\s+|shooting\s+|collector\s+|"
    r"military\s+)?condition\b",
    re.IGNORECASE,
)

#: A sentence about a part or an accessory, whose condition is not the gun's:
#: "the bore is in very good condition", "includes a holster in good condition".
_PART = re.compile(
    r"\b(?:bores?|holsters?|slings?|magazines?|mags?|stocks?|grips?|box(?:es)?|cases?|"
    r"bayonets?|scabbards?|scopes?|mounts?|pouch(?:es)?|rifling|wood|leather|finish|"
    r"bluing|metal|lens(?:es)?|handguards?|cleaning\s+rods?|belts?|sights?|bolts?|"
    r"barrels?|muzzles?|springs?|screws?)\b",
    re.IGNORECASE,
)

#: How far in front of a condition statement its subject is looked for.
_SUBJECT_CHARS = 40


def _overall_grade(text: str) -> tuple[str | None, str | None]:
    """The whole gun's condition, where the vendor stated it, and their words.

    **Not the ``condition`` column.** Every value in it is a *bore* grade:
    the classifier reads one out of the description, and the scrapers that
    carry a vendor's own field (Simpson's "Bore", Legacy's "9/10, ME: 2, TE:
    1") carry the bore field -- the page already labels it "Bore condition".
    A bright bore is not an excellent rifle, so the grade is read from the one
    place a vendor states the whole gun: a sentence that says so. Measured over
    9,970 active firearms on production, 1,691 do, across 25 shops.
    """
    for match in _OVERALL.finditer(text):
        start, end = match.start(), match.end()
        sentence, offset = _sentence(text, start, end)
        # The subject is the few words in front: "the sight is in good
        # condition". Not the whole sentence -- a Simpson title is one long
        # sentence, and "...IN GOOD CONDITION MISSING ITS CLEANING ROD" is the
        # rifle's condition whatever else it mentions.
        if _PART.search(sentence[max(0, offset - _SUBJECT_CHARS) : offset + (end - start)]):
            continue
        if _is_generic(text, start) or _is_hedged(text, start, end):
            continue
        word = next(group for group in match.groups() if group)
        found = grade_word(word)
        if found:
            return found, _quote(text, start, end)
    return None, None


def read(title: str, description: str | None = None) -> Reading:
    """What this listing's own words say. Never raises; silence is a Reading."""
    text = "\n".join(part for part in (title, description) if part)
    if not text:
        return Reading()

    quotes: dict[str, str] = {}
    marked, quote = _import_marks(text)
    if quote:
        quotes[IMPORT] = quote
    matching, quote = _numbers(text)
    if quote:
        quotes[NUMBERS] = quote
    refinished, quote = _finish(text)
    if quote:
        quotes[FINISH] = quote
    overall, quote = _overall_grade(text)
    if quote:
        quotes[CONDITION] = quote
    return Reading(
        import_marked=marked,
        numbers_match=matching,
        refinished=refinished,
        finish_percent=_finish_percent(text),
        grade=overall,
        quotes=quotes,
    )


# ---------------------------------------------------------------------------
# Filtering the catalog
# ---------------------------------------------------------------------------
#: The browse filter's values, grouped: one choice per group or several, and
#: the groups combined -- "unmarked" *and* "all matching", never "or".
TRAITS: dict[str, tuple[str, str]] = {
    "unmarked": (IMPORT, "No import marks"),
    "import_marked": (IMPORT, "Import marked"),
    "all_matching": (NUMBERS, "All matching"),
    "not_matching": (NUMBERS, "Not all matching"),
    "original_finish": (FINISH, "Original finish"),
    "refinished": (FINISH, "Refinished"),
}


def firearm() -> Any:
    """The curio module's test, for the same reason: only a gun has these."""
    from ..models import Item

    return sa_and(
        sa_or(Item.is_rifle.is_(True), Item.is_pistol.is_(True)),
        Item.is_parts_kit.is_(False),
    )


def trait_clause(value: str) -> Any:
    """The SQL for one trait value. Raises on one nothing knows."""
    from ..models import Item

    column_and_answer = {
        "unmarked": (Item.import_marked, False),
        "import_marked": (Item.import_marked, True),
        "all_matching": (Item.numbers_match, True),
        "not_matching": (Item.numbers_match, False),
        "original_finish": (Item.refinished, False),
        "refinished": (Item.refinished, True),
    }
    if value not in column_and_answer:
        raise ValueError(f"unknown trait {value!r}")
    column, answer = column_and_answer[value]
    return sa_and(firearm(), column.is_(answer))


def traits_clause(values: list[str]) -> Any:
    """Several trait values: either within a group, all of the groups."""
    groups: dict[str, list[Any]] = {}
    for value in values:
        group, _label = TRAITS[value]
        groups.setdefault(group, []).append(trait_clause(value))
    return sa_and(*(sa_or(*clauses) for clauses in groups.values()))


def applies(is_rifle: bool, is_pistol: bool, is_parts_kit: bool) -> bool:
    """Whether a listing is a firearm, and so has these to show."""
    return bool((is_rifle or is_pistol) and not is_parts_kit)


# ---------------------------------------------------------------------------
# The backfill
# ---------------------------------------------------------------------------
def backfill(session: object, *, only_missing: bool = True, batch: int = 1000) -> dict[str, int]:
    """Read every stored listing and fill in the trait columns and the grade.

    Shared by the migration that adds the columns and by ``cli.py
    traits-backfill``, for the reason curio.backfill is: two readings of the
    same text drift the first time a pattern is tightened.

    ``only_missing`` reads only rows with no reading and no grade yet. A row
    whose text says nothing stays unread and is read again next time, which
    costs a regex pass and is how a tightened rule reaches it.
    """
    from sqlalchemy import select

    from ..models import Item

    counts = {"examined": 0, "import": 0, "numbers": 0, "finish": 0, "graded": 0}
    query = select(Item.id, Item.title, Item.description).order_by(Item.id)
    if only_missing:
        query = query.where(
            Item.import_marked.is_(None),
            Item.numbers_match.is_(None),
            Item.refinished.is_(None),
            Item.finish_percent.is_(None),
            Item.condition_grade.is_(None),
        )

    wrote = False
    pending: list[dict[str, object]] = []
    for item_id, title, description in session.execute(query):  # type: ignore[attr-defined]
        counts["examined"] += 1
        found = read(title or "", description)
        if not found.says_anything:
            continue
        counts["import"] += found.import_marked is not None
        counts["numbers"] += found.numbers_match is not None
        counts["finish"] += found.refinished is not None
        counts["graded"] += found.grade is not None
        pending.append(
            {
                "_id": item_id,
                "import_marked": found.import_marked,
                "numbers_match": found.numbers_match,
                "refinished": found.refinished,
                "finish_percent": found.finish_percent,
                "trait_quotes": found.quotes or None,
                "condition_grade": found.grade,
            }
        )
        if len(pending) >= batch:
            _write(session, pending)
            wrote = True
            pending = []
    if pending:
        _write(session, pending)
        wrote = True

    # Core writes go around the identity map; see curio.backfill.
    expire = getattr(session, "expire_all", None)
    if wrote and callable(expire):
        expire()
    return counts


def _write(session: object, rows: list[dict[str, object]]) -> None:
    from typing import cast

    from sqlalchemy import Table, bindparam, update

    from ..models import Item

    # Against the table, not the mapped class: this runs on an ORM Session and
    # on a migration's bare Connection. See curio._write.
    table = cast(Table, Item.__table__)
    session.execute(  # type: ignore[attr-defined]
        update(table).where(table.c.id == bindparam("_id")),
        rows,
    )


def apply(item: Any, trusted: bool) -> None:
    """Read one listing during a scan and store what it says.

    Overwritten each time rather than filled only when blank, as the curio
    evidence is: none of this is a value a vendor supplied that needs
    protecting, and a description that grows a sentence should be re-read.
    """
    found = read(item.title or "", item.description if trusted else None)
    item.import_marked = found.import_marked
    item.numbers_match = found.numbers_match
    item.refinished = found.refinished
    item.finish_percent = found.finish_percent
    item.trait_quotes = found.quotes or None
    item.condition_grade = found.grade
