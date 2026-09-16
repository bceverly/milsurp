"""Vendor boilerplate, taken off the end of a description.

Every dealer ends listings the same way: how to send an FFL, what they will not
ship to California, when they take a card. It is true, it is theirs, and it is
the same paragraph on every listing they publish -- so it tells a reader nothing
about *this* rifle while pushing the part that does off the screen.

**Only from the end, and only whole sentences.** Boilerplate is appended; the
description proper comes first. Working backwards and stopping at the first
sentence that is not boilerplate means a sentence in the middle is never
touched, however much it looks like a policy -- "shipped to my FFL in 1962" is
part of a story somebody is telling about a gun.

**And never down to nothing.** Some dealers' entire description *is* a
compliance note: `Description **C&R FFL OK**` is 26 characters and every one of
them is useful, because C&R eligibility is a fact about the gun. A stripper that
turns that into an empty string has made the listing worse, so there is a floor
and the original is returned whenever the result would fall through it.

The rule throughout is that leaving boilerplate in is a small harm and cutting
a description short is a large one, so every judgment call here goes the same
way.
"""

from __future__ import annotations

import re

#: Sentence-enders, kept so the pieces can be put back together unchanged.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: What marks a sentence as the shop talking about itself rather than the gun.
#:
#: Each of these was read off the catalog rather than imagined: 1,387 active
#: listings carry an FFL notice, 336 a returns policy, 91 ordering
#: instructions. The phrasings are deliberately specific -- "we ship", not
#: "ship" -- because the loose version eats "this rifle shipped from Tula in
#: 1943".
_BOILERPLATE = re.compile(
    r"""
    \b(?:
        # Transfers and licensing, the commonest by a distance.
        (?:c\ ?&\ ?r\ +or\ +)?ffl\ +(?:is\ +)?(?:required|dealer|holder)
      | must\ +(?:be\ +)?(?:ship|transfer)(?:ped|red)?\ +(?:to|through)
      | transferred?\ +through\ +a\ +(?:valid\ +)?ffl
      | (?:upload|email|fax|send)\ +(?:us\ +|your\ +|a\ +)*(?:copy\ +of\ +)?
        (?:your\ +)?(?:licen[sc]e|ffl)
      # Ordering and payment.
      | (?:how\ +to\ +order|ordering\ +instructions|call\ +to\ +order)
      | (?:we|please)\ +(?:accept|visit|call|contact|email)\b
      | add\ +to\ +(?:cart|basket) | at\ +checkout
      # Shipping and restrictions.
      | (?:we|orders?)\ +ship\b | shipping\ +(?:is|charges?|restrictions?|costs?)
      | cannot\ +be\ +shipped\ +to | not\ +(?:available|legal)\ +(?:for\ +sale\ +)?in
      | subject\ +to\ +(?:state|change|all\ +)
      # Returns and disclaimers.
      | no\ +returns? | return\ +policy | all\ +sales\ +(?:are\ +)?final
      | ^disclaimer\b
      # Compliance.
      | 18\ +u\.?\ ?s\.?\ ?c | state\ +and\ +local\ +laws
      | comply\ +with\ +all | buyer\ +is\ +responsible\ +for
    )
    """,
    re.I | re.X,
)

#: A "DISCLAIMER:"-style heading, which introduces a block rather than a
#: sentence and is worth recognizing on its own.
_BLOCK_HEADING = re.compile(
    r"^\s*(?:disclaimer|note|important|please\s+note|shipping)\s*[:\-]", re.I
)

#: The same heading found *mid-text*, where it marks the point the shop stopped
#: describing the gun and started describing itself.
#:
#: Cutting *at* the marker rather than dropping the chunk containing it, and
#: that distinction is the whole reason this exists: dealers write condition
#: notes with no full stops -- "Light pitting on receiver Light grease on
#: barrel Visible and clean rifling DISCLAIMER: Firearms are subject to..." --
#: so the notes and the disclaimer arrive as a single sentence. Removing that
#: sentence removed the condition report, which is the part a buyer reads.
#:
#: A colon is required and the word list is short, because "note the matching
#: serial number" is a sentence about the gun.
_HEADING_ANYWHERE = re.compile(
    r"\b(?:disclaimer|please\s+note|important\s+notice|shipping\s+restrictions?)\s*:", re.I
)

#: Never return a description shorter than this. Below it the result reads as
#: an empty field rather than a short one, and a short honest description is
#: worth more than a tidy blank.
MIN_KEPT_CHARS = 40

#: Never remove more than this share of a description. Removing most of one
#: means the patterns matched something that was not boilerplate, and the safe
#: response to "I have cut away most of this" is to cut nothing.
MAX_REMOVED_SHARE = 0.4

#: The longest run of text that may be dropped as a single "sentence".
#:
#: A shop's standing notice is a sentence or two. This guard exists because the
#: splitter cannot split what has no punctuation, and a parts-kit contents list
#: has none: "This kit includes: Bolt group, complete Buttstock, complete with
#: recoil spring and guide rod Backplate..." arrives as one 700-character chunk,
#: and one incidental match inside it took the whole list. Four listings lost
#: 59% of a real description that way before this existed.
MAX_SENTENCE_CHARS = 300


def _is_boilerplate(sentence: str) -> bool:
    stripped = sentence.strip()
    if not stripped:
        return True
    if len(stripped) > MAX_SENTENCE_CHARS:
        # Too long to be a standing notice, so whatever matched inside it was
        # incidental. See MAX_SENTENCE_CHARS.
        return False
    return bool(_BLOCK_HEADING.match(stripped) or _BOILERPLATE.search(stripped))


def strip_boilerplate(description: str | None) -> str | None:
    """The description with the shop's standing notices taken off the end.

    Returns the original whenever trimming would go too far -- see the module
    docstring. Never raises and never returns an empty string where there was
    text: a caller storing this has no way to tell "nothing to remove" from
    "removed everything" if the answer to both is blank.
    """
    if not description or not description.strip():
        return description

    text = description.strip()

    # Cut at a mid-text heading first, so the sentence pass never has to decide
    # about a chunk that is half condition report and half policy.
    heading = _HEADING_ANYWHERE.search(text)
    if heading and heading.start() > 0:
        candidate = text[: heading.start()].strip()
        share_cut = (len(text) - len(candidate)) / len(text)
        if len(candidate) >= MIN_KEPT_CHARS and share_cut <= MAX_REMOVED_SHARE:
            text = candidate

    sentences = _SENTENCE.split(text)
    if len(sentences) < 2:
        # One sentence is all there is; if it is boilerplate it is also the
        # only thing the shop said, and an empty description is worse.
        return description

    keep = len(sentences)
    while keep > 0 and _is_boilerplate(sentences[keep - 1]):
        keep -= 1

    if keep == len(sentences):
        # Nothing further to take. `text` may already be shorter than the
        # original because a heading was cut above, and that is the answer.
        return text if text != description.strip() else description

    kept = " ".join(sentences[:keep]).strip()
    if len(kept) < MIN_KEPT_CHARS:
        return description
    original = description.strip()
    if (len(original) - len(kept)) / len(original) > MAX_REMOVED_SHARE:
        return description
    return kept
