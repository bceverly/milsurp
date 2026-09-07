"""Turning a scanned advertising flyer into individual listings.

Most vendors publish an HTML catalog. A few publish a picture of one: a
magazine advertisement, scanned, replaced every month or two, with every
product for that period inside a single image. This module is the machinery for
that shape of vendor, kept apart from any one of them so a second flyer-based
site does not have to reinvent it.

Three steps, each of which can be tested on its own:

1. :func:`columns` finds the page's columns.
2. :func:`read_region` runs OCR over one of them.
3. :func:`listings_from_lines` groups the lines into products.
4. :func:`crop_for_listing` cuts each one out as its photograph.

**Why the columns are found from rules rather than whitespace.** The obvious
approach is an XY-cut: project the ink onto each axis and split on the blank
gutters. Measured on a real Hunter's Lodge flyer that finds nothing at all,
because the page is drawn as a grid of ruled boxes — of its 4813 columns of
pixels, *not one* is free of ink, since the panel borders run the full height.
The rules that defeat whitespace-cutting are themselves the layout, so this
reads them instead: a run of near-total ink coverage is a division.

**Why each region is OCR'd separately.** Handing Tesseract the whole page lets
its own layout analysis merge lines *across* columns — on the same flyer it
produced the line "1940'S U.S. MILITARY GAHENDRA MARTINI "OLE ZEKE'S"
TREASURES", which is three different listings' headings from three different
columns glued into one string. Reading a single column-width region at a time
removes the ambiguity rather than trying to undo it afterwards.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from PIL import Image

# The one thing this module asks of the domain: which words name an ATF license
# rather than a product. Page layout is what the rest of this file knows about;
# what "C&R" means is a fact about the trade, and it lives with the rest of them.
from ..services import classify

#: Grey values below this count as ink once the page is converted to greyscale.
INK_THRESHOLD = 160

#: Mean ink across a region's span, 0-255, at or above which a row or column is
#: a separator rule rather than content.
RULE_COVERAGE = 150

#: ...and at or below which it is whitespace.
BLANK_COVERAGE = 6

#: A rule only needs to be a few pixels thick; a whitespace gutter has to be
#: wide enough not to be the space between two lines of text.
MIN_RULE_RUN = 3
MIN_BLANK_RUN = 24

#: Regions smaller than this in either direction are not listings — they are
#: fragments of a photograph or a stray rule.
MIN_REGION_SIZE = 150

#: Depth cap, so a pathological page cannot recurse without end.
MAX_CUT_DEPTH = 7

#: Listing photographs are crops of a scan, and a crop of a crop looks worse
#: the smaller it starts. Anything below this on its long edge is enlarged.
MIN_CROP_LONG_EDGE = 900

#: ...but never enlarged beyond this, which would only magnify the paper grain.
MAX_UPSCALE = 3.0

#: A trailing full stop is part of the sentence, not the number: "$178.88." is
#: a price of 178.88.
PRICE_PATTERN = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{2})?)")

#: Tesseract renders the flyer's bullet glyph inconsistently. Measured against
#: a real page it comes back as •, ·, *, ¢, e, «, ° and ) among others, so this
#: matches any short run of punctuation-or-single-letter before the text rather
#: than trying to enumerate every misreading.
#: A bullet is a glyph, optionally some space, then the start of a name.
#:
#: Two branches, because the space is optional only when the glyph is
#: unmistakable. Tesseract reads the flyer's bullet as ¢ or ° or * and
#: routinely loses the space behind it, giving "¢CZ 52 SEMI AUTO ASSAULT
#: RIFLES" — which, when the space was required, was not a bullet at all, so
#: the CZ 52 never started a listing and was swallowed by the Colt frames
#: above it, along with its photograph. Parentheses, hyphens and a stray
#: lowercase letter are also seen standing in for a bullet, but each of those
#: is a real character in its own right ("-38 SPECIAL"), so those still need
#: the space to tell a bullet from a word.
BULLET_PATTERN = re.compile(
    r"^\s*(?:"
    r"[•·∙*●▪¢°«»]{1,2}\s*(?=[A-Z0-9])"
    r"|(?:[•·∙*●▪¢°«»)(\-—]{1,3}|[a-z])\s*[•·∙*●▪¢°«»]?\s+(?=[A-Z0-9])"
    r")"
)


#: Page furniture that is set in capitals and therefore reads as a heading:
#: the masthead, the payment terms box, the footer. It sits at the top and
#: bottom of the page rather than in a panel, so it attaches itself to whatever
#: listing is nearest and turns up at the front of a title — "OR MONEY MAUSER
#: C96 PISTOL KITS". Matched at the start of a title and dropped.
FURNITURE_PATTERN = re.compile(
    r"^(?:\s*(?:NO\.?\s*CREDIT|CARDS?|CHECK|OR\s+MONEY|ORDER\s+ONLY|SEE\s+OUR\s+WEB\s*SITE"
    r"|WWW\.[^\s]+|EST\.?\s*\d{4}|P\.?O\.?\s*BOX[^,]*|TELEPHONE[^,]*)\b[\s.,:;-]*)+",
    re.I,
)

#: The licensing terms, which are set in the same capitals as a product name
#: and are not one. Every listing on the page carries some version of "C&R or
#: FFL required", and where it is set on a line of its own it reads as a
#: heading by shape — which put "NO FFL REQUIRED" on the end of the 1888 German
#: Commission Rifle and left one listing titled "C&R/FFL" and nothing else.
#: The words those lines are made of, and nothing else. Written as a repeated
#: alternation rather than a fixed shape because the flyer says it a different
#: way every time: "C&R/FFL", "FFL or C&R required", "NO FFL REQUIRED".
_TERM_WORD = (
    r"(?:C\s*&\s*R|F\.?F\.?L\.?|LICENSE[SD]?|PERMIT|REQUIRED|REQ\.?|NEEDED|NO|OR|AND|NOT)"
    # A whole word, or "NO" eats the front of "NO1 MK2 PARTS KITS" and
    # "NOSE HOLSTER".
    r"(?![A-Za-z0-9])"
)
TERMS_PATTERN = re.compile(rf"^[\s.,:;/&-]*(?:{_TERM_WORD}[\s.,:;/&-]*)+$", re.I)

#: The same words in front of a name rather than instead of one. The flyer sets
#: "FFL or / C&R required" in its own little block beside the heading, and OCR
#: reads the two as one line: "FFL or WW2 RUSSIAN 91/30 RIFLES".
LEADING_TERMS = re.compile(
    rf"^[\s.,:;/&-]*(?:{_TERM_WORD}[\s.,:;/&-]*)+(?=[A-Z0-9])",
    re.I,
)


def is_only_terms(text: str) -> bool:
    """Whether a line says nothing but who may buy the thing."""
    return bool(text.strip()) and bool(TERMS_PATTERN.match(text.strip()))


#: Stray glyphs left at the head of a line once the bullet itself is removed.
_LEADING_NOISE = re.compile(r"^\s*(?:[¢°«»)(*·•~|\\/\-—]+\s*|(?<![A-Za-z])[a-z]\s+(?=[A-Z]))+")


class OcrUnavailable(RuntimeError):
    """Tesseract or its Python binding is not installed on this machine."""


@dataclass
class Region:
    """One rectangle of the page, in page pixel coordinates."""

    box: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


@dataclass
class TextLine:
    """One OCR'd line, with where it sits on the page."""

    text: str
    box: tuple[int, int, int, int]
    height: float
    #: Which panel of the page this line sits in. Lines are read a column at a
    #: time, which keeps a heading with the body below it, but a column holds
    #: several products; this is what stops one listing running into the next.
    panel: int = -1
    #: The words this line was assembled from, as (left edge, box, text), in
    #: reading order. Kept so a word recovered by a second pass can be put back
    #: in the place it actually occupies rather than at one end of the line —
    #: see :func:`_prices_lost_in_the_pictures`. Empty when a line is built by
    #: hand, as the tests do.
    words: list[tuple[int, tuple[int, int, int, int], str]] = field(default_factory=list)

    @property
    def is_bulleted(self) -> bool:
        return bool(BULLET_PATTERN.match(self.text))


