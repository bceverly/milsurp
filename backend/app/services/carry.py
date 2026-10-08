"""Which handguns are concealed-carry guns.

Asked for on 2026-10-08: a Concealed carry category for compact and
subcompact pistols in 9mm, 10mm, .40 S&W, .45 ACP and .380 ACP, and the small
revolvers people carry -- .32 H&R Magnum, .327 Federal, .38 Special, .357
Magnum. It is one of the browse page's Types and one of the hot-deals tabs,
and it outranks Police surplus there: a traded-in Glock 19 is shopped for as a
carry gun, so that is where it is found (see search.KINDS).

**Two questions, and a listing has to pass both.**

1. *A carry cartridge.* The caliber the listing has, or none at all when the
   model settles it -- a Glock 26 is a 9mm whether or not the title says so.
   A J-frame in .22 LR or a Walther PPK in .32 ACP is a small handgun but not
   what was asked for.
2. *A carry size*, from any of three kinds of evidence, strongest first: a
   model that only comes small (Glock 26, Sig P365, S&W Shield, a J-frame, an
   LCR); a size the title states ("Compact", "Subcompact", "Snub Nose",
   "Officer's"); or a stated barrel of three inches or less on a revolver,
   3.6 on a pistol.

**What it does not do.** It never reads the description, for the reason the
armory's model match does not: prose compares ("a P365-sized carry gun"), and a
duty Glock described as "great for carry" is still a duty Glock. Nor does it
make anything a handgun -- that is the classifier's call, made before this is
asked. An antique (a percussion revolver, a flintlock) is never carry, however
short its barrel: there is no cartridge to carry it in.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import Item

#: The cartridges. Matched on the caliber the listing ended up with, which the
#: armory has already normalized ("9mm Luger", ".357 Magnum") -- but loosely,
#: because a vendor's own spelling is kept where the armory had no row for it.
_CARRY_CALIBER = re.compile(
    r"^\s*(?:"
    r"9\s*mm(?!\s*(?:makarov|kurz|short|corto|browning\s+short|largo|steyr|mauser|nambu))"
    r"|9\s*x\s*19|10\s*mm|\.?40\s*s\s*&?\s*w|\.?45\s*(?:acp|auto)\b(?!\s*rim)"
    r"|\.?380|9\s*x\s*17|9\s*mm\s*(?:kurz|short|corto)"
    r"|\.?38\s*(?:special|spl|spc)|\.?357\s*mag|\.?327|\.?32\s*h\s*&\s*r|\.?44\s*special"
    r")",
    re.I,
)

#: Calibers a carry gun is chambered in that the regex above would let through
#: by their first characters. "9mm Makarov" is the obvious one -- a Makarov is
#: carried, but it was not asked for.
_NOT_CARRY_CALIBER = re.compile(r"makarov|9\s*x\s*18|largo|steyr|nambu|\.357\s*sig", re.I)

#: The finer kinds a carry gun can be. No percussion, no flintlock.
CARRY_KINDS = frozenset({"pistol", "revolver"})

# ---------------------------------------------------------------------------
# Models that only come in carry sizes
# ---------------------------------------------------------------------------
#: Semi-automatics, as dealers write them. A pattern rather than a list of
#: names, because a model is written a dozen ways ("Glock 19", "G19 Gen 5",
#: "GLOCK MODEL 19") and the armory does not have a row for most of them --
#: it was built for military surplus.
_CARRY_PISTOL = re.compile(
    r"""
    \b(?:glock|g)[\s-]*(?:model\s*)?(?:19[xv]?|23|25|26|27|28|29|30s?|32|33|36|38|39|42|43x?|48)\b
    |\bp\s*365(?:\s*-?\s*(?:xl|x|sas|macro|xmacro|axg))?\b
    |\bp\s*320\b[^,]{0,25}\b(?:compact|sub[\s-]*compact|carry|x[\s-]*compact)\b
    |\bp\s*(?:239|238|938|225)\b|\bp6\b
    |\bp\s*229\b
    |\b(?:m\s*&\s*p|mp)[\s-]*(?:9|40|45|380)?\s*(?:m2\.0\s*)?(?:shield|compact|c)\b
    |\bshield(?:\s*(?:plus|ez|ez\s*9|ez\s*380))?\b
    |\bbody\s*guard\b
    |\b(?:csx|sw\s*99\s*compact|39(?:13|14|53)|69(?:04|06)|46(?:53|83)|45(?:13|16)|40(?:13|14))\b
    |\bhellcat\b|\bxd[\s-]*s\b|\bxd[\s-]*e\b|\bxd(?:m)?[\s-]*(?:sub[\s-]*compact|compact)\b
    |\bemp\b|\bofficer'?s?\s*(?:acp|model|size|1911)\b|\b(?:champion|defender|commander|ultra\s*carry|pro\s*carry|micro\s*9|micro\s*carry)\b
    |\b(?:lcp(?:\s*(?:ii|2|max))?|lc\s*9s?|ec\s*9s?|lc\s*380|max[\s-]*9|security[\s-]*9\s*compact|sr\s*(?:9|40)\s*c|sr(?:9|40)c)\b
    |\bkimber\s+(?:micro|solo|ultra|pro\s*carry|cdp|eclipse\s+ultra|r7\s*mako)\b
    |\bpps\b(?![\s-]*\d)|\b(?:ppk(?:\s*/?\s*s)?|pk\s*380|ccp|p99\s*c|p99c|pdp\s*(?:f[\s-]*series\s*)?compact)\b
    |\b(?:p30\s*sk|p2000\s*sk|vp9\s*sk|p7(?:\s*(?:m8|m13|psp))?)\b
    |\b(?:nano|pico|apx\s*a?1?\s*carry|px4\s*(?:storm\s*)?(?:compact|sub[\s-]*compact)|cougar\s*mini|92\s*compact|centurion)\b
    |\b(?:g2c|g3c|g3x|gx4|pt\s*111|pt\s*709|709\s*slim|tcp|pt\s*738)\b
    |\b(?:p[\s-]*01|p[\s-]*07|p[\s-]*10\s*[cs]|rami|cz\s*75\s*(?:compact|d\s*compact|p[\s-]*01)|cz\s*2075)\b
    |\b(?:tp9\s*sc|tp\s*9\s*sc|mete\s*sc|elite\s*sc)\b
    |\b(?:mc\s*1(?:sc)?|mc\s*2c)\b
    |\b(?:fn\s*503|509\s*c|509\s*compact|fn\s*reflex)\b
    |\bkahr\b|\b(?:cw|pm|mk|cm|ct|k|p|t)\s*(?:9|40|45|380)\b(?=.*\bkahr\b)
    |\b(?:mustang|pocketlite|government\s*\.?380)\b
    |\b(?:pf\s*940\s*c|pf\s*9|dagger\s*compact|dagger)\b
    |\b(?:cr\s*920|mr\s*920|staccato\s*cs?|edc\s*x9|db\s*9|db\s*380|rm\s*380|r51|seecamp|cpx[\s-]*[12])\b
    |\b(?:thunder\s*(?:380|9\s*uc|ultra\s*compact)|bersa\s*(?:bp9|bp380))\b
    |\b(?:sig\s*)?p\s*250\s*(?:compact|sub[\s-]*compact)\b
    """,
    re.I | re.X,
)

#: Revolvers that only come small: the J-frames, the small Rugers and Colts,
#: Charter Arms, the Kimber K6s, the snub Tauruses and Rossis.
_CARRY_REVOLVER = re.compile(
    r"""
    (?:\b(?:s\s*&\s*w|smith\s*(?:&|and)\s*wesson)\s+(?:model\s*|mod\.?\s*|m)?|\b(?:model|mod\.?)\s*)
        (?:340|351|360|432|442|632|637|638|640|642|649)\b
    # The two-digit J-frames need more than the number, which is also a
    # caliber ("S&W 38 Single Action") and another maker's model ("CZ Model
    # 38"): the word Model, and S&W or "revolver" somewhere in the title.
    |\b(?:s\s*&\s*w|smith\s*(?:&|and)\s*wesson)\b.{0,30}?\b(?:model|mod\.?)\s*(?:36|37|38|40|42|49|60)\b
    |\b(?:model|mod\.?)\s*(?:36|37|38|40|42|49|60)\b(?=.*\b(?:s\s*&\s*w|smith\s*(?:&|and)\s*wesson|revolver)\b)
    |\bchiefs?'?\s*special\b|\bairweight\b|\bbody\s*guard\b|\bj[\s-]*frame\b
    |\b(?:s\s*&\s*w|smith\s*(?:&|and)\s*wesson)\b.*\bcentennial\b
    |\blcr\s*x?\b|\bsp[\s-]*101\b
    |\b(?:detective\s*special|(?<!king\s)cobra|agent|night\s*cobra|banker'?s?\s*special|pocket\s*positive)\b
    |\bcharter\b.*\b(?:undercover(?:ette)?|off[\s-]*duty|bulldog|pug|mag\s*pug|professional)\b
    |\bk6\s*s\b|\bk6s\b
    |\btaurus\s*(?:model\s*)?(?:85|605|650|651|856|905)\b
    |\b(?:85|605|650|651|856|905)\b(?=.*\b(?:taurus|revolver)\b)
    |\brossi\s*(?:model\s*)?(?:461|462|351|352|r35202)\b
    |\b(?:461|462|351|352|r35202)\b(?=.*\b(?:rossi|revolver)\b)
    """,
    re.I | re.X,
)

#: A size the title states.
_CARRY_SIZE = re.compile(
    r"\b(?:sub[\s-]*compact|compact|micro[\s-]*compact|snub(?:[\s-]*nose[d]?)?|snubbie|"
    r"pocket\s+pistol|carry\s+(?:pistol|gun|model)|ccw|conceal(?:ed)?\s+carry|"
    r"officer'?s?\s+(?:model|size)|backup)\b",
    re.I,
)

#: Duty and target sizes, which outrank a model's family name: "Glock 17", a
#: "Full Size" M&P, "Long Slide", a Python with a 6" barrel. Checked against the
#: title only after the explicit model patterns, so "G19 compact" is not undone
#: by anything here.
_NOT_CARRY_SIZE = re.compile(
    r"\b(?:full[\s-]*size|long[\s-]*slide|target|competition|match|tactical|hunter)\b"
    # A pistol-caliber carbine or an AR or AK sold as a "pistol", which a short
    # barrel would otherwise qualify: "Sig MPX Copperhead, 9mm 3.5in Pistol".
    r"|\b(?:mpx|mp5|sp5|ar[\s-]*(?:15|9|10)?\s*pistol|ak[\s-]*(?:47|74)?\s*pistol|draco|"
    r"scorpion|uzi|tec[\s-]*9|brace[d]?|pcc|sbr)\b"
    r"|\bglock\s*(?:model\s*)?(?:17|20|21|22|24|31|34|35|37|40|41|45|47)\b(?!\s*(?:sf\s*)?(?:c\b|compact))",
    re.I,
)

#: A barrel length in the title, in inches: '2"', '2 inch', '3-inch', '1 7/8"',
#: '2.5in', "2¼"".
_BARREL = re.compile(
    r"(?<![\d.])(\d(?:\.\d+)?)(?:\s*(?:-|\s)?\s*(\d)/(\d)|\s*([¼½¾]))?\s*"
    r"(?:\"|”|″|''|-?\s*inch(?:es)?\b|\s*in\.?(?=\s|$|,)|\s*bbl\b)",
    re.I,
)
_FRACTIONS = {"¼": 0.25, "½": 0.5, "¾": 0.75}

#: The longest barrel a carry revolver has. A 3" SP101 or a 3" Model 13 is
#: carried; a 4" Model 10 is a duty gun.
CARRY_REVOLVER_BARREL = 3.0

#: And a carry pistol's. Greentop states every used pistol's barrel ("Sig 1911
#: 3.25"", "Steyr C9-A2 3.5""), and at 3.6" or under a semi-automatic in a
#: carry cartridge is a compact by anybody's measure: a Glock 19 is 4.02", a
#: Glock 26 3.42", a P365 3.1".
CARRY_PISTOL_BARREL = 3.6


def barrel_inches(title: str) -> float | None:
    """The shortest plausible handgun barrel length the title states, if any."""
    lengths = []
    for found in _BARREL.finditer(title or ""):
        whole, num, den, glyph = found.group(1), found.group(2), found.group(3), found.group(4)
        length = float(whole)
        if num and den and float(den):
            length += float(num) / float(den)
        if glyph:
            length += _FRACTIONS[glyph]
        # A handgun barrel. Not a magazine count ("15+1"), a year or a price.
        if 1.0 <= length <= 8.5:
            lengths.append(length)
    return min(lengths) if lengths else None


def is_carry_caliber(caliber: str | None) -> bool:
    """Whether a caliber is one of the carry cartridges."""
    if not caliber:
        return False
    return bool(_CARRY_CALIBER.search(caliber)) and not _NOT_CARRY_CALIBER.search(caliber)


def is_concealed_carry(  # noqa: PLR0911 - one return per kind of evidence, strongest first
    title: str,
    *,
    is_pistol: bool,
    is_rifle: bool,
    kind: str | None,
    caliber: str | None,
    model: str | None = None,
) -> bool:
    """Whether a listing is a concealed-carry handgun. See the module docstring."""
    if not is_pistol or is_rifle:
        return False
    if kind is not None and kind not in CARRY_KINDS:
        return False
    if caliber and not is_carry_caliber(caliber):
        return False
    text = " ".join(part for part in (title, model) if part)
    revolver = kind == "revolver" or bool(re.search(r"\brevolver\b", title or "", re.I))

    # A model that only comes small decides it -- unless the title says this
    # one is the big version ("Glock 19 ... Glock 17 slide" is rare; "M&P
    # Compact" with "Full Size" is not).
    # Which family of model names to try: the one the kind says, or both when
    # the kind is unknown -- "Used Smith & Wesson 642 Airweight" says neither
    # "revolver" nor anything a pistol pattern knows.
    if kind == "pistol" and not revolver:
        named = _CARRY_PISTOL.search(text)
    elif revolver:
        named = _CARRY_REVOLVER.search(text)
    else:
        named = _CARRY_PISTOL.search(text) or _CARRY_REVOLVER.search(text)
    if named and not _explicitly_full_size(title):
        return _caliber_known_or_implied(caliber)
    if _NOT_CARRY_SIZE.search(title or ""):
        return False
    if _CARRY_SIZE.search(title or ""):
        return _caliber_known_or_implied(caliber, need_known=True)
    length = barrel_inches(title)
    limit = CARRY_REVOLVER_BARREL if revolver else CARRY_PISTOL_BARREL
    if length is not None and length <= limit:
        return _caliber_known_or_implied(caliber, need_known=True)
    return False


def _explicitly_full_size(title: str | None) -> bool:
    return bool(re.search(r"\bfull[\s-]*size\b|\blong[\s-]*slide\b", title or "", re.I))


def _caliber_known_or_implied(caliber: str | None, *, need_known: bool = False) -> bool:
    """A carry model needs no stated caliber -- the model implies one. A gun
    judged on its size alone does: a "compact" in an unknown chambering may be
    a .22 or a .25, so the size word is not enough on its own."""
    if caliber:
        return is_carry_caliber(caliber)
    return not need_known


def decide(session: Session, item: Item) -> bool:
    """The answer for a stored listing, from the fields everything else has
    already settled: the flags, the finer kind, the caliber and the armory
    model. The scan and ``reclassify`` both call this, last, so the two cannot
    drift apart -- the mistake ``is_police_surplus`` was once added to only one
    of them to make."""
    from ..models import FirearmModel

    model = session.get(FirearmModel, item.firearm_model_id) if item.firearm_model_id else None
    kind = getattr(item.kind, "value", item.kind)
    return is_concealed_carry(
        item.title,
        is_pistol=bool(item.is_pistol),
        is_rifle=bool(item.is_rifle),
        kind=str(kind) if kind else None,
        caliber=item.caliber,
        model=model.name if model else None,
    )
