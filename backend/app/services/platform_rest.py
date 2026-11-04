"""Rest a whole hosted platform when it, rather than one shop, refuses us.

A shop on Shopify is not its own web server. Every Shopify store answers from
Shopify's edge, and that edge keeps its own count of the address asking. In
November 2026 it decided this address had asked too often: Centerfire Systems,
IMA-USA, Muzzle-Loaders.com and Tortuga Trading all began answering 429 to the
first request of a scan, and so did Shopify stores this application has never
read. Each shop's own cooldown (:mod:`.cooldown`) dealt with it one host at a
time, for an hour at a time, which from Shopify's side is the same address
coming back every hour to four different doors.

So a refusal from a shop on a hosted platform is also written down against
the platform, and when **two different shops on one platform answer 429
within a day**, every shop on that platform rests for a week. The rest is
ordinary :class:`~app.models.HostCooldown` rows, one per shop, marked with the
platform, so everything that already respects a resting host -- scans, the
canary, watch polling, the inbox, the Sites page and its "Stop resting"
button -- respects this too, and when the week is up the shops are simply
fetchable again. Nobody has to re-enable anything.

The decisions worth stating.

**Hosted platforms only.** A WooCommerce shop runs on its own server, so two
of them refusing on the same day is two shops having a bad day. Shopify,
BigCommerce and Wix answer every one of their stores from shared
infrastructure; a scraper says it is on one with :attr:`SiteScraper.platform`.

**Two shops, one day.** Measured on production's history before this was
written: 2,988 scans since September, 42 of them told 429, and not once had
two shops on one platform been refused within a day until Shopify's limit --
which this rule would have caught on 2026-10-31, three days before the scans
began failing outright. A single shop rate-limiting us is the per-host
cooldown's job.

**A week, fixed.** The limit took days to build and there is no telling from
here when it lifts; a week of asking nothing is the cheapest way to find out.

**Never raises.** This runs inside the HTTP layer, on a 429. Politeness
bookkeeping that could fail a fetch would be worse than none.
"""

from __future__ import annotations

import html as _html
import logging
from datetime import datetime, timedelta
from functools import cache

from sqlalchemy import delete, select

from ..database import session_scope
from ..models import HostCooldown, PlatformRefusal, Site, as_utc, utcnow
from . import cooldown

log = logging.getLogger("milsurp.platform_rest")

#: How close together two shops' refusals must be to count as the platform's.
WINDOW = timedelta(hours=24)
#: How many different shops on one platform that takes.
THRESHOLD = 2
#: How long every shop on the platform then rests.
REST = timedelta(days=7)


def _bare(host: str) -> str:
    """A host without its ``www.``, which shops use or drop at will."""
    return host.lower().removeprefix("www.")


@cache
def _members() -> dict[str, dict[str, str]]:
    """platform -> {slug: bare host} for every registered scraper on one.

    From the registry, because a shop's own domain is all a request carries:
    nothing in ``www.ima-usa.com`` says Shopify.
    """
    from ..scrapers import _REGISTRY  # here, because the scrapers import this

    members: dict[str, dict[str, str]] = {}
    for slug, cls in _REGISTRY.items():
        platform = getattr(cls, "platform", None)
        host = _bare(cooldown.host_of(cls.base_url))
        if platform and host:
            members.setdefault(platform, {})[slug] = host
    return members


def platform_of(url: str) -> str | None:
    """The hosted platform the shop at this URL is on, or None."""
    host = _bare(cooldown.host_of(url))
    if not host:
        return None
    for platform, shops in _members().items():
        if host in shops.values():
            return platform
    return None


def saw_429(url: str) -> str | None:
    """Note that a shop answered 429; rest its platform if it is the second.

    Returns the platform when this refusal is the one that started a rest, and
    None otherwise -- including for a shop on no platform, which is nearly
    every call, and answered without touching the database.
    """
    platform = platform_of(url)
    if platform is None:
        return None
    host = cooldown.host_of(url)
    now = utcnow()
    try:
        with session_scope() as session:
            row = session.execute(
                select(PlatformRefusal).where(PlatformRefusal.host == host)
            ).scalar_one_or_none()
            if row is None:
                row = PlatformRefusal(host=host, platform=platform, refused_at=now)
                session.add(row)
            row.platform = platform
            row.refused_at = now
            session.commit()

            refusing = sorted(
                session.execute(
                    select(PlatformRefusal.host).where(
                        PlatformRefusal.platform == platform,
                        # Naive, as the column is stored.
                        PlatformRefusal.refused_at >= (now - WINDOW).replace(tzinfo=None),
                    )
                )
                .scalars()
                .all()
            )
            if len({_bare(h) for h in refusing}) < THRESHOLD:
                return None
            if _resting(session, host, now):
                # A request already in flight when the rest began. The rest it
                # would start is the one that is running.
                return None
            until = now + REST
            rested = _rest(session, platform, refusing, until, now)
            # Spent: the rest is what they bought, and a week from now they are
            # old news, not half of the next rest.
            session.execute(delete(PlatformRefusal).where(PlatformRefusal.platform == platform))
            session.commit()
    except Exception as exc:  # deliberate: see the module docstring
        log.warning("Could not record %s's 429 against %s: %s", host, platform, exc)
        return None

    log.warning(
        "%s refused %d of its shops within %s (%s); resting all %d of them until %s.",
        platform,
        len(refusing),
        WINDOW,
        ", ".join(refusing),
        len(rested),
        f"{until:%Y-%m-%d %H:%M} UTC",
    )
    _announce(platform, refusing, rested, until)
    return platform


