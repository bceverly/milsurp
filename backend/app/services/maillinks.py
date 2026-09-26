"""From a vendor's marketing email to the pages it links to.

A sale email is mostly pictures and links, and the link is the one reliable
identifier in it. But almost none of the links are the shop's own: measured on
the first mail after the notification account subscribed (September 2026),
every shop but AIM Surplus wraps its links in a mailing service's click
tracker -- Klaviyo (``ctrk.klclick1.com/l/…``), Listrak (``link.botach.com/q/…``),
SendGrid, Constant Contact (``rs6.net``), Mailchimp -- and the real address is
known only to that service's server.

**How a link is followed, cheapest first:**

1. already on the shop's site: used as it is, no request;
2. carrying its destination inside it (Mailchimp's ``p=`` payload, a
   ``url=``/``original_uri=`` parameter): decoded here, no request;
3. otherwise **resolved**: one request to the tracker with redirects off,
   reading only the ``Location`` it answers with. Up to three hops, each
   decoded first where possible (Clyde's SendGrid link redirects to a Privy
   link that carries the shop address in ``original_uri``). The page at the
   end is **never requested here**; it is read, if at all, by the shop's own
   scraper under robots.txt and the rate limits.

Resolving registers a click by the subscribed account, which the administrator
agreed to when this was designed; every alternative left ten of twelve shops'
emails unread.

**Footer links are never resolved.** Unsubscribe, manage preferences, privacy,
terms, "view in browser", "forward to a friend" and the social icons are
recognized by their text or image alt and skipped before any request, and an
address whose path says unsubscribe or preferences is skipped even when its
text does not. Even a missed one would be harmless -- a redirect is read, not
followed -- but it is not left to that.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

#: Links read from one email at most. A newsletter is forty or so.
MAX_LINKS = 60

#: Redirect hops followed from a tracker before giving up.
MAX_HOPS = 3

RESOLVE_TIMEOUT = 15

#: Text or image alt that marks a link as the email's furniture, not its news.
_FOOTER = re.compile(
    r"unsubscribe|opt[\s-]?out|preferences?|privacy|terms|faqs?\b|contact\s+us|"
    r"view\s+(?:this\s+)?(?:email|online|in\s+(?:your\s+)?browser)|forward\s+to|"
    r"facebook|twitter|instagram|youtube|tiktok|pinterest|linkedin|\bx\.com\b|"
    r"about\s+us|disclaimers?|confirm\s+(?:your\s+)?subscription|refer\s+a\s+friend",
    re.I,
)

#: An address that manages the subscription itself, whatever its text says.
_SUBSCRIPTION_PATH = re.compile(
    r"unsubscribe|optout|opt-out|preference|/subscriptions?/|manage\.kmail-lists\.com|"
    r"audience\.constantcontact\.com|list-manage\.com/(?:unsubscribe|subscribe|profile|about)",
    re.I,
)

#: Query parameters that only say where a click came from.
_TRACKING_PARAM = re.compile(
    r"^(?:utm_\w+|trk_\w+|_kx|_ke|gclid|fbclid|mc_cid|mc_eid|sc_\w+|klaviyo_\w+)$",
    re.I,
)

#: Mailing services' click-tracker hosts, measured on the shops' first mail.
_TRACKER_HOSTS = re.compile(
    r"klclick|mailchimp\.com$|list-manage\.com$|rs6\.net$|ccsend\.com$|sendgrid\.net$|"
    r"privy\.com$|espssl\.com$|exacttarget|mcsv\.net$|hubspotlinks|ct\.sendgrid",
    re.I,
)

#: A click tracker on the shop's own domain, as Listrak and its kind run them:
#: ``link.botach.com/q/…``, ``enews.ima-usa.com/q/…``,
#: ``link.sportsmansoutdoorsuperstore.com/…``. Same registrable domain as the
#: shop, so without this they read as shop pages and were never resolved.
_TRACKER_LABELS = frozenset(
    {
        "link",
        "links",
        "lnk",
        "enews",
        "email",
        "emails",
        "click",
        "clicks",
        "trk",
        "track",
        "t",
        "e",
        "em",
        "mail",
        "news",
        "go",
        "r",
    }
)


#: Parameters a redirector names its destination in.
_DESTINATION_PARAMS = ("url", "u", "original_uri", "redirect", "target", "dest", "destination")


@dataclass(frozen=True)
class Link:
    url: str
    text: str


def registrable(host: str) -> str:
    return ".".join((host or "").lower().strip(".").split(".")[-2:])


def is_furniture(url: str, text: str = "") -> bool:
    """Whether a link is the email's footer rather than its news."""
    return bool(_FOOTER.search(text) or _SUBSCRIPTION_PATH.search(url))


