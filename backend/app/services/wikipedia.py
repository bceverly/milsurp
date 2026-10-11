"""Proposing a Wikipedia article for each maker and model that has none.

84 of 1,214 approved models carried a link when this was written, and makers
none at all (``Manufacturer.wikipedia_url`` is new); typing 1,200 addresses by
hand was not going to happen. So this asks Wikipedia's own search for each row
and proposes the first result that is plainly about a firearm or a firearms
maker -- judged by the article's categories, not by its title alone, because
"Model 1910" is a Mauser, an FN and a Winchester and the search will happily
answer with a district of Paris.

**Proposed, never written.** Each candidate becomes a ``ReferenceProposal``
for somebody to accept or reject on the Armory page; a rejected one is kept,
so the same article is not proposed again. ``confident`` marks the ones whose
article title names the row as well as sitting in a firearm category -- the
ones "accept all confident" takes -- and that is a label, not a decision.

**Polite by Wikipedia's rules**: an agent naming this tool and how to reach
it, one request a second, ``maxlag`` so a busy server is left alone, and a
search plus one batched category lookup per row. The links themselves are what
Wikipedia's license is for; nothing of the article is copied.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ArmoryStatus,
    FirearmModel,
    Manufacturer,
    ReferenceProposal,
    User,
)
from . import audit

API = "https://en.wikipedia.org/w/api.php"
#: Wikipedia asks API clients to say what they are and how to reach whoever
#: runs them, and refuses some generic browser strings outright.
AGENT = "MilsurpMonitor/1.0 (https://milsurpmonitor.com; armory reference links)"
#: Search results looked at per row. The first that passes is proposed.
RESULTS = 3

#: Categories an article about a gun sits in.
_GUN_CATEGORY = re.compile(
    r"firearm|rifle|pistol|revolver|carbine|shotgun|submachine gun|machine gun|"
    r"semi-automatic|bolt-action|lever-action|muzzleloader|musket|derringer|"
    r"small arms|infantry weapons|weapons of|police weapons",
    re.I,
)
#: Categories an article about a gun maker sits in.
_MAKER_CATEGORY = re.compile(
    r"firearm manufacturers|firearms manufacturers|arms manufacturers|"
    r"manufacturers of|defen[cs]e companies|weapons manufacturers|gunsmith|"
    r"arsenal|armou?ries|ammunition manufacturers",
    re.I,
)

#: Categories that make an article about a person, not a gun or a firm:
#: "Arisaka" found "Arisaka Nariakira", the colonel, before this.
_PERSON_CATEGORY = re.compile(
    r"\b(?:births|deaths|people|families|surnames|given names|politicians|"
    r"businesspeople|inventors|engineers)\b",
    re.I,
)
#: Words an article title adds to a gun's or a firm's name without changing
#: which one it is: "AA-52 machine gun" is the AA52.
_GENERIC = frozenset(
    [
        "rifle",
        "rifles",
        "pistol",
        "pistols",
        "revolver",
        "carbine",
        "machine",
        "gun",
        "guns",
        "submachine",
        "shotgun",
        "model",
        "company",
        "corporation",
        "firearms",
        "arms",
        "inc",
        "co",
        "ltd",
        "the",
        "of",
    ]
)

Fetch = Callable[[dict[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    confident: bool
    reason: str


def http_fetch(session: requests.Session | None = None, pause: float = 1.0) -> Fetch:
    """A fetch that asks the real API, one request a second."""
    client = session or requests.Session()

    def fetch(params: dict[str, str]) -> dict[str, Any]:
        response = client.get(
            API,
            params={**params, "format": "json", "formatversion": "2", "maxlag": "5"},
            headers={"User-Agent": AGENT},
            timeout=30,
        )
        response.raise_for_status()
        time.sleep(pause)
        answer = response.json()
        if isinstance(answer, dict) and answer.get("error", {}).get("code") == "maxlag":
            # Wikipedia is busy. Wait as long as it says and ask once more.
            time.sleep(float(response.headers.get("Retry-After", "5")))
            return fetch(params)
        return answer if isinstance(answer, dict) else {}

    return fetch


def article_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"), safe="_()'-.,")


def _words(text: str) -> list[str]:
    """Lower-case words, accents taken off: "Anschütz" is "anschutz"."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", plain.lower())


