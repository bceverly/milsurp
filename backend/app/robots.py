"""robots.txt, parsed properly.

The standard library has :mod:`urllib.robotparser`, and it is not good enough
for this. Measured against the real file at collectorsfirearms.com it got two
things wrong, both in the direction of crawling more than permitted:

* It ignored ``Disallow: /*?*`` and reported every query-string URL as allowed.
  That rule is the whole reason this module exists — it is what keeps a
  price monitor out of a shop's faceted-search URL space.
* It applied rules in file order rather than by specificity, so
  ``Allow: /wp-admin/admin-ajax.php`` beneath ``Disallow: /wp-admin/`` came back
  disallowed. RFC 9309 says the longest matching pattern wins, and where two
  match equally, allow wins.

So the matching here follows RFC 9309: wildcards with ``*`` and end-anchoring
with ``$``, longest match wins, ties go to allow, and an unparseable or missing
file means everything is allowed. A 5xx from the robots endpoint is treated as
"disallow everything" — the site is telling us it cannot answer, and a monitor
that guesses "yes" in that case is the one that gets a vendor's back up.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

log = logging.getLogger("milsurp.robots")

#: How long a fetched robots.txt is trusted before it is fetched again. Long
#: enough that a scan of one site reads it once, short enough that a change
#: takes effect the same day.
CACHE_SECONDS = 3600.0

#: Cap on the file we will read. A robots.txt is a few kilobytes; anything
#: past this is either a mistake or an attempt to make us hold it in memory.
MAX_BYTES = 512_000


@dataclass(frozen=True)
class Rule:
    """One Allow or Disallow line, compiled."""

    pattern: re.Pattern[str]
    #: The raw path, whose length decides which rule wins.
    length: int
    allow: bool


@dataclass
class Group:
    """The rules for one set of user-agent tokens."""

    agents: set[str] = field(default_factory=set)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _compile(path: str) -> re.Pattern[str] | None:
    """Turn a robots path pattern into a regular expression.

    ``*`` matches any run of characters and a trailing ``$`` anchors the end.
    Everything else is literal, so a path containing regex punctuation — and
    "&" and "?" are common in these files — cannot become a pattern of its own.
    """
    if not path.startswith("/"):
        return None
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    expression = "".join(
        ".*" if piece == "*" else re.escape(piece) for piece in re.split(r"(\*)", body)
    )
    try:
        return re.compile(f"^{expression}$" if anchored else f"^{expression}")
    except re.error:  # pragma: no cover - re.escape makes this unreachable
        return None


def parse(text: str) -> list[Group]:
    """Read a robots.txt into its groups.

    Consecutive ``User-agent`` lines share the rules that follow them, which is
    how a file says "these three crawlers, same rules".
    """
    groups: list[Group] = []
    current: Group | None = None
    starting = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        field_name = name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            if current is None or not starting:
                current = Group()
                groups.append(current)
                starting = True
            current.agents.add(value.lower())
            continue

        if current is None:
            # A rule before any user-agent line belongs to nobody.
            continue
        starting = False

        if field_name in ("allow", "disallow"):
            if field_name == "disallow" and not value:
                # "Disallow:" with nothing after it means "allow everything",
                # and is not a rule matching the empty path.
                continue
            pattern = _compile(unquote(value))
            if pattern is not None:
                current.rules.append(Rule(pattern, len(value), field_name == "allow"))
        elif field_name == "crawl-delay":
            try:
                current.crawl_delay = max(float(value), 0.0)
            except ValueError:
                continue

    return groups


class Robots:
    """One site's robots.txt, ready to answer questions about it."""

    def __init__(self, groups: list[Group], *, allow_all: bool = False) -> None:
        self._groups = groups
        self._allow_all = allow_all

    @classmethod
    def allowing_everything(cls) -> Robots:
        """What a missing or unreadable robots.txt means."""
        return cls([], allow_all=True)

    @classmethod
    def denying_everything(cls) -> Robots:
        """What a server error from the robots endpoint means."""
        return cls([Group(agents={"*"}, rules=[Rule(re.compile("^/"), 1, False)])])

    @classmethod
    def parse(cls, text: str) -> Robots:
        return cls(parse(text))

    def _group_for(self, user_agent: str) -> Group | None:
        """The group that applies, by RFC 9309's rules.

        A group naming our product token beats the catch-all, and the longest
        such token wins when more than one matches — a file addressing both
        "some-bot" and "some-bot/2.0" means the more specific one.
        """
        token = user_agent.lower()
        best: Group | None = None
        best_length = -1
        catch_all: Group | None = None
        for group in self._groups:
            for agent in group.agents:
                if agent == "*":
                    catch_all = catch_all or group
                elif agent and agent in token and len(agent) > best_length:
                    best, best_length = group, len(agent)
        return best or catch_all

    def allows(self, url_or_path: str, user_agent: str) -> bool:
        if self._allow_all:
            return True
        group = self._group_for(user_agent)
        if group is None or not group.rules:
            return True

        path = _path_of(url_or_path)
        winner: Rule | None = None
        for rule in group.rules:
            if not rule.pattern.match(path):
                continue
            # Longest match wins; where two match equally, allow wins.
            if winner is None or (rule.length, rule.allow) > (winner.length, winner.allow):
                winner = rule
        return winner.allow if winner else True

    def crawl_delay(self, user_agent: str) -> float | None:
        group = self._group_for(user_agent)
        return group.crawl_delay if group else None


def _path_of(url_or_path: str) -> str:
    """The path-and-query a rule is matched against."""
    if url_or_path.startswith(("http://", "https://")):
        parts = urlparse(url_or_path)
        path, query = parts.path or "/", parts.query
    else:
        path, _, query = url_or_path.partition("?")
        path = path or "/"
    return f"{path}?{query}" if query else path


class RobotsCache:
    """Fetches and remembers each site's robots.txt.

    One instance per scan. The fetch goes through the caller's own session so
    it carries the same user agent and timeouts as everything else — asking a
    site for its rules under a different identity than the one the rules will
    be applied to would be pointless.
    """

    def __init__(self, fetch, *, ttl: float = CACHE_SECONDS) -> None:
        self._fetch = fetch
        self._ttl = ttl
        self._cache: dict[str, tuple[float, Robots]] = {}

    def for_url(self, url: str) -> Robots:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._cache.get(origin)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]

        robots = self._load(f"{origin}/robots.txt")
        self._cache[origin] = (now, robots)
        return robots

    def _load(self, url: str) -> Robots:
        try:
            response = self._fetch(url)
        except Exception:
            # We could not ask. Erring towards "allowed" here would mean a
            # network blip silently turns off every restriction a site has.
            log.warning("Could not fetch %s; treating the site as off limits.", url)
            return Robots.denying_everything()

        status = getattr(response, "status_code", 0)
        if status in (401, 403):
            # The rules themselves are behind a login, which is not an
            # invitation to crawl what they might have covered.
            return Robots.denying_everything()
        if 500 <= status < 600:
            return Robots.denying_everything()
        if status != 200:
            # 404 and friends: no robots.txt, so nothing is restricted.
            return Robots.allowing_everything()

        text = getattr(response, "text", "") or ""
        if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
            log.warning("%s is implausibly large; ignoring it.", url)
            return Robots.allowing_everything()
        return Robots.parse(text)