@dataclass
class FlyerListing:
    """One product recovered from the flyer."""

    title: str
    description: str
    price: float | None
    box: tuple[int, int, int, int]
    lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
def _pytesseract():
    """Import pytesseract lazily and turn its absence into a clear error.

    Imported here rather than at module scope so that the rest of the
    application -- and every test that never touches a flyer -- runs on a
    machine with no OCR installed.
    """
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - depends on host packages
        raise OcrUnavailable(
            "pytesseract is not installed; run 'make install-dev', or disable "
            "this site in the admin UI."
        ) from exc
    return pytesseract


def ocr_available() -> bool:
    """True when both the Python binding and the tesseract binary are present."""
    try:
        pytesseract = _pytesseract()
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def _binarize(page: Image.Image) -> Image.Image:
    """Ink as white on black, which makes a projection a sum of ink."""
    return page.convert("L").point(lambda value: 255 if value < INK_THRESHOLD else 0)


def _projection(binary: Image.Image, axis: str) -> list[int]:
    """Mean ink per row (``"h"``) or per column (``"v"``), each 0-255.

    Computed by resizing to a single pixel on the other axis with BOX
    filtering, which averages exactly the pixels being projected and does it in
    Pillow's C code. It avoids a numpy dependency for what is one line of it.
    """
    width, height = binary.size
    target = (1, height) if axis == "h" else (width, 1)
    # get_flattened_data() is typed for any band count, so it returns a union of
    # "tuple of ints" and "tuple of tuples". This is always a single-band "L"
    # image, straight out of _binarize, so every value is one number.
    data = cast("Sequence[float]", binary.resize(target, Image.Resampling.BOX).get_flattened_data())
    return [int(value) for value in data]


def _runs(profile: list[int], keep, min_run: int) -> list[tuple[int, int]]:
    """Index ranges of at least ``min_run`` where ``keep`` holds."""
    found: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(profile):
        if keep(value):
            if start is None:
                start = index
        else:
            if start is not None and index - start >= min_run:
                found.append((start, index))
            start = None
    if start is not None and len(profile) - start >= min_run:
        found.append((start, len(profile)))
    return found


def _separators(profile: list[int]) -> list[tuple[int, int]]:
    """Where this profile is either a rule or a gutter, merged and in order."""
    marks = sorted(
        _runs(profile, lambda v: v >= RULE_COVERAGE, MIN_RULE_RUN)
        + _runs(profile, lambda v: v <= BLANK_COVERAGE, MIN_BLANK_RUN)
    )
    merged: list[tuple[int, int]] = []
    for mark in marks:
        if merged and mark[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], mark[1]))
        else:
            merged.append(mark)
    return merged


def _slices(separators: list[tuple[int, int]], length: int) -> list[tuple[int, int]]:
    """The content between the separators, discarding slivers."""
    pieces: list[tuple[int, int]] = []
    previous = 0
    for start, end in separators:
        if start - previous >= MIN_REGION_SIZE:
            pieces.append((previous, start))
        previous = end
    if length - previous >= MIN_REGION_SIZE:
        pieces.append((previous, length))
    return pieces


# ---------------------------------------------------------------------------
# Reading a region
# ---------------------------------------------------------------------------
#: Minimum confidence for a word to be believed.
MIN_CONFIDENCE = 30

#: Tesseract's "assume a single uniform block of text": no layout analysis at
#: all. See :func:`_prices_lost_in_the_pictures`.
NO_LAYOUT_ANALYSIS = "--psm 6"


