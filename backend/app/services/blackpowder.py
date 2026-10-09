"""Which firearms are black powder guns.

Asked for on 2026-10-08: a Black powder category beside Police surplus and
Concealed carry, for percussion and flintlock guns -- rifles, muskets, pistols,
revolvers, fowlers -- original antiques and modern reproductions alike. Like
the other two it is one of the browse page's Types and one of the hot-deals
tabs, and it outranks both there: a percussion revolver is never a carry gun or
a department trade-in, whatever a loose rule might make of it (see
search.KINDS).

**What makes one.** A firearm, not a parts kit, and any of:

* a finer kind that already says it -- ``percussion_revolver``,
  ``flintlock_rifle`` and the rest, from the armory model, the vendor or the
  title (see classify.finer_kind); or
* the vendor's own section saying it ("Traditional Muzzleloaders", "Black
  Powder Weapons", "Percussion Rifles"); or
* a title that says it: flintlock, percussion, cap and ball, caplock,
  matchlock, wheellock, muzzleloader, "black powder", and the guns that are
  only ever one (Brown Bess, Charleville, Hawken, Kentucky and Pennsylvania
  rifles, longrifles, fowlers, blunderbusses, muskets).

**What does not**, though the words are there: a gun *converted to fire
cartridges* (a Richards-Mason Colt, a Snider, an Allin trapdoor) and a "black
powder cartridge" rifle, which takes a metallic cartridge loaded with black
powder; a Colt's "black powder frame"; anything whose title names a cartridge
(".32 WCF", "45 LC", "357 Mag"). All cartridge guns. A pepperbox in rimfire is
too. And not a modern inline muzzleloader, which takes a 209 shotgun primer.

The description is not read, for the reason the other rules do not read it:
prose compares and reminisces, and "like the old percussion guns" is not a
percussion gun.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import Item

#: The finer kinds that are black powder guns by definition.
BLACK_POWDER_KINDS = frozenset(
    {
        "flintlock_rifle",
        "flintlock_carbine",
        "flintlock_pistol",
        "percussion_rifle",
        "percussion_carbine",
        "percussion_pistol",
        "percussion_revolver",
    }
)

#: A title saying it is a muzzleloader, or naming a gun that only ever was one.
_SAYS_SO = re.compile(
    r"\b(?:flint[\s-]?locks?|flint\s+(?:pistols?|muskets?|rifles?|guns?|fowlers?)|percussion|cap[\s-]*(?:and|&|n)[\s-]*ball|cap[\s-]?locks?|"
    r"match[\s-]?locks?|wheel[\s-]?locks?|snaphaunce|miquelet|"
    r"muzzle[\s-]?load(?:er|ers|ing)|black[\s-]?powder|"
    r"brown\s+bess|charleville|hawken|kentucky\s+(?:long\s*)?rifle|pennsylvania\s+(?:long\s*)?rifle|"
    # One word only: "Long Rifle" is a military rifle's length (a Steyr M95,
    # a Carcano) and half of ".22 Short, Long & Long Rifle".
    r"longrifle|"
    r"fowl(?:er|ing\s+piece)|blunderbuss|rifle[\s-]?musket|rifled\s+musket|muskets?|musketoons?)\b",
    re.I,
)

#: What turns those words into a cartridge gun.
_CARTRIDGE_GUN = re.compile(
    r"\b(?:altered|converted|conversion|alteration)\s+(?:to|for)\s+(?:\w+\s+)?cartridges?\b"
    r"|\bcartridge\s+conversion\b|\bconversion\s+revolver\b|\brichards[\s-]*mason\b"
    r"|\bblack[\s-]?powder\s+cartridge\b|\bbpcr\b|\bsnider\b|\ballin\b|\btrapdoor\b"
    r"|\b(?:rim|center|centre)[\s-]?fire\b|\b\.?\d{2,3}\s*(?:rf|cf)\b"
    # "Black powder" describing a cartridge gun: a Colt's black-powder frame,
    # a top-break "(black powder loads)".
    r"|\bblack[\s-]?powder\s+(?:frame|loads?)\b"
    # And a cartridge named outright: ".32WCF", "357 MAG", "45 LC".
    r"|\.?\d{2,3}[\s-]?(?:wcf|s\s*&\s*w|long\s+colt|lc|special|spl|mag(?:num)?)\b"
    # A modern inline muzzleloader is a hunting gun fired by a shotgun primer,
    # not the percussion or flintlock gun this category was asked for.
    r"|\bin[\s-]?line\b|\b209\b"
    # Called a musket and fired with a cartridge -- a Peabody-Martini, a
    # Winchester 1873 "44-40 Musket", an SMLE turned into a .410 -- or not a
    # firearm at all: a bayonet-training "fencing musket".
    r"|\b(?:martini|peabody|rolling[\s-]?block|fencing|smle|magazine\s+lee)\b"
    r"|(?<![\d.])\.410\b|\b\d{2}-\d{2,3}\b",
    re.I,
)


#: A vendor's own muzzleloading section, which says it for every gun in it:
#: "Traditional Muzzleloaders", "Black Powder Weapons", "Percussion Rifles".
_SECTION_SAYS_SO = re.compile(
    r"\b(?:muzzle[\s-]?load(?:er|ers|ing)|black[\s-]?powder|flint[\s-]?lock|percussion)\b",
    re.I,
)


def is_black_powder(
    title: str,
    *,
    is_rifle: bool,
    is_pistol: bool,
    is_parts_kit: bool = False,
    kind: str | None = None,
    category: str | None = None,
) -> bool:
    """Whether a listing is a black powder firearm. See the module docstring."""
    if not (is_rifle or is_pistol) or is_parts_kit:
        return False
    text = title or ""
    if _CARTRIDGE_GUN.search(text):
        return False
    if kind in BLACK_POWDER_KINDS:
        return True
    return bool(_SAYS_SO.search(text) or _SECTION_SAYS_SO.search(category or ""))


def decide(session: Session, item: Item) -> bool:  # noqa: ARG001 - carry.decide's signature
    """The answer for a stored listing, from the fields already settled. The
    scan and ``reclassify`` both call this, last, as they do carry.decide."""
    kind = getattr(item.kind, "value", item.kind)
    return is_black_powder(
        item.title,
        is_rifle=bool(item.is_rifle),
        is_pistol=bool(item.is_pistol),
        is_parts_kit=bool(item.is_parts_kit),
        kind=str(kind) if kind else None,
        category=item.category,
    )
