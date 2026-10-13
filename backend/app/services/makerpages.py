"""Finding each model's own page on its maker's site.

Asked for on 2026-10-12, in place of the search of the maker's site that slice
1 of "New-gun prices, and the makers' own pages" linked to: "i had hoped you
could scan, find the appropriate manufacturer's product page, store that link
in the armory and then surface it ... inside of the 'what the armory knows'
popup."

**Read from the maker's sitemap**, the list of its pages a site publishes for
search engines -- one to a few dozen requests per maker rather than one per
model, and the same list whatever the site's theme. Found through robots.txt's
``Sitemap:`` lines, or ``/sitemap.xml`` and ``/sitemap_index.xml`` where it
names none; an index is followed into the sitemaps it lists, those that look
like products first. Everything through ``ScrapeContext``, so under robots.txt,
the request delay and the cooldown register: a maker that answers with a bot
control (Sig Sauer, HK and Mossberg did, measured 2026-10-12) is not read.

**Matched on the page's address, not its contents.** A product page's last
path segment is its name -- ``/products/pistols/g19-gen5``,
``/product/m-p-shield-plus`` -- so the model's own words, less the maker's, are
looked for in it as words, in order. "Confident" is a slug that is the model's
name and little else; a longer one ("glock-19-gen-5-mos-fs") is proposed but
not confident.

**Proposed, never written.** Each find is a ``ReferenceProposal`` with
``field="maker_page"``, accepted or rejected on the Armory's Manufacturer pages tab
the way a Wikipedia article is; accepting writes ``FirearmModel.maker_url``.
A rejection is final for the model, as it is for an article.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ArmoryStatus, FirearmModel, ReferenceProposal
from ..scrapers.base import Disallowed, ScrapeContext, ScrapeError

FIELD = "maker_page"

#: Sitemaps followed from one index at most, and addresses kept from a maker.
MAX_SITEMAPS = 40
MAX_PAGES = 30_000

#: A page that is never a product page, whatever its name says.
_NOT_A_PRODUCT = re.compile(
    r"/(?:blog|news|press|article|articles|video|videos|support|manual|manuals|faq|"
    r"dealer|dealers|careers|events|category|categories|tag|tags|search|cart|account|"
    r"warranty|recall|recalls|media|catalog/category|collections?/all|journal|"
    r"journal-entry|product-tag|product-category|magazines|accessories|parts|gear|"
    r"apparel|holsters?|spare-parts|pistol-parts|rifle-parts|replacement-parts)(?:/|$)"
    # Any section about the bits that go on a gun: Beretta files a PX4
    # Storm page under "/gun-accessories/accessories-by-gun-family/".
    r"|/[^/]*(?:accessor|parts)[^/]*/" r"|\.(?:pdf|jpe?g|png|gif|webp|zip)$",
    re.I,
)
#: A slug that is about a gun rather than the gun: a review, an announcement,
#: a safety notice. Kahr's sitemap lists "kahr-arms-cw380-pistol-review".
_NOT_A_PRODUCT_WORD = frozenset(
    {
        "review",
        "reviews",
        "introduces",
        "announces",
        "announcement",
        "notice",
        "safetynotice",
        "giveaway",
        "recall",
        "handcuffs",
        "holster",
        "magazine",
        "magazines",
        "grips",
        "sights",
        "barrel",
        "slide",
        "kit",
        "manual",
        "owners",
    }
)
#: Words a model's name carries that a product slug leaves out, or that mean
#: nothing on their own.
_FILLER = frozenset({"the", "and", "with", "w", "pistol", "pistols", "rifle", "revolver"})
#: Words a product address carries around the model's name that say nothing
#: about which model: "/1911-series-handguns/", "/firearms/revolvers/taurus-judge/".
_GENERIC = frozenset(
    {
        "series",
        "handgun",
        "handguns",
        "pistol",
        "pistols",
        "revolver",
        "revolvers",
        "rifle",
        "rifles",
        "shotgun",
        "shotguns",
        "firearm",
        "firearms",
        "product",
        "products",
        "detail",
        "page",
        "the",
        "and",
        "arms",
        "inc",
        "us",
        "usa",
        "family",
    }
)
#: A section of a maker's site for agencies rather than the public: Glock lists
#: its G17 under both, and the public one is the page to show.
_AGENCY = re.compile(r"law-?enforcement|/le/|police|military|government", re.I)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


@dataclass(frozen=True)
class Page:
    url: str
    confident: bool
    reason: str


def _words(text: str) -> list[str]:
    """Lowercase words and numbers: "M&P9 Shield Plus" is m, p, 9, shield, plus;
    a generation stays whole ("gen_5", from _slug)."""
    return re.findall(r"gen_\d+|[a-z]+|\d+", text.lower().replace("&", " "))


def _model_words(name: str, makers: Iterable[str]) -> list[str]:
    """A model's name less its maker's: "Smith & Wesson M&P Shield" is m p shield."""
    words = _words(name)
    for maker in sorted(makers, key=len, reverse=True):
        drop = _words(maker)
        if drop and words[: len(drop)] == drop:
            words = words[len(drop) :]
            break
    return [w for w in words if w not in _FILLER]


def _slug(url: str) -> list[str]:
    path = urlsplit(url).path.rstrip("/")
    last = path.rsplit("/", 1)[-1]
    last = re.sub(r"\.(?:html?|php|aspx?)$", "", last, flags=re.I)
    # A generation is one word: Glock's "g17-gen5" is g, 17 and gen5.
    return _words(re.sub(r"(?i)\bgen-?(\d)", r"gen_\1", last))


def _contains(have: list[str], need: list[str], initial: str) -> int | None:
    """Where *need* starts in *have*, as consecutive words, or None.

    Numbers may carry the maker's initial or run into the word before them --
    Glock writes its 19 as "g19", Smith & Wesson its M&P 9 as "m-p9" -- so a
    number is also found inside a word ending with it.
    """
    if not need:
        return None
    for start in range(len(have)):
        index, ok = start, True
        for word in need:
            if index >= len(have):
                ok = False
                break
            token = have[index]
            if token == word or (
                word.isdigit()
                and (
                    token == f"{initial}{word}"
                    or (
                        token.endswith(word)
                        and token[: -len(word)].isalpha()
                        and len(token) - len(word) <= 2
                    )
                )
            ):
                index += 1
                continue
            ok = False
            break
        if ok:
            return start
    # Run together: "mp9" for "m p 9" -- as whole words of the slug, so
    # "model10" is not found inside "model-103-1-handcuffs".
    compact = "".join(need)
    if len(compact) >= 3:
        for start in range(len(have)):
            for end in range(start + 1, len(have) + 1):
                window = "".join(have[start:end])
                if window == compact:
                    return start
                if len(window) > len(compact):
                    break
    return None


def best_page(pages: Iterable[str], names: Iterable[str], makers: Iterable[str]) -> Page | None:
    """The page most plainly about this model, or None.

    *names* are the model's spellings, its own name first. A page qualifies
    when one spelling's words, less the maker's, are in its slug in order. Of
    those, the one with the fewest words beyond the model's -- not counting the
    maker's name or words like "series" and "handguns" -- wins, "g19-gen5" over
    "g19-gen5-mos-fs", and is confident when what is left over is no more than
    a generation or a size and no other page is as close.
    """
    makers = list(makers)
    initial = _words(makers[0])[0][:1] if makers and _words(makers[0]) else ""
    # The maker's initial too: Glock writes its 19 as "g19", read as g and 19.
    maker_words = {w for maker in makers for w in _words(maker)} | ({initial} if initial else set())
    wanted = []
    for name in names:
        words = _model_words(name, makers)
        if words and words not in wanted:
            wanted.append(words)
    if not wanted:
        return None
    found: list[tuple[int, int, int, str, tuple[str, ...]]] = []
    for url in pages:
        path = urlsplit(url).path
        if _NOT_A_PRODUCT.search(path):
            continue
        slug = _slug(url)
        if not slug or _NOT_A_PRODUCT_WORD & set(slug):
            continue
        for rank, words in enumerate(wanted):
            # A bare number is too little to go on: "19" is in a hundred slugs.
            if len(words) == 1 and words[0].isdigit() and not initial:
                continue
            start = _contains(slug, words, initial)
            if start is None:
                continue
            rest = tuple(
                w
                for i, w in enumerate(slug)
                if not start <= i < start + len(words)
                and w not in maker_words
                and w not in _GENERIC
            )
            agency = 1 if _AGENCY.search(path) else 0
            found.append((len(rest), rank, agency, url, rest))
            break
    if not found:
        return None
    # The public page before an agencies' one, whatever else it carries.
    found.sort(key=lambda row: (row[2], row[0], row[1], len(row[3])))
    extra, _rank, agency, url, rest = found[0]
    small = all(
        re.fullmatch(r"gen_?\d*|v|\d|g\d|compact|subcompact|sc|fs|full|size|m\d|us", w)
        for w in rest
    )
    best = tuple(_slug(url))
    # The same product under another section is not a rival: Glock's G17 is
    # under both its law-enforcement and its commercial pages.
    ties = {
        row[3]
        for row in found
        if row[2] == agency and row[0] == extra and tuple(_slug(row[3])) != best
    }
    confident = extra <= 1 and small and not ties
    reason = f"in the manufacturer's sitemap: {urlsplit(url).path}"
    if ties:
        reason += f" (and {len(ties)} more as close)"
    return Page(url=url, confident=confident, reason=reason)


# -- Reading a maker's sitemap ----------------------------------------------
def _locs(xml: str) -> list[str]:
    return _LOC.findall(xml or "")


def sitemap_pages(ctx: ScrapeContext, website: str, log: Callable[[str], None]) -> list[str]:
    """Every page a maker's sitemaps list, or [] where none can be read.

    Where the maker's address names a section of its site -- Beretta's is
    ``/en-us`` -- that section's sitemaps are read first and only its pages
    kept: Beretta's robots.txt lists a sitemap per country, Austria's first,
    and the first pass matched every Beretta to a German page.
    """
    section = urlsplit(website).path.strip("/").lower()
    root = f"{urlsplit(website).scheme or 'https'}://{urlsplit(website).netloc or website}/"
    starts: list[str] = []
    try:
        robots = ctx.get_text(urljoin(root, "robots.txt"))
        starts = [
            line.split(":", 1)[1].strip()
            for line in robots.splitlines()
            if line.lower().startswith("sitemap:")
        ]
    except (Disallowed, ScrapeError):
        pass
    starts = starts or [urljoin(root, "sitemap.xml"), urljoin(root, "sitemap_index.xml")]
    if section:
        starts.sort(key=lambda url: 0 if f"/{section}/" in url.lower() else 1)
    pages: list[str] = []
    queue = list(dict.fromkeys(starts))
    read = 0
    while queue and read < MAX_SITEMAPS and len(pages) < MAX_PAGES:
        url = queue.pop(0)
        read += 1
        try:
            xml = ctx.get_text(url)
        except (Disallowed, ScrapeError) as exc:
            log(f"    {url}: not read ({exc})")
            continue
        locs = _locs(xml)
        if "<sitemapindex" in xml.lower():
            # Product sitemaps first; a blog's or a news section's last.
            children = sorted(
                locs,
                key=lambda u: (
                    0 if section and f"/{section}/" in u.lower() else 1,
                    0 if re.search(r"product|firearm|gun|pistol|rifle", u, re.I) else 1,
                ),
            )
            queue.extend(child for child in children if child not in queue)
        else:
            pages.extend(locs)
    pages = list(dict.fromkeys(pages))
    if section:
        mine = [url for url in pages if urlsplit(url).path.lower().startswith(f"/{section}/")]
        pages = mine or pages
    return pages[:MAX_PAGES]


# -- Makers with no sitemap that can be read -----------------------------------
def _host(url: str) -> str:
    host = urlsplit(url if "://" in url else f"https://{url}").hostname or ""
    return host.removeprefix("www.")


def _ruger(ctx: ScrapeContext, model: FirearmModel) -> list[str]:
    from .makersites import RugerReader

    return RugerReader().models_pages(ctx, model)


def _walther(ctx: ScrapeContext, model: FirearmModel) -> list[str]:
    from .makersites import WaltherReader

    return WaltherReader().line_pages(ctx, model)


#: Ruger and Walther publish no sitemap that can be read, but the variant
#: readers (app.services.makersites) already find a model's product-line page
#: from their navigation -- which is the page to show.
_READERS: dict[str, Callable[[ScrapeContext, FirearmModel], list[str]]] = {
    "ruger.com": _ruger,
    "waltherarms.com": _walther,
}


def _from_reader(
    ctx: ScrapeContext,
    reader: Callable[[ScrapeContext, FirearmModel], list[str]] | None,
    model: FirearmModel,
) -> Page | None:
    if reader is None:
        return None
    try:
        found = reader(ctx, model)
    except (Disallowed, ScrapeError):
        return None
    if not found:
        return None
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    return Page(
        url=found[0],
        confident=len(found) == 1,
        reason=f"the product line the manufacturer's own navigation names{more}",
    )


# -- The pass ---------------------------------------------------------------
def _title(url: str) -> str:
    """What the review tab calls a page: its name, not "models.html"."""
    parts = [p for p in urlsplit(url).path.split("/") if p]
    while len(parts) > 1 and re.fullmatch(r"(?:models|index|overview)\.html?", parts[-1], re.I):
        parts.pop()
    return parts[-1] if parts else url


def _decided(session: Session) -> set[int]:
    """Models with a maker-page proposal pending or ever rejected."""
    return set(
        session.execute(
            select(ReferenceProposal.target_id).where(
                ReferenceProposal.field == FIELD,
                ReferenceProposal.target_type == "model",
                ReferenceProposal.status.in_(("pending", "rejected")),
            )
        ).scalars()
    )


def run(
    session: Session,
    ctx: ScrapeContext,
    *,
    maker: str | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Propose a product page for every model in modern production without
    one. Returns counts: models asked about, proposed, confident, none found,
    and makers whose site could not be read."""
    counts = {"asked": 0, "proposed": 0, "confident": 0, "nothing": 0, "unread": 0}
    decided = _decided(session)
    by_site: dict[str, list[FirearmModel]] = {}
    makers_of: dict[int, list[str]] = {}
    for model in session.execute(
        select(FirearmModel).where(
            FirearmModel.status == ArmoryStatus.APPROVED,
            FirearmModel.enabled.is_(True),
            FirearmModel.modern_production.is_(True),
            FirearmModel.maker_url.is_(None),
        )
    ).scalars():
        if model.id in decided:
            continue
        for firm in model.manufacturers:
            if not firm.website or (maker and firm.name.lower() != maker.lower()):
                continue
            by_site.setdefault(firm.website, []).append(model)
            makers_of[model.id] = list(firm.spellings)
            break
    for website, models in sorted(by_site.items()):
        log(f"  {website}: {len(models)} model(s)")
        pages = sitemap_pages(ctx, website, log)
        reader = _READERS.get(_host(website))
        if not pages and reader is None:
            counts["unread"] += 1
            log("    no sitemap could be read; skipped")
            continue
        for model in models:
            counts["asked"] += 1
            if pages:
                found = best_page(pages, model.spellings, makers_of[model.id])
            else:
                found = _from_reader(ctx, reader, model)
            if found is None:
                counts["nothing"] += 1
                continue
            # Another run, or a person, may have decided this model since the
            # list was drawn up: two runs at once, on 2026-10-13, had the
            # second fail on the first one's rows and lose its whole batch.
            if model.id in _decided(session):
                continue
            session.add(
                ReferenceProposal(
                    field=FIELD,
                    target_type="model",
                    target_id=model.id,
                    url=found.url,
                    title=_title(found.url),
                    confident=found.confident,
                    reason=found.reason,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                continue
            counts["proposed"] += 1
            counts["confident"] += int(found.confident)
            log(f"    {model.name}: {found.url}{' (confident)' if found.confident else ''}")
    return counts