def _lines_from(data: dict, ox: int, oy: int) -> list[TextLine]:
    """Assemble tesseract's word table into lines, in reading order."""
    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, text in enumerate(data["text"]):
        if not text.strip():
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        if confidence < MIN_CONFIDENCE:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        grouped.setdefault(key, []).append(index)

    lines: list[TextLine] = []
    for indexes in grouped.values():
        indexes.sort(key=lambda i: data["left"][i])
        text = " ".join(data["text"][i].strip() for i in indexes).strip()
        if not text:
            continue
        left = min(data["left"][i] for i in indexes)
        top = min(data["top"][i] for i in indexes)
        right = max(data["left"][i] + data["width"][i] for i in indexes)
        bottom = max(data["top"][i] + data["height"][i] for i in indexes)
        heights = sorted(data["height"][i] for i in indexes)
        lines.append(
            TextLine(
                text=text,
                box=(ox + left, oy + top, ox + right, oy + bottom),
                height=heights[len(heights) // 2],
                words=[
                    (
                        ox + data["left"][i],
                        (
                            ox + data["left"][i],
                            oy + data["top"][i],
                            ox + data["left"][i] + data["width"][i],
                            oy + data["top"][i] + data["height"][i],
                        ),
                        data["text"][i].strip(),
                    )
                    for i in indexes
                ],
            )
        )
    lines.sort(key=lambda line: (line.box[1], line.box[0]))
    return lines


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Whether two boxes cover any of the same page."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _prices_lost_in_the_pictures(
    page: Image.Image, region: Region, lines: list[TextLine]
) -> list[TextLine]:
    """Put back the prices tesseract decided were part of a photograph.

    This flyer sets its prices across the product photo — "Only $378.88" over
    the stock of the rifle, "ONLY $219.00." beside it — and tesseract's layout
    analysis, reasonably enough, calls that region a picture and does not read
    it. Not at low confidence: the words are absent from the word table
    entirely. Cropped on their own the same words read at confidence 96, so
    nothing is wrong with the print, only with the decision about where the
    text is.

    The same happens to a product's name when it is set directly above its own
    photograph, underlined, with the panel rule beneath it: "1903 TURKISH
    CONTRACT MAUSERS" was not read at all, and the Ottoman Mauser was left
    titled "MFG by germany for The Empire", cropped to a picture that began
    below its own name.

    So the region is read a second time with layout analysis off, which reads
    everything including the pictures. Two things are taken from that pass and
    nothing else: price words the first pass missed, and headings standing in a
    band of the page where the first pass read nothing at all. Every part of
    that restriction matters:

    * Only prices, because reading a photograph as text also produces "~~" and
      "ae) :", and none of that is wanted in a title.
    * Only words, not lines — except in an empty band. Without layout analysis
      tesseract joins text across a picture into lines that do not exist:
      "Supply limited. | BBL Action/Rec $48.88" is two different products, and
      taking whole lines from the second pass corrupted good text from the
      first. A single word put back where it sits is safe, and so is a whole
      line in a band where there is nothing to corrupt.

    Two rifles were priced at their own hand-select surcharge before this: the
    91/30 at the "$20.00" of "Hand select add $20.00", and the 1916 Spanish
    Mauser at the "$25" of "Add $25 for hand select", each having taken the
    first price it could see once its real one had been discarded.
    """
    pytesseract = _pytesseract()
    data = pytesseract.image_to_data(
        page.crop(region.box),
        config=NO_LAYOUT_ANALYSIS,
        output_type=pytesseract.Output.DICT,
    )
    second = _lines_from(data, region.box[0], region.box[1])

    already = [box for line in lines for _left, box, _text in line.words]
    missing = [
        (left, box, text)
        for line in second
        for left, box, text in line.words
        if PRICE_PATTERN.search(text) and not any(_overlaps(box, seen) for seen in already)
    ]
    headings = [
        line
        for line in second
        if is_heading(line) and not is_only_terms(line.text) and _in_a_gap(line, lines)
    ]
    if not missing and not headings:
        return lines

    merged = [*lines, *headings]
    for left, box, text in missing:
        home = next((line for line in merged if _overlaps(line.box, box)), None)
        if home is None:
            # Standing on its own over the picture, as "Only $378.88" does.
            merged.append(TextLine(text=text, box=box, height=box[3] - box[1]))
            continue
        home.words = sorted([*home.words, (left, box, text)])
        home.text = " ".join(word for _left, _box, word in home.words)
        home.box = (
            min(home.box[0], box[0]),
            min(home.box[1], box[1]),
            max(home.box[2], box[2]),
            max(home.box[3], box[3]),
        )

    merged.sort(key=lambda line: (line.box[1], line.box[0]))
    return merged


def _in_a_gap(line: TextLine, lines: list[TextLine]) -> bool:
    """Whether nothing in the first pass occupies this line's band of the page.

    Vertical only, and deliberately strict: a line sharing any part of its band
    with something already read is a *re-read* of that text, and taking it
    would replace a good line with one that layout analysis has run together
    across a picture. A band with nothing in it cannot be damaged.
    """
    return not any(line.box[1] < other.box[3] and other.box[1] < line.box[3] for other in lines)


def read_region(page: Image.Image, region: Region) -> list[TextLine]:
    """OCR one region, returning its lines in reading order."""
    pytesseract = _pytesseract()
    data = pytesseract.image_to_data(page.crop(region.box), output_type=pytesseract.Output.DICT)
    lines = _lines_from(data, region.box[0], region.box[1])
    return _prices_lost_in_the_pictures(page, region, lines)


def parse_price(text: str) -> float | None:
    """The first dollar amount in a line, or None."""
    match = PRICE_PATTERN.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


#: The proportion of a line's letters that must be capitals for it to be a
#: heading. The flyer sets every product name in caps and every word of prose
#: in mixed case, so this alone separates them.
HEADING_UPPERCASE = 0.85

