"""One listing per gun, when a product page sells several.

Some shops put a run of guns behind one product page and let a dropdown or a
row of buttons choose between them -- Moka's Raifus sells twenty-one Radom
P-83s as "Radom P-83 Pistol - 1" to "- 21", Classic Firearms twenty unrelated
handguns as one "Gunsmith Special" priced $10, Centerfire a Walther P38 as
"Good $529.99 / Poor $499.99". Stored as one listing, each collapsed to a single
row at one price: the guns were invisible to every filter, total and
comparison, and the price was nobody's.

So a scraper that reads a page's choices hands them here, and gets back one
listing per choice -- or the page as it was, when the choices are not separate
guns. Asked for on 2026-10-10; see "One listing per gun when a page sells
several" in ROADMAP.md, which has the survey this rule came out of.

**What decides it is the choices, not the option's name.** Moka's calls its
numbered pistols "Condition", Arms of America calls rifles "Options", CO Gun
Sales calls revolvers "Box". The choices are separate guns when they are
numbered or serial-numbered, a condition grade, or differently priced or
pictured. They are not when the option is a service or an accessory -- IMA's
"Hand Select: Yes / No", a certificate, a magazine size -- nor when one of
them is "No Preference", which makes the page a lot with a preference rather
than a choice of guns; nor when a new gun is merely offered in colors at one
price, which is one product (see the variant work in "New-gun prices").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import ScrapedItem

#: An option that is something added to the gun rather than a choice of gun.
_ADD_ON = re.compile(
    r"hand[\s-]*select|certificat|\bcoa\b|warrant|insurance|gift|engrav|"
    r"magazine|\bmags?\b|holster|\bcase\b|sling|scope|optic|ammo|ammunition|"
    r"accessor|add[\s-]*on|upgrade|protection plan",
    re.I,
)
#: A choice that is a preference over a pick the shop makes, not a gun.
_PREFERENCE = re.compile(r"no\s+preference|\brandom\b|dealer'?s?\s+choice|\bany\b", re.I)
#: A condition grade, in any of the ways the shops in the survey wrote one.
_GRADE = re.compile(
    r"\b(?:poor|fair|good|very\s+good|excellent|mint|unissued|new\s+old\s+stock|nos|"
    r"blem(?:ished)?|cracked|broken|matching|non[\s-]*matching|grade|"
    r"[abcx][\s-]?grade|grade\s+[abc1-5]|early\s+production)\b",
    re.I,
)
#: A choice that is one particular gun: "Pistol - 1", "#3", "1 - Phoenix
#: Arms ...", "SN: BB50068".
_NUMBERED = re.compile(
    r"(?:^|[\s#])\d{1,3}\s*$|^\s*#?\d{1,3}\s*[-\u2013.)]|\bs/?n\b|\bserial\b", re.I
)
#: An option that is only how a gun looks.
_LOOKS = re.compile(r"\b(?:colou?r|finish|cerakote|pattern)\b", re.I)


@dataclass(frozen=True)
class Choice:
    """One option on a product page, as its shop describes it."""

    #: Stable within the page: the shop's own id for the option.
    key: str
    #: What the shop calls it: "Radom P-83 Pistol - 1", "Good".
    label: str
    price: float | None = None
    is_sold: bool = False
    image_urls: list[str] = field(default_factory=list)
    #: The option's own address, where the shop gives one.
    url: str | None = None
    description: str | None = None
    #: A complete title of its own, for a page whose choices are unrelated
    #: guns -- Classic's grab bags -- where "parent title - label" would read
    #: "Gunsmith Special Handguns - 1 - Phoenix Arms HP22B Pistol ...".
    title: str | None = None
    #: Set where the page's photographs are each one gun's: a choice whose own
    #: could not be found shows none rather than the whole gallery, which is
    #: every other gun on the page (see with_numbered_photos).
    own_photos_only: bool = False


def splits(  # noqa: PLR0911 - one return per rule, in the docstring's order
    option_names: list[str], choices: list[Choice]
) -> bool:
    """Whether these choices are separate guns. See the module docstring."""
    if len(choices) < 2:
        return False
    if any(_ADD_ON.search(name or "") for name in option_names):
        return False
    labels = [choice.label or "" for choice in choices]
    if any(_PREFERENCE.search(label) for label in labels):
        return False
    if any(_GRADE.search(label) for label in labels):
        return True
    if sum(1 for label in labels if _NUMBERED.search(label)) >= 2:
        return True
    prices = {choice.price for choice in choices if choice.price is not None}
    differently_priced = len(prices) > 1
    if option_names and all(_LOOKS.search(name or "") for name in option_names):
        # A color or a finish is one product unless the shop prices them
        # apart -- which on a surplus gun means a different gun.
        return differently_priced
    pictures = {tuple(choice.image_urls) for choice in choices if choice.image_urls}
    return differently_priced or len(pictures) > 1


def _strip_number(label: str) -> str:
    """ "1 - Phoenix Arms HP22B ..." without the "1 - " the page counts with."""
    return re.sub(r"^\s*#?\d{1,3}\s*[-\u2013.)]\s*", "", label).strip()


#: A label that is a name and a count: "Radom P-83 Pistol - 20", "Pistol 2".
_NAME_AND_NUMBER = re.compile(r"^(?P<name>.*?)[\s#\-\u2013]*(?P<number>\d{1,3})\s*$")


def _child_title(parent_title: str, choice: Choice) -> str:
    """What a choice's listing is called.

    Its own title where it has one. A label that only repeats the product's
    name with a count on the end -- Moka's "Radom P-83 Pistol - 20" under
    "Polish Radom P-83 Pistol - 9MM Makarov" -- becomes "#20" on the product's
    title rather than the name twice over. Anything else is appended.
    """
    if choice.title:
        return _strip_number(choice.title)
    found = _NAME_AND_NUMBER.match(choice.label or "")
    if found:
        name = found.group("name").strip().lower()
        words = re.findall(r"[a-z0-9]+", name)
        if all(word in parent_title.lower() for word in words):
            return f"{parent_title} #{found.group('number')}"
    return f"{parent_title} - {choice.label}"


def split(parent: ScrapedItem, choices: list[Choice]) -> list[ScrapedItem]:
    """One listing per choice, each standing in for a share of ``parent``.

    Keyed ``<parent key>#<choice key>`` so a choice keeps its listing -- and
    its price history and watchers -- from scan to scan. Each carries
    ``split_from`` so the scan can retire the combined listing it replaces.
    A choice with no photograph of its own shows the page's -- unless the
    page's photographs are each another choice's (``own_photos_only``).
    """
    children = []
    for choice in choices:
        title = _child_title(parent.title, choice)
        children.append(
            replace(
                parent,
                external_key=f"{parent.external_key}#{choice.key}",
                url=choice.url or parent.url,
                title=title,
                price=choice.price if choice.price is not None else parent.price,
                is_sold=choice.is_sold,
                description=choice.description or parent.description,
                image_urls=list(choice.image_urls)
                or ([] if choice.own_photos_only else list(parent.image_urls)),
                images_are_complete=bool(choice.image_urls)
                or choice.own_photos_only
                or parent.images_are_complete,
                split_from=parent.external_key,
                replaces_keys=[],
            )
        )
    return children


def _number(label: str) -> str | None:
    found = re.match(r"^\s*#?(\d{1,3})\s*[-\u2013.)]", label or "")
    return found.group(1).lstrip("0") or "0" if found else None


#: The gun's number in a photograph's file name, as Classic Firearms write it --
#: four ways on two pages (2026-10-12): "hg3_1", "hgnvts-5" and "op4-min_1",
#: the number after a word; "2_bst20409-min", the number first.
_PHOTO_NUMBER = (
    re.compile(r"^0*(\d{1,3})[_-]"),
    re.compile(r"^[a-z]+[-_]?0*(\d{1,3})(?:[-_](?:\d{1,2}|min))*$"),
)
#: The stock or serial number a grab bag's gun ends its title with: "... -
#: BST20409", "... - ZC12345 ".
_STOCK_NUMBER = re.compile(r"-\s*([A-Za-z0-9]{5,})\s*$")


def _photo_number(url: str) -> str | None:
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    stem = name.rsplit(".", 1)[0].lower()
    for pattern in _PHOTO_NUMBER:
        found = pattern.match(stem)
        if found:
            return found.group(1).lstrip("0") or "0"
    return None


def with_numbered_photos(choices: list[Choice], urls: list[str]) -> list[Choice]:
    """Each numbered choice given the page's photographs named for it.

    Classic Firearms number the guns in a grab bag ("1 - Phoenix Arms HP22B
    ...", "2 - Smith & Wesson M&P 40 ...") and name each one's photograph
    for it -- ``hg1_2.png``, ``hg2_1.png`` -- with the twenty side by side in
    one gallery and nothing else tying photograph to gun. Two signals, the
    stronger first: the stock number the gun's title ends with, found in the
    file's name ("... - BST20409" is ``2_bst20409-min.jpg``); then the gun's
    number (see :data:`_PHOTO_NUMBER`).

    **Where most of the guns find a photograph, the gallery is theirs**, and a
    gun whose own could not be found shows none rather than all of them: the
    "Video Team Special" page wrote its file names three new ways, none
    matched, and each of its twenty guns showed all twenty-one pictures
    (2026-10-12). A choice with a photograph of its own, or no number, is left
    as it is.
    """
    numbered = [(url, _photo_number(url)) for url in urls]
    matched: list[Choice] = []
    found_any = 0
    asked = 0
    for choice in choices:
        number = _number(choice.label)
        if choice.image_urls or number is None:
            matched.append(choice)
            continue
        asked += 1
        stock = _STOCK_NUMBER.search(choice.title or choice.label or "")
        mine = []
        if stock:
            code = stock.group(1).lower()
            mine = [url for url in urls if code in url.rsplit("/", 1)[-1].lower()]
        if not mine:
            mine = [url for url, n in numbered if n == number]
        found_any += bool(mine)
        matched.append(replace(choice, image_urls=mine) if mine else choice)
    if asked and found_any * 2 >= asked:
        matched = [
            replace(choice, own_photos_only=True) if _number(choice.label) is not None else choice
            for choice in matched
        ]
    return matched