def html_of(message_html: str) -> list[Link]:
    """The links worth following in one email, in order, footer left out."""
    soup = BeautifulSoup(message_html, "html.parser")
    found: list[Link] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href.lower().startswith(("http://", "https://")):
            continue  # mailto:, tel:, "#"
        text = " ".join(
            [anchor.get_text(" ", strip=True)]
            + [str(img.get("alt") or "") for img in anchor.select("img")]
        ).strip()
        if is_furniture(href, text) or href in seen:
            continue
        seen.add(href)
        found.append(Link(url=href, text=" ".join(text.split())[:200]))
        if len(found) >= MAX_LINKS:
            break
    return found


def is_tracker(url: str, shop_domain: str) -> bool:
    """Whether this address is a mailing service's click tracker -- the only
    kind of address the resolver ever requests."""
    host = (urlparse(url).hostname or "").lower()
    if _TRACKER_HOSTS.search(host):
        return True
    return registrable(host) == shop_domain and host.split(".")[0] in _TRACKER_LABELS


def decoded(url: str) -> str | None:
    """A destination carried inside the link itself, or None."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    # Mailchimp: click.mailchimp.com/track/click/…?p=<base64 JSON>, whose inner
    # "p" is itself JSON with the "url".
    if parsed.hostname == "click.mailchimp.com" and "p" in query:
        try:
            outer = json.loads(_b64(query["p"][0]))
            inner = json.loads(outer.get("p", "{}"))
            target = inner.get("url")
            return str(target) if target else None
        except (ValueError, TypeError, AttributeError):
            return None
    for name in _DESTINATION_PARAMS:
        for value in query.get(name, []):
            if value.lower().startswith(("http://", "https://")):
                return value
    return None


def _b64(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8", "replace")


def clean(url: str) -> str:
    """The address without its click-tracking parameters or fragment."""
    parsed = urlparse(url)
    kept = [(k, v) for k, v in parse_qsl(parsed.query) if not _TRACKING_PARAM.match(k)]
    return urlunparse(parsed._replace(query=urlencode(kept), fragment=""))


def destination(
    url: str,
    shop_domain: str,
    *,
    get: Callable[..., requests.Response] | None = None,
    user_agent: str,
) -> tuple[str | None, str]:
    """Where a link leads on the shop's site, and how that was found.

    Returns ``(url, how)``: ``how`` is "direct", "decoded", "resolved", or,
    with a None url, "offsite" (it leads somewhere that is not the shop),
    "subscription" (it manages the subscription) or "failed".
    """
    fetch = get or requests.get
    how = "direct"
    for _hop in range(MAX_HOPS + 1):
        if _SUBSCRIPTION_PATH.search(url):
            return None, "subscription"
        tracker = is_tracker(url, shop_domain)
        if not tracker and registrable(urlparse(url).hostname or "") == shop_domain:
            return clean(url), how
        inner = decoded(url)
        if inner:
            url, how = inner, "decoded" if how == "direct" else how
            continue
        # Only a tracker is ever asked. Anything else that is not the shop --
        # a GunBroker search, a financing company's disclaimer -- is where the
        # link leads, and it is not ours to fetch.
        if not tracker:
            return None, "offsite"
        if _hop == MAX_HOPS:
            break
        try:
            response = fetch(
                url,
                headers={"User-Agent": user_agent},
                allow_redirects=False,
                timeout=RESOLVE_TIMEOUT,
                stream=True,
            )
            location = response.headers.get("Location")
            response.close()
        except requests.RequestException:
            return None, "failed"
        if not location:
            # Not a redirect: a page that is not the shop's.
            return None, "offsite"
        url, how = urljoin(url, location), "resolved"
    return None, "offsite"


def normalized(url: str, *, query: bool = True) -> str:
    """A listing URL reduced to what identifies it: host without ``www.``,
    path without a trailing slash, lower case, and the non-tracking query
    unless ``query`` is False. Matching tries with the query, then without:
    a tracker can add a parameter the listing's own URL never had (Apex's
    ``cid``), and some shops identify a product only by its query."""
    parsed = urlparse(clean(url))
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    kept = f"?{parsed.query.lower()}" if query and parsed.query else ""
    return f"{host}{path}{kept}"