#: A heading needs enough letters to be a name rather than an abbreviation
#: caught mid-sentence ("FFL", "C&R", "NEW").
MIN_HEADING_LETTERS = 6

#: Stop joining heading lines into a title once it is this long. A product name
#: broken over four lines is normal on this page; a paragraph is not.
MAX_TITLE_FROM_HEADINGS = 60

#: How many heading lines a price-less group may hand on to the next listing.
#: Enough for the longest name on the page, few enough that a column of section
#: headers cannot accumulate.
MAX_CARRIED_HEADING_LINES = 4


def _is_capitalized(text: str) -> bool:
    """Whether a piece of text is set in capitals, as every heading here is."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        # "50/70" and "10" are parts of a name, not the end of one.
        return any(c.isdigit() for c in text)
    return sum(1 for c in letters if c.isupper()) / len(letters) >= HEADING_UPPERCASE


#: How many capitalised words a line must open with before it counts as
#: naming a product. One is not enough: "FFL or C&R required" opens with an
#: abbreviation and continues the line above it.
MIN_LEADING_NAME_WORDS = 2


def starts_with_a_name(text: str) -> bool:
    """Whether a line opens with a product name set in capitals."""
    words = text.split()
    if len(words) < MIN_LEADING_NAME_WORDS:
        return False
    for word in words[:MIN_LEADING_NAME_WORDS]:
        letters = [c for c in word if c.isalpha()]
        if not ((len(letters) >= 2 and word.upper() == word) or word[:1].isdigit()):
            return False
    return True


def is_heading(line: TextLine) -> bool:
    """Whether this line starts a new listing rather than continuing one.

    Judged on capitalisation, not on size. Size is the obvious signal and it
    does not work here: an all-caps heading's bounding box is no taller than a
    line of lowercase prose with ascenders and descenders, so measured on a
    real page a height rule found five headings where there were thirty. Every
    product name on the flyer is set in capitals and every sentence of
    description is not, which separates them cleanly.

    """
    letters = [c for c in line.text if c.isalpha()]
    if len(letters) < MIN_HEADING_LETTERS:
        return False
    return _is_capitalized(line.text)


def prices_in(text: str) -> list[float]:
    """Every dollar amount in a line."""
    found = []
    for raw in PRICE_PATTERN.findall(text):
        try:
            found.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return found


def listings_from_lines(lines: list[TextLine]) -> list[FlyerListing]:
    """Group a region's lines into listings.

    Two shapes appear on these flyers and both are handled here:

    * a **panel** — a heading in large type, then body text, then a price;
    * a **bulleted list** — one item per line, each with its own price, several
      dozen of them under a single heading.

    A heading or a bullet starts a listing and everything after it belongs to
    that listing until the next one starts.

    The price is the **first** amount in the listing. These pages follow one
    order throughout: the name, then the description, then the price, and then
    occasionally some terms — "$322.88 for a limited time. Add $25 for hand
    select." The price is stated once, where the description ends, and anything
    after it is an option.

    Taking the largest instead was tried, on the reasoning that a firearm costs
    more than its add-ons. It holds right up until a listing's text bleeds into
    its neighbour's, and then it reaches over and takes the bigger number:
    hand-woven blankets came out at $99.00 instead of $36.88, and a barrelled
    receiver at $47.88 instead of $45.00, each having borrowed from the item
    beside it. Taking the first is both more faithful to how the page is
    written and harder to mislead.
    """
    listings: list[FlyerListing] = []
    pending: list[TextLine] = []

    def flush(before_a_bullet: bool = False) -> None:
        if not pending:
            return
        text_lines = [line.text for line in pending]
        joined = " ".join(text_lines)
        found = prices_in(joined)
        if not found:
            # Nothing here is for sale, but the heading lines almost certainly
            # belong to whatever comes next: the flyer sets a product's name
            # above the rule that separates it from its own description, so a
            # group that ends without a price is usually a name looking for
            # one. Dropping it outright left listings titled "needs TLC" and
            # "frame for". The prose is discarded; only the name is carried.
            #
            # Except across a bullet. A bullet is the start of a product, and
            # the flyer never puts one product's name after the next one's
            # bullet — so a price-less group in front of a bullet is a listing
            # whose price was misread, not a name looking for a body. Carrying
            # it anyway produced "1903 BRITISH .303 LEATHER AMMO JAP ARISIKA
            # BBL REC", which is two products with one price between them; the
            # bandolier's own "39.88." had lost its dollar sign to OCR.
            kept = (
                [] if before_a_bullet else [item for item in pending if _is_capitalized(item.text)]
            )
            pending.clear()
            pending.extend(kept[-MAX_CARRIED_HEADING_LINES:])
            return
        box = (
            min(line.box[0] for line in pending),
            min(line.box[1] for line in pending),
            max(line.box[2] for line in pending),
            max(line.box[3] for line in pending),
        )
        title = _title_from(pending)

        if listings and (not title or classify.names_only_a_license(title)):
            # A price with no name of its own is the tail of the listing above
            # it, not a listing. "Add frame for $38.88. C&R/FFL required." is
            # the second half of the Enfield kits, split off by a rule falling
            # between the two lines; on its own it became a $38.88 product
            # called "C&R/FFL", which is a license the ATF issues and not
            # something anybody sells.
            #
            # It is put back rather than dropped: the option belongs in the
            # description, and the box belongs in the crop, which was stopping
            # short of the panel it was cut from.
            previous = listings[-1]
            previous.description = f"{previous.description} {joined}".strip()
            previous.lines.extend(text_lines)
            previous.box = (
                min(previous.box[0], box[0]),
                min(previous.box[1], box[1]),
                max(previous.box[2], box[2]),
                max(previous.box[3], box[3]),
            )
            pending.clear()
            return

        listings.append(
            FlyerListing(
                title=title,
                description=only_this_listing(joined, title),
                price=found[0],
                box=box,
                lines=list(text_lines),
            )
        )
        pending.clear()

    for line in lines:
        # A panel boundary ends a listing, but only once that listing has a
        # price. Before it does it is still being assembled, and the boundary
        # is one it has to cross: the flyer draws a rule between a product's
        # name and its description, and its bulleted lists run across panels,
        # so cutting at every boundary orphaned the name from the price and
        # left listings called "needs TLC" and "frame for".
        #
        # A listing ends at its price. That is the one thing these pages are
        # consistent about, and it is a far better boundary than a rule: in the
        # dense lower half of the page the rules fall between a sentence and
        # its own continuation, which cut "1903 TURKISH CONTRACT MAUSERS" from
        # the "$322.88" three words later and titled the result "MFG by germany
        # for The Empire".
        crossed_panel = (
            bool(pending)
            and line.panel != pending[-1].panel
            and bool(prices_in(" ".join(item.text for item in pending)))
        )
        # A line that opens with a product name *and* carries its own price
        # starts a new item, whether or not OCR kept the bullet in front of it.
        #
        # The bulleted lists set each name in capitals and then continue in
        # sentence case — "BRITISH NO4 MK1 RIFLES as is $88.00." — so the line
        # is not capitalised enough to read as a heading, and the bullet glyph
        # is dropped often enough not to be relied on. Without this those items
        # were swallowed by the one above and their prices went with them: the
        # bayonet grab bag was priced at the British No4's $88.
        #
        # Only once the item being assembled has a price of its own, or a
        # wrapped name splits from its own description: ".38 SNUB" / "NOSE
        # HOLSTER for belt or boot $14.50." would become two listings.
        pending_text = " ".join(item.text for item in pending)
        resumes_a_list = (
            bool(pending)
            and starts_with_a_name(line.text)
            and bool(prices_in(line.text))
            and bool(prices_in(pending_text))
        )
        if (line.is_bulleted or is_heading(line) or crossed_panel or resumes_a_list) and pending:
            # ...unless everything pending is *also* heading text with no price,
            # in which case this is the next line of the same name rather than
            # the start of a new listing.
            #
            # The flyer breaks a product name over as many lines as it needs:
            # "S&W" / "K-FRAME," / "SNUB-NOSE" / "REVOLVER KITS", and
            # "GAHENDRA MARTINI" / "BEAUTIFUL HANDSOME" / "WOOD STOCK SET".
            # Splitting on each of those threw away everything before the last
            # line and produced listings called "REVOLVER KITS" and "WOOD STOCK
            # SET" with no maker and no model.
            # A bullet is never a continuation. The flyer wraps a long name
            # onto a second line without repeating the bullet, so a wrapped
            # name is always unbulleted — which means a bulleted line is the
            # next product even when what is pending is still nothing but
            # capitals. "1903 BRITISH .303 LEATHER AMMO" ran straight into
            # "JAP ARISIKA BBL REC" without this.
            still_in_the_heading = (
                not line.is_bulleted
                and not prices_in(pending_text)
                and all(_is_capitalized(item.text) for item in pending)
            )
            if not still_in_the_heading:
                flush(before_a_bullet=line.is_bulleted)
        pending.append(line)
    flush()
    return listings


#: Below this a title is not a name — a stray "MFG" or "1" — and the listing's
#: opening line is more use than the fragment.
MIN_TITLE_LENGTH = 6

#: How far into a title to look for the start of the actual name. Beyond this
#: the capitals are as likely to be a word shouted mid-sentence.
MAX_LEADING_JUNK_WORDS = 6


def _from_the_first_capital(title: str) -> str:
    """Drop the prose in front of a name that begins in capitals.

    Every product on this page is named in capitals, so a lower-case word ahead
    of the first capitalised one is something that leaked in from a neighbour —
    "Swedish steel. GAHENDRA MARTINI RIFLE", or the masthead's "Loc 1" landing
    in front of "CZ 50/70 PISTOL KITS".
    """
    words = title.split()
    for index, word in enumerate(words[:MAX_LEADING_JUNK_WORDS]):
        letters = [c for c in word if c.isalpha()]
        if (len(letters) >= 2 and word.upper() == word) or word[:1].isdigit():
            return " ".join(words[index:]) if index else title
    return title


def _is_title_word(word: str) -> bool:
    """Whether a word is still part of the product's name.

    The name is set in capitals and the description is not, so the switch from
    one to the other is where the name ends. Digits and punctuation carry
    through, because a name is full of them: "6.5MM", "1940'S", "K-FRAME,",
    "S&W", ".303".
    """
    letters = [c for c in word if c.isalpha()]
    if letters:
        return word.upper() == word
    return any(c.isdigit() for c in word) or bool(word.strip(".,:;-—/&()"))


def _title_words(text_lines: list[str]) -> list[str]:
    """The leading run of name words, rejoining words broken across lines.

    The flyer hyphenates to fit its columns — "SWEDISH LEATHER AMMO BELT/BANDO-"
    on one line and "LIER can fit a variety of rifle" on the next. Reading line
    by line stopped at the hyphen and produced "SWEDISH LEATHER AMMO
    BELT/BANDO", which is not a word; the "LIER" belongs to the title and
    everything after it is description.
    """
    words: list[str] = []
    pending_hyphen = False
    after_a_heading = False
    for line in text_lines:
        # A name set as a heading ends where the heading ends. Once one has
        # contributed, a line that is not itself a heading is the description,
        # and the capital it opens with is just the start of a sentence — which
        # is how "1903 TURKISH CONTRACT MAUSERS" acquired the "MFG" of "MFG by
        # germany for The Ottoman Empire".
        #
        # Unless a word is waiting to be finished: the flyer hyphenates across
        # the break, and "BELT/BANDO-" / "LIER can fit a variety" is one word
        # spanning a heading and the prose under it.
        if words and after_a_heading and not pending_hyphen and not _is_capitalized(line):
            break
        after_a_heading = _is_capitalized(line)
        tokens = line.split()
        for index, token in enumerate(tokens):
            if pending_hyphen:
                # Splice the two halves of the broken word back together.
                words[-1] = words[-1][:-1] + token
                pending_hyphen = words[-1].endswith("-")
                if not _is_title_word(words[-1].rstrip("-")):
                    return words
                continue
            if not _is_title_word(token):
                return words
            words.append(token)
            # A hyphen at the end of a line is a break, not punctuation.
            pending_hyphen = token.endswith("-") and index == len(tokens) - 1
    return words


def _skip_to_the_first_name_word(text_lines: list[str]) -> list[str]:
    """Drop everything before the first word that could open a product name."""
    for index, line in enumerate(text_lines):
        tokens = line.split()
        for position, token in enumerate(tokens):
            if _is_title_word(token) and any(c.isalpha() for c in token):
                return [" ".join(tokens[position:]), *text_lines[index + 1 :]]
    return []


def only_this_listing(text: str, title: str) -> str:
    """Trim a listing's text down to the part that is about the listing.

    Grouping cuts a page into listings, but OCR reads *lines*, and a line
    routinely carries the tail of the panel above or the head of the one below.
    So a listing's description arrives with a neighbour attached at one end or
    the other, and anything derived from it — a caliber, a country, a maker —
    is then derived from the wrong product. Hand-woven Vaquero blankets came
    out chambered in 8mm Mauser, which is the cartridge of the Spanish M43
    rifles advertised beneath them.

    Two cuts, both from things the page itself settles:

    * **The front.** The description starts where the name does. Anything in
      front of the name belongs to whatever came before — "quality Swedish
      steel." is the end of the stock sets above the Gahendra Martini, and it
      is why the Gahendra was filed under Sweden.
    * **The back.** A bullet marks the start of a product, so the first bullet
      *after* this listing's price begins the next one. Cutting at the price
      itself would be wrong: what follows it is usually this listing's own
      terms and options, "Add $25 for hand select", which are worth keeping.

    Neither cut is applied speculatively: if the name cannot be found in the
    text, or no bullet follows the price, that end is left alone.
    """
    cleaned = text
    if title:
        start = cleaned.find(title)
        if start > 0:
            cleaned = cleaned[start:]

    price = PRICE_PATTERN.search(cleaned)
    if price is not None:
        following = BULLET_ANYWHERE.search(cleaned, price.end())
        if following is not None:
            cleaned = cleaned[: following.start()]
    return " ".join(cleaned.split()).strip()


#: A bullet anywhere in a line, rather than only at the start of one. Used to
#: find where the *next* product begins inside a run-together description.
BULLET_ANYWHERE = re.compile(
    r"[•·∙*●▪]{1,2}\s*(?=[A-Z0-9])|(?<=[.\s])[¢°«»]\s*[a-z]?\s*(?=[A-Z0-9])"
)


def _opens_with_a_shouted_name(text: str) -> bool:
    """Whether a line names a product in capitals and then keeps talking.

    "RUSSIAN M44 CARBINES good condition, cracked stock (toe)," is the whole of
    one listing on one line. The flyer sets every product name in capitals, so
    a run of capitals followed by sentence case is a name followed by its own
    description -- as distinct from "Excellent Condition rifles", which is
    prose that happens to start with a capital letter.
    """
    tokens = text.split()
    if len(tokens) <= MIN_LEADING_NAME_WORDS:
        return False
    lead = tokens[:MIN_LEADING_NAME_WORDS]
    if not all(_is_title_word(token) and token == token.upper() for token in lead):
        return False
    # A price is capitals by default, having no letters to be anything else.
    # "ONLY $219.00. Add $25 for hand select" is not a product naming itself;
    # it is the tail of the 1916 Spanish Mauser, whose name is on the line
    # above.
    if any(PRICE_PATTERN.search(token) for token in lead):
        return False
    if not any(character.isalpha() for token in lead for character in token):
        return False
    # Fully capitalised means it is a heading in its own right, not a product
    # line with prose after it.
    return not _is_capitalized(text)


def _past_a_section_header(text_lines: list[str]) -> list[str]:
    """Drop a section heading sitting above a listing that names itself.

    The flyer runs sections -- "OLE ZEKE'S TREASURES" -- above lists of
    products, and where the list is not bulleted the section name has nothing
    separating it from the first product. It was taking that product's title.

    Only a *complete* heading may be dropped, and only in front of a line that
    names itself in capitals: that is the shape of a section above a list, and
    it is not the shape of a name broken across lines ("S&W" / "K-FRAME," /
    "SNUB-NOSE" / "REVOLVER KITS"), where no line names itself and nothing is
    dropped.
    """
    for index, text in enumerate(text_lines[1:], start=1):
        if not _opens_with_a_shouted_name(text):
            continue
        if all(_is_capitalized(above) and not prices_in(above) for above in text_lines[:index]):
            return text_lines[index:]
    return text_lines


def _title_from(lines: list[TextLine]) -> str:
    """The product's name: the run of capitalised words a listing opens with.

    Read word by word rather than line by line. The flyer breaks a name over as
    many lines as it needs, hyphenating mid-word where the column runs out, and
    then continues straight into the description on the same line — "REVOLVER
    KITS" / "very good/ excellent" — so the boundary is between two words, not
    between two lines.
    """
    # A bulleted line is a product; anything above it in the same group is the
    # section header the list sits under. "OLE ZEKE'S TREASURES" is not for
    # sale, and it was taking the title of the first item beneath it.
    first_bullet = next((i for i, line in enumerate(lines) if line.is_bulleted), None)
    text_lines = [line.text for line in (lines[first_bullet:] if first_bullet else lines)]

    # Page furniture is removed from each line *before* the name is read off
    # them, not from the finished title. Doing it afterwards produced an empty
    # title for the CZ 50/70 kits: the masthead scrap "SEE OUR WEB SITE" had
    # been carried in as their heading, the name was read from that, and then
    # the whole of it was stripped away.
    cleaned = []
    for line in text_lines:
        text = _LEADING_NOISE.sub("", BULLET_PATTERN.sub("", line))
        text = _LEADING_NOISE.sub("", FURNITURE_PATTERN.sub("", text)).strip()
        # A line that is nothing but terms is dropped whole rather than
        # trimmed. Trimming a leading run off "C&R or FFL" leaves "FFL", which
        # then reads as the next word of the name above it — the 1910 Mexican
        # Mausers came out as "1910 MEXICAN MAUSER RIFLES FFL".
        if is_only_terms(text):
            continue
        text = LEADING_TERMS.sub("", text).strip()
        if text and not is_only_terms(text):
            cleaned.append(text)
    if not cleaned:
        return ""

    cleaned = _past_a_section_header(cleaned)

    title = " ".join(_title_words(cleaned))
    if len(title.strip(" .,:;-")) < MIN_TITLE_LENGTH:
        # The run stopped immediately, which means something is in front of the
        # name: a scrap of the masthead carried in with the heading, or OCR
        # noise. Skip ahead to the first word that could start a name and try
        # once more.
        skipped = _skip_to_the_first_name_word(cleaned)
        title = " ".join(_title_words(skipped)) if skipped else ""
    if len(title.strip(" .,:;-")) < MIN_TITLE_LENGTH:
        # Nothing recognisable as a name — usually a listing whose heading was
        # lost. Fall back to its opening line so it is at least identifiable.
        title = cleaned[0]

    title = PRICE_PATTERN.split(title)[0]
    for _ in range(2):
        title = FURNITURE_PATTERN.sub("", _LEADING_NOISE.sub("", title))
    title = _from_the_first_capital(title)
    return " ".join(title.split())[:200].strip(" .,:;-")


# ---------------------------------------------------------------------------
# The picture
# ---------------------------------------------------------------------------
def crop_for_listing(page: Image.Image, box: tuple[int, int, int, int], padding: int = 24) -> bytes:
    """Cut a listing's region out of the flyer as a PNG, enlarged if small.

    The flyer is the only picture this vendor publishes, so a listing's
    photograph has to come out of it. A crop of a scan is not a product
    photograph and will not look like one; enlarging a small one at least makes
    the text in it legible at card size, which is what it is for.

    PNG rather than JPEG: these are crops of an already-compressed scan, and
    re-encoding line art and small text as JPEG a second time is exactly what
    JPEG is worst at.
    """
    x0, y0, x1, y1 = box
    padded = (
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(page.width, x1 + padding),
        min(page.height, y1 + padding),
    )
    crop = page.crop(padded)
    if crop.width == 0 or crop.height == 0:
        crop = page.crop(box)

    long_edge = max(crop.size)
    if 0 < long_edge < MIN_CROP_LONG_EDGE:
        scale = min(MAX_UPSCALE, MIN_CROP_LONG_EDGE / long_edge)
        crop = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )

    buffer = io.BytesIO()
    crop.convert("L").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def columns(page: Image.Image) -> list[tuple[int, int]]:
    """The page's columns, as (left, right) x-ranges.

    Ruled divisions are preferred and whitespace is only a fallback, because a
    gutter is not as reliable a signal as it looks. On a page whose lines are
    short, the space to the right of each one lines up into a vertical band of
    blank pixels that is indistinguishable from a real gutter — measured on a
    sparse two-column test page, cutting on whitespace produced three columns
    and sliced a heading in half. A drawn rule means what it says.

    When there is no rule the fallback demands a much wider gap than the
    recursive reader would, for the same reason.
    """
    binary = _binarize(page)
    profile = _projection(binary, "v")

    def interior(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
        # A band touching an edge is the page margin, not a division.
        return [r for r in runs if r[0] > 0 and r[1] < len(profile)]

    rules = interior(_runs(profile, lambda v: v >= RULE_COVERAGE, MIN_RULE_RUN))
    if rules:
        found = _slices(rules, len(profile))
        if len(found) > 1:
            return found

    wide_gutter = max(MIN_BLANK_RUN, page.width // 40)
    gutters = interior(_runs(profile, lambda v: v <= BLANK_COVERAGE, wide_gutter))
    found = _slices(gutters, len(profile))
    return found if len(found) > 1 else [(0, page.width)]


def _panel_of(line: TextLine, boxes: list[tuple[int, int, int, int]]) -> int:
    """Which panel a line belongs to, by how much of it each panel covers.

    Not by its midpoint. A product's name is set directly on the rule that
    separates it from the panel above, so its midpoint lands in the gap between
    two panels and belongs to neither — "1893 SPANISH MAUSER LONG RIFLES" came
    back as panel -1, which then read as a panel change and cut the heading off
    from the description underneath it.

    Falling back to the nearest panel below matters for the same reason: a
    heading that overhangs its own panel entirely still introduces it.
    """
    lx0, ly0, lx1, ly1 = line.box
    best_index, best_area = -1, 0
    for index, (x0, y0, x1, y1) in enumerate(boxes):
        width = min(lx1, x1) - max(lx0, x0)
        height = min(ly1, y1) - max(ly0, y0)
        area = max(0, width) * max(0, height)
        if area > best_area:
            best_index, best_area = index, area
    if best_index >= 0:
        return best_index

    # Sitting clear of every panel: take the nearest one below that it is over.
    below = [
        (y0, index)
        for index, (x0, y0, x1, y1) in enumerate(boxes)
        if y0 >= ly0 and min(lx1, x1) - max(lx0, x0) > 0
    ]
    return min(below)[1] if below else -1


def _column_of(line: TextLine, bounds: list[tuple[int, int]]) -> int:
    """Which column a line sits in, by the midpoint of its box."""
    middle = (line.box[0] + line.box[2]) // 2
    for index, (left, right) in enumerate(bounds):
        if left <= middle < right:
            return index
    return len(bounds)


#: A region narrower or shorter than this is not split further: below it the
#: cuts start falling inside a photograph rather than between panels.
MIN_PANEL_WIDTH = 300
MIN_PANEL_HEIGHT = 200

#: How deep the panel split goes. Three levels take the real page from 2 halves
#: to 42 panels; deeper only fragments photographs.
MAX_PANEL_DEPTH = 3


def panels(page: Image.Image) -> list[Region]:
    r"""Cut the page into panels by following its drawn rules, recursively.

    Only rules, never whitespace. A rule is a line somebody drew to separate
    two things, so cutting on it cannot land inside a word; a whitespace gutter
    can, and did — the short lines at the end of a paragraph stack into a band
    of blank pixels that reads exactly like a column boundary, and cutting
    there returned OCR like "wil", "th more" and "al \".
    """
    binary = _binarize(page)
    found: list[Region] = []
    _cut_panels(binary, (0, 0, page.width, page.height), 0, found)
    return found


def _cut_panels(
    binary: Image.Image, box: tuple[int, int, int, int], depth: int, out: list[Region]
) -> None:
    x0, y0, x1, y1 = box
    if x1 - x0 < MIN_PANEL_WIDTH or y1 - y0 < MIN_PANEL_HEIGHT or depth >= MAX_PANEL_DEPTH:
        out.append(Region(box))
        return
    window = binary.crop(box)
    for axis in ("v", "h"):
        profile = _projection(window, axis)
        rules = [
            r
            for r in _runs(profile, lambda v: v >= RULE_COVERAGE, MIN_RULE_RUN)
            if r[0] > 0 and r[1] < len(profile)
        ]
        parts = _slices(rules, len(profile))
        if len(parts) > 1:
            for begin, finish in parts:
                child = (
                    (x0 + begin, y0, x0 + finish, y1)
                    if axis == "v"
                    else (x0, y0 + begin, x1, y0 + finish)
                )
                _cut_panels(binary, child, depth + 1, out)
            return
    out.append(Region(box))


def _horizontal_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """How much of the narrower box's width the two share, 0 to 1."""
    left, right = max(a[0], b[0]), min(a[2], b[2])
    narrower = min(a[2] - a[0], b[2] - b[0])
    return max(0, right - left) / max(1, narrower)


