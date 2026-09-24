"""Mail a new flyer the day it is read.

Hunter's Lodge publish their stock as one scanned advertisement at a time, and
it turns over by the issue. Waiting for the next digest is the difference
between seeing a new issue first and seeing it after the good rifles have gone,
so a scan that reads a flyer nobody has been told about mails it at once.

**What "new" means is already in the keys.** Every listing read from a flyer
carries that flyer's signature as the prefix of its external key (see
``hunters_lodge.signature_of``), and :class:`FlyerNotice` remembers which
signatures have been mailed. A flyer is new when its listings are active and
its signature is not in that table -- which also makes this safe to call more
than once: the second call finds nothing.

**Only active listings are considered.** When a new flyer arrives, the scan
de-lists the last one's listings (Hunter's Lodge is exempt from the shrink
guard for exactly this), so an old flyer never comes back as news. And the
flyer that was already on the shelf when this shipped was read by a scan that
reported itself unchanged, which does not call this at all.

**Who gets it:** every active account with an address, except anyone whose
digest settings name the sites they want and leave this one out. That is the
nearest thing a reader already has to "not this shop", and asking them to
switch it off a second time somewhere else would be asking twice.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Config, get_config
from ..models import EmailPreference, EmailStatus, FlyerNotice, Item, Site, User, utcnow
from ..scrapers import get_scraper_class

log = logging.getLogger("milsurp.flyer_alert")


def _signature_reader(site: Site):
    """The function that reads a flyer signature off this site's keys, if any."""
    scraper = get_scraper_class(site.slug)
    if scraper is None or not getattr(scraper, "announces_new_catalog", False):
        return None
    return getattr(scraper, "catalog_signature", None)


def new_flyers(session: Session, site: Site) -> dict[str, list[Item]]:
    """Active listings grouped by a flyer signature nobody has been told about."""
    reader = _signature_reader(site)
    if reader is None:
        return {}
    told = set(
        session.execute(select(FlyerNotice.signature).where(FlyerNotice.site_id == site.id))
        .scalars()
        .all()
    )
    grouped: dict[str, list[Item]] = defaultdict(list)
    for item in session.execute(
        select(Item).where(Item.site_id == site.id, Item.is_active.is_(True)).order_by(Item.id)
    ).scalars():
        signature = reader(item.external_key)
        if signature and signature not in told:
            grouped[signature].append(item)
    return dict(grouped)


def recipients(session: Session, site: Site) -> list[User]:
    """Everybody with an address, bar anyone whose digest leaves this site out."""
    users = (
        session.execute(
            select(User).where(User.is_active.is_(True), User.email.is_not(None), User.email != "")
        )
        .scalars()
        .all()
    )
    chosen: dict[int, list[int]] = {
        preference.user_id: preference.site_ids
        for preference in session.execute(select(EmailPreference)).scalars()
    }
    return [
        user
        for user in users
        # No row, or a row with no sites named, means every site.
        if not chosen.get(user.id) or site.id in chosen[user.id]
    ]


def announce(
    session: Session, site: Site, *, partial: bool = False, config: Config | None = None
) -> int:
    """Mail every new flyer for this site to its readers. Returns emails sent.

    The notice is written once the flyer has gone to everybody it was going to,
    whether or not every send succeeded: a failed send is recorded in the email
    log like any other, and retrying the whole flyer next scan would mail the
    readers who did get it a second time.
    """
    from . import digest  # the renderer and the mailer live there

    config = config or get_config()
    flyers = new_flyers(session, site)
    if not flyers:
        return 0
    readers = recipients(session, site)
    sent = 0
    for signature, items in flyers.items():
        delivered = 0
        for user in readers:
            entry = digest.send_new_flyer(
                session, user, site, items, partial=partial, config=config
            )
            if entry.status == EmailStatus.SENT:
                delivered += 1
        session.add(
            FlyerNotice(
                site_id=site.id,
                signature=signature,
                listings=len(items),
                recipients=delivered,
                partial=partial,
                sent_at=utcnow(),
            )
        )
        session.commit()
        log.info(
            "New %s flyer %s: %d listing(s) mailed to %d reader(s).",
            site.name,
            signature,
            len(items),
            delivered,
        )
        sent += delivered
    return sent