def names_it(title: str, spellings: Iterable[str]) -> bool:
    """Whether an article's title is one of the row's names.

    Either every word of a name appears in the title, or the title, run
    together and stripped of the generic words an encyclopedia adds, is the
    name run together: "AA-52 machine gun" is "AA52", "Auto-Ordnance
    Corporation" is "Auto-Ordnance".
    """
    words = _words(title)
    have = set(words)
    core = "".join(word for word in words if word not in _GENERIC)
    for spelling in spellings:
        mine = _words(spelling)
        if mine and set(mine) <= have:
            return True
        if len("".join(mine)) >= 4 and "".join(mine) == core:
            return True
    return False


def search(fetch: Fetch, query: str) -> list[str]:
    answer = fetch(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(RESULTS),
            "srnamespace": "0",
        }
    )
    return [hit["title"] for hit in (answer.get("query") or {}).get("search") or []]


def categories(fetch: Fetch, titles: list[str]) -> dict[str, list[str]]:
    """Each article's visible categories, by the title it was asked for."""
    if not titles:
        return {}
    answer = fetch(
        {
            "action": "query",
            "prop": "categories",
            "titles": "|".join(titles),
            "cllimit": "max",
            "clshow": "!hidden",
            "redirects": "1",
        }
    )
    query = answer.get("query") or {}
    # Asked-for title -> the title of the page it ended up at.
    landed = {title: title for title in titles}
    for hop in (*(query.get("normalized") or []), *(query.get("redirects") or [])):
        for asked, at in list(landed.items()):
            if at == hop.get("from"):
                landed[asked] = hop.get("to")
    by_page = {
        page.get("title"): [c.get("title", "") for c in page.get("categories") or []]
        for page in query.get("pages") or []
    }
    return {asked: by_page.get(at, []) for asked, at in landed.items()}


def candidate(
    fetch: Fetch, query: str, spellings: list[str], kind: str, refused: set[str]
) -> Candidate | None:
    """The first search result that is an article about this kind of thing."""
    titles = search(fetch, query)
    found = categories(fetch, titles)
    wanted = _MAKER_CATEGORY if kind == "manufacturer" else _GUN_CATEGORY
    for title in titles:
        url = article_url(title)
        if url in refused:
            continue
        cats = found.get(title, [])
        if any(_PERSON_CATEGORY.search(c) for c in cats):
            continue
        matched = [c.removeprefix("Category:") for c in cats if wanted.search(c)]
        if not matched:
            continue
        confident = names_it(title, spellings)
        reason = ("title matches; " if confident else "") + f"in Category:{matched[0]}"
        return Candidate(title, url, confident, reason)
    return None


def _query_for(row: FirearmModel | Manufacturer) -> tuple[str, str]:
    if isinstance(row, Manufacturer):
        return "manufacturer", f"{row.name} firearms"
    maker = row.manufacturer_names[0] if row.manufacturer_names else ""
    words = set(_words(row.name))
    if maker and not set(_words(maker)) <= words:
        return "model", f"{maker} {row.name}"
    return "model", row.name