def _resting(session, host: str, now: datetime) -> bool:
    row = session.execute(
        select(HostCooldown).where(HostCooldown.host == host)
    ).scalar_one_or_none()
    return bool(row and row.platform and (as_utc(row.until) or now) > now)


def _rest(
    session, platform: str, refusing: list[str], until: datetime, now: datetime
) -> list[Site]:
    """A week's pause for every shop on the platform, as cooldown rows."""
    slugs = list(_members().get(platform, {}))
    sites = list(session.execute(select(Site).where(Site.slug.in_(slugs))).scalars().all())
    reason = (
        f"{platform} refused {len(refusing)} of its shops within a day "
        f"({', '.join(refusing)}); every {platform} shop rests a week"
    )[:255]
    for site in sites:
        host = cooldown.host_of(site.base_url)
        if not host:
            continue
        row = session.execute(
            select(HostCooldown).where(HostCooldown.host == host)
        ).scalar_one_or_none()
        if row is None:
            row = HostCooldown(host=host, until=until, refusals=0, first_refused_at=now)
            session.add(row)
        # Never shorten a pause already set, and leave one refusal on record so
        # the shop is asked gently for a while once the week is up.
        row.until = max(until, as_utc(row.until) or until)
        row.refusals = max(row.refusals or 0, 1)
        row.reason = reason
        row.platform = platform
        row.last_refused_at = now
    session.commit()
    for site in sites:
        cooldown.forget(cooldown.host_of(site.base_url))
    return sites


def resting_hosts(session) -> dict[str, HostCooldown]:
    """Every host in a platform rest right now, by hostname."""
    now = utcnow()
    rows = (
        session.execute(
            select(HostCooldown).where(
                HostCooldown.platform.is_not(None),
                HostCooldown.until > now.replace(tzinfo=None),
            )
        )
        .scalars()
        .all()
    )
    return {row.host: row for row in rows}


def rest_for(url: str) -> HostCooldown | None:
    """The platform rest covering this URL's host, if one is running."""
    host = cooldown.host_of(url)
    if not host:
        return None
    try:
        with session_scope() as session:
            row = resting_hosts(session).get(host)
            if row is not None:
                session.expunge(row)
            return row
    except Exception as exc:  # deliberate: see the module docstring
        log.warning("Could not read the platform rests: %s", exc)
        return None


def _announce(platform: str, refusing: list[str], rested: list[Site], until: datetime) -> None:
    """Tell the administrators, once, when a rest begins.

    Only the start is mailed. The end needs nobody: the shops become
    fetchable again on their own, and a shop that then fails to scan is
    reported by the ordinary scan alerts.
    """
    from . import scanalerts  # here, because scanalerts reads the rests

    try:
        with session_scope() as session:
            addresses = scanalerts.admin_addresses(session)
        if not addresses:
            log.warning(
                "No active administrator has an email address; %s rest not reported.", platform
            )
            return
        names = ", ".join(_html.escape(site.name) for site in sorted(rested, key=lambda s: s.name))
        subject = f"Milsurp: {platform} is resting for a week"
        body = (
            f"<p>{len(refusing)} {_html.escape(platform)} shops answered 429 (too many "
            f"requests) within a day: {_html.escape(', '.join(refusing))}. When more than "
            f"one shop on the same platform does that, the platform is limiting this "
            f"address, not the shops limiting us.</p>"
            f"<p>So every {_html.escape(platform)} shop is resting until "
            f"<strong>{until:%Y-%m-%d %H:%M} UTC</strong>, and nothing will ask any of "
            f"them for anything until then: {names}.</p>"
            f"<p>Nothing needs doing. Their listings stay in the catalog, and the "
            f"shops are scanned again on their own once the week is up. To end the "
            f"rest early for a shop, use “Stop resting” on the Sites page.</p>"
        )
        scanalerts.send(addresses, subject, body, platform)
    except Exception:  # deliberate: see the module docstring
        log.warning("Could not announce the %s rest", platform, exc_info=True)
