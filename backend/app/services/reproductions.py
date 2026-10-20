"""Whether a listing reads as a reproduction: a copy made recently of an old
pattern, not the old gun.

Shared by the C&R reader (app.services.curio) and the serial dating
(app.services.serials), because both go wrong the same way on one. A Pietta
"1858 New Army" is not an 1858 revolver, and a description that says it was
"created to replicate the Samuel & Jacob Hawken of the 1840's" does not date
the rifle to the 1840s. On production on 2026-10-20, 183 guns carried a C&R
year read that way -- 89 of them Muzzle-Loaders.com's new reproductions, with
years such as 1800, 1815 and 1858 -- and nearly all were "eligible by age". An Uberti Single Action Army numbered in
Colt's 1890s range came out as an 1897 Colt (2026-10-19).

**Read as one:** replica, reproduction, repro, replicate, non-firing, "1/2
scale", scale model, and the firms that make copies of these patterns. Not
"miniature" -- FN and the Scolaire made real miniature rifles -- nor
"replicated", which is history ("closely replicated the look of the M1911").

**Not read as one**, each found on production on 2026-10-20, where a first
draft took 376 listings' years and many of them were originals:

* the word before a part, within a few words, or after one in the same
  sentence: "with a reproduction ramrod", "reproduction black plastic grips",
  "owners manual (repro)", "Mount is a possible reproduction" -- an original
  gun with a replaced part or accessory, which is common on the antiques here;
* a denial in the same sentence: "NOT A REPRODUCTION", "a legitimate antique
  and not a reproduction", "not a molded replica, lightweight reproduction";
* a plural, which is about other guns: "Portugal received K98k replicas".
"""

from __future__ import annotations

import re

#: The words, in the singular: a plural is about other guns ("Portugal
#: received K98k replicas", "the reproductions from Inland are nearly $1400").
_WORDS = re.compile(
    r"\b(?:replica|reproduction|repro|replicates?|non-?firing|\d+/\d+\s+scale|\d+%\s+scale|"
    r"scale\s+model)(?![\w'])",
    re.I,
)
#: The firms that make nothing but copies of these patterns -- not Rossi, Navy
#: Arms or Great Western, which also made or sold originals, nor Miroku, which
#: builds Brownings under license, nor "Standard Manufacturing", which is
#: inside "High Standard Manufacturing". A maker's name is
#: the gun's maker wherever it stands, so the part rules
#: below are not applied to one: "...barrel, with the notorious Uberti blue
#: finish" is an Uberti.
_MAKERS = re.compile(
    r"\b(?:uberti|pietta|pedersoli|investarm|armi\s+sport|euroarms|ardesa|cimarron|"
    r"chiappa|armi\s+san\s+marco|taylor'?s\s*(?:&|and)\s*co|hy\s+hunter|e\.?m\.?f\.?\b|"
    r"american\s+western\s+arms)(?![\w'])",
    re.I,
)
#: A denial earlier in its sentence: "NOT A REPRODUCTION", "an antique and
#: not a replica", "not a molded replica, lightweight reproduction, or ...".
_DENIED = re.compile(r"\b(?:not|isn'?t|no|never|nor|rather\s+than|instead\s+of)\b", re.I)
_SENTENCE_START = re.compile(r"[.!?;]\s")
#: A part a gun is sold with, which a "reproduction" a few words before it
#: describes: "reproduction black plastic grips", "reproduction P.38 holster".
_PARTS = (
    r"(?:ramrods?|rods?|slings?|stocks?|sights?|bayonets?|scabbards?|magazines?|mags?|"
    r"holsters?|grips?|handguards?|bands?|buttplates?|butt\s+plates?|triggers?|locks?|"
    r"hammers?|nipples?|barrels?|bolts?|parts?|screws?|springs?|covers?|caps?|box(?:es)?|"
    r"cases?|labels?|tags?|markings?|stamps?|manuals?|mounts?|bases?|oilers?|pouch(?:es)?|"
    r"belts?|straps?|frogs?|levers?|cups?|cans?|scopes?|rings?|guards?|plates?|cylinders?|sets?)"
)
_PART_AFTER = re.compile(r"(?:[\s-]+[\w.'/&-]+){0,3}?[\s-]+" + _PARTS + r"\b", re.I)
#: ...or a part named just before it: "owners manual (repro)", "Mount is a
#: possible reproduction", "handguard is reproduction".
_PART_BEFORE = re.compile(r"\b" + _PARTS + r"\b(?:\W+\w+){0,8}\W*$", re.I)


def is_reproduction(text: str | None) -> bool:
    """Whether *text* reads as a copy of the pattern rather than the gun."""
    text = text or ""
    for pattern in (_MAKERS, _WORDS):
        for hit in pattern.finditer(text):
            before = text[max(0, hit.start() - 80) : hit.start()]
            starts = [found.end() for found in _SENTENCE_START.finditer(before)]
            sentence = before[starts[-1] :] if starts else before
            if _DENIED.search(sentence):
                continue
            if pattern is _WORDS and (
                _PART_AFTER.match(text, hit.end()) or _PART_BEFORE.search(sentence)
            ):
                continue
            return True
    return False