def run(
    session: Session,
    fetch: Fetch,
    *,
    limit: int | None = None,
    kinds: Iterable[str] = ("manufacturer", "model"),
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Propose an article for every approved row without a link or a pending
    proposal. Returns counts: rows asked about, proposals written, of them
    confident, and rows nothing suitable was found for."""
    counts = {"asked": 0, "proposed": 0, "confident": 0, "nothing": 0}
    pending = {
        (p.target_type, p.target_id)
        for p in session.execute(
            select(ReferenceProposal).where(ReferenceProposal.status == "pending")
        ).scalars()
    }
    refused: dict[tuple[str, int], set[str]] = {}
    for proposal in session.execute(
        select(ReferenceProposal).where(ReferenceProposal.status == "rejected")
    ).scalars():
        refused.setdefault((proposal.target_type, proposal.target_id), set()).add(proposal.url)
    for kind in kinds:
        for row in _unlinked(session, kind):
            if limit is not None and counts["asked"] >= limit:
                return counts
            if (kind, row.id) in pending:
                continue
            counts["asked"] += 1
            _kind, query = _query_for(row)
            try:
                found = candidate(
                    fetch, query, row.spellings, kind, refused.get((kind, row.id), set())
                )
            except (requests.RequestException, ValueError) as exc:
                log(f"  {row.name}: Wikipedia did not answer ({exc}); trying the next.")
                continue
            if found is None:
                counts["nothing"] += 1
                continue
            session.add(
                ReferenceProposal(
                    target_type=kind,
                    target_id=row.id,
                    url=found.url,
                    title=found.title,
                    confident=found.confident,
                    reason=found.reason,
                )
            )
            counts["proposed"] += 1
            counts["confident"] += int(found.confident)
            log(f"  {row.name}: {found.title}{' (confident)' if found.confident else ''}")
            if counts["proposed"] % 25 == 0:
                session.commit()
    session.commit()
    return counts


def _unlinked(session: Session, kind: str) -> list[FirearmModel] | list[Manufacturer]:
    """The approved rows of one table with no article, oldest first."""
    if kind == "manufacturer":
        return list(
            session.execute(
                select(Manufacturer)
                .where(
                    Manufacturer.status == ArmoryStatus.APPROVED,
                    Manufacturer.enabled.is_(True),
                    Manufacturer.wikipedia_url.is_(None),
                )
                .order_by(Manufacturer.id)
            ).scalars()
        )
    return list(
        session.execute(
            select(FirearmModel)
            .where(
                FirearmModel.status == ArmoryStatus.APPROVED,
                FirearmModel.enabled.is_(True),
                FirearmModel.wikipedia_url.is_(None),
            )
            .order_by(FirearmModel.id)
        ).scalars()
    )


def _target(session: Session, proposal: ReferenceProposal) -> FirearmModel | Manufacturer | None:
    if proposal.target_type == "manufacturer":
        return session.get(Manufacturer, proposal.target_id)
    return session.get(FirearmModel, proposal.target_id)


def accept(session: Session, ids: Iterable[int], actor: User | None) -> int:
    """Write each proposal's article onto its row, unless the row has gained
    one meanwhile. Returns how many rows took one."""
    taken = 0
    for proposal in session.execute(
        select(ReferenceProposal).where(
            ReferenceProposal.id.in_(list(ids)), ReferenceProposal.status == "pending"
        )
    ).scalars():
        row = _target(session, proposal)
        proposal.status = "accepted"
        if row is None or row.wikipedia_url:
            continue
        row.wikipedia_url = proposal.url
        taken += 1
        audit.record(
            session,
            actor=actor,
            action=audit.ARMORY_EDITED,
            target_type=proposal.target_type,
            target_id=row.id,
            target_label=row.name,
            detail=f"Wikipedia: {proposal.title}",
            before={"wikipedia_url": None},
        )
    session.commit()
    return taken


def reject(session: Session, ids: Iterable[int]) -> int:
    rows = session.execute(
        select(ReferenceProposal).where(
            ReferenceProposal.id.in_(list(ids)), ReferenceProposal.status == "pending"
        )
    ).scalars()
    count = 0
    for proposal in rows:
        proposal.status = "rejected"
        count += 1
    session.commit()
    return count


def pending(session: Session) -> list[tuple[ReferenceProposal, str]]:
    """Every pending proposal with the name of the row it is for."""
    found = []
    for proposal in session.execute(
        select(ReferenceProposal)
        .where(ReferenceProposal.status == "pending")
        .order_by(ReferenceProposal.confident.desc(), ReferenceProposal.id)
    ).scalars():
        row = _target(session, proposal)
        if row is not None:
            found.append((proposal, row.name))
    return found