def _attach_headings(read: list[tuple[Region, list[TextLine]]]) -> list[list[TextLine]]:
    """Give each panel the heading that sits above it in a region of its own.

    The flyer draws a rule between a product's name and its description, so the
    panel cut — which follows exactly those rules — separates them. Left alone
    the heading panel has no price and is discarded, and the product is titled
    with the first line of its own prose: "with frames, used, good condition"
    rather than "MAUSER C96 PISTOL KITS".

    Headings move a line at a time rather than a panel at a time, because one
    strip across the top of the page routinely carries the headings for two or
    three panels side by side. Each line goes to the nearest panel below that
    it sits over.
    """
    ordered = sorted(range(len(read)), key=lambda i: (read[i][0].box[1], read[i][0].box[0]))
    carried: dict[int, list[TextLine]] = {}
    donors: set[int] = set()

    for position, index in enumerate(ordered):
        region, lines = read[index]
        if not lines or any(prices_in(line.text) for line in lines):
            continue
        if not all(_is_capitalized(line.text) for line in lines):
            continue

        moved = False
        for line in lines:
            target = next(
                (
                    j
                    for j in ordered[position + 1 :]
                    if read[j][0].box[1] >= region.box[1]
                    and _horizontal_overlap(line.box, read[j][0].box) > 0.6
                ),
                None,
            )
            if target is not None:
                carried.setdefault(target, []).append(line)
                moved = True
        if moved:
            donors.add(index)

    return [
        carried.get(index, []) + lines
        for index, (_region, lines) in enumerate(read)
        if index not in donors and (lines or carried.get(index))
    ]


def read_flyer(page: Image.Image) -> list[FlyerListing]:
    """Cut the page into panels, read each one, and group its lines.

    Each panel is read and grouped on its own. Pooling every line and grouping
    across the page was tried and is worse: with panels side by side the lines
    interleave and a panel ends up quoting its neighbour's price — the CZ 50/70
    pistol kit came out at the Turkish Mauser's $322.88.

    The one thing that legitimately crosses a panel boundary is a heading,
    because the flyer draws a rule between a product's name and its
    description. :func:`listings_from_lines` allows exactly that crossing.
    """
    # Read a whole column at a time. Reading panel by panel gives cleaner
    # boundaries but worse text: the cuts fall on rules that a heading sits
    # directly above, and the heading ends up in a panel of its own with no
    # price, so it is discarded and the product is titled with its own prose.
    bounds = columns(page)
    lines: list[TextLine] = []
    for left, right in bounds:
        lines.extend(read_region(page, Region((left, 0, right, page.height))))
    if not lines:
        return []

    # The panels are used only to say where one listing stops and the next
    # begins. Without them a column is grouped as one run and a product quotes
    # its neighbour's price — the CZ 50/70 pistol kit came out at the Turkish
    # Mauser's $322.88.
    boxes = [region.box for region in panels(page)]
    for line in lines:
        line.panel = _panel_of(line, boxes)

    lines.sort(key=lambda line: (_column_of(line, bounds), line.box[1], line.box[0]))

    found: list[FlyerListing] = []
    for index in range(len(bounds) + 1):
        in_column = [line for line in lines if _column_of(line, bounds) == index]
        if in_column:
            found.extend(listings_from_lines(in_column))
    return found
