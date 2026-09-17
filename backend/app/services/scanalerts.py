"""Mail the administrators when a shop stops scraping, and when it starts again.

The canary already probes every shop nightly and mails what it finds, which
covers a vendor quietly changing its markup. It is a *separate probe*, though,
and that leaves two gaps this closes:

* **Latency.** The canary runs once a day. A scan that dies at two in the
  morning waits until ten past six to be noticed, and a scraper is most often
  looked at on the morning somebody is already annoyed.
* **Depth.** The canary consumes three listings and walks away, which is the
  right trade for a sweep of twenty-eight shops. A failure on page nine -- a
  pagination change, a detail page that started 404ing -- happens well past
  where it stops looking, so it can pass while every real scan fails.

**A change of state, never a standing condition.** This is the whole discipline
of the module and the reason it is worth having at all: a site broken for a
fortnight must not mail every night for a fortnight, because by the third night
it is a rule in somebody's mail client and by the fifth the next real failure
goes in the same folder. So the question asked here is not "did this scan
fail?" -- it is "is this different from last time?"

Recovery is reported for the same reason failure is: somebody who was told a
shop went quiet is owed the sentence that says it came back, and without it the
only way to find out is to go and look.

Never raises. Alerting that can break a scan is worse than no alerting: it
turns every mail outage into a scraping outage, and the failure it reports is
its own.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ScanRun, ScanStatus, Site, User, UserRole
from . import mailer

log = logging.getLogger("milsurp.scanalerts")

#: A finished scan that did what it was asked. PARTIAL belongs here: some pages
#: or images failed and the rest of the catalog came through, which is a
#: warning on the scan's own record and not a shop that has stopped answering.
HEALTHY = (ScanStatus.SUCCESS, ScanStatus.PARTIAL)

#: Statuses that say nothing about the vendor and so never move the state. A
#: canceled scan is an administrator pressing stop, and a running one has not
#: finished having an opinion.
IGNORED = (ScanStatus.CANCELED, ScanStatus.RUNNING)


def _previous_verdict(session: Session, site_id: int, before_run_id: int) -> bool | None:
    """Whether the run before this one was healthy, or None if there wasn't one.

    Ordered by id rather than by ``started_at``: two scans of one site cannot
    overlap, but a clock that steps backwards would reorder them, and the id is
    monotonic whatever the clock does.
    """
    row = session.execute(
        select(ScanRun.status)
        .where(
            ScanRun.site_id == site_id,
            ScanRun.id < before_run_id,
            ScanRun.status.not_in(IGNORED),
        )
        .order_by(ScanRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return row in HEALTHY


def _admin_addresses(session: Session) -> list[str]:
    users = (
        session.execute(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
        .scalars()
        .all()
    )
    return [user.email for user in users if user.email]


def _broken_message(site: Site, run: ScanRun) -> tuple[str, str]:
    detail = (run.error_message or "no detail recorded").replace("&", "&amp;").replace("<", "&lt;")
    subject = f"Milsurp: {site.name} stopped scraping"
    html = (
        f"<p><strong>{site.name}</strong> ({site.slug}) failed its scan.</p>"
        f"<pre style='font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;"
        f"white-space:pre-wrap'>{detail}</pre>"
        f"<p>Its listings are still in the catalog and are not being de-listed; "
        f"what has stopped is the scan that keeps them current. You will get one "
        f"more message when it scrapes again, and none in between.</p>"
    )
    return subject, html


def _recovered_message(site: Site, run: ScanRun) -> tuple[str, str]:
    subject = f"Milsurp: {site.name} is scraping again"
    html = (
        f"<p><strong>{site.name}</strong> ({site.slug}) completed a scan: "
        f"{run.items_found:,} listing(s) seen, {run.items_new:,} new.</p>"
    )
    return subject, html


def _send(addresses: list[str], subject: str, html: str, slug: str) -> None:
    """One message each.

    A mail that will not go is logged and not retried: the next state change
    will try again, and a retry loop inside a scan is another way to turn a
    mail outage into a scraping one.
    """
    for address in addresses:
        try:
            mailer.send_html(address, subject, html)
        except mailer.MailError as exc:
            log.warning("Could not mail %s about %s: %s", address, slug, exc)


def consider(session: Session, site: Site, run: ScanRun) -> str | None:
    """Mail the admins if this run's verdict differs from the last one.

    Returns what was sent -- ``"broken"``, ``"recovered"`` or None -- for the
    caller's log and for the tests. Called after the run is committed, so a
    message can never describe a scan that was then rolled back.
    """
    try:
        if run.status in IGNORED:
            return None
        healthy = run.status in HEALTHY
        previous = _previous_verdict(session, site.id, run.id)

        # A first-ever scan that fails is news; a first-ever scan that works is
        # not. Nobody needs telling that a thing did what it was installed to
        # do.
        if previous is None and healthy:
            return None
        if previous is not None and previous == healthy:
            return None

        subject, html = _recovered_message(site, run) if healthy else _broken_message(site, run)
        addresses = _admin_addresses(session)
        if not addresses:
            log.warning("No active administrator has an email address; %s not reported.", site.slug)
            return None
        _send(addresses, subject, html, site.slug)
    except Exception:
        # See the module docstring: alerting that can break a scan turns a mail
        # outage into a scraping outage.
        log.warning("Scan alerting failed for %s", site.slug, exc_info=True)
        return None
    else:
        return "recovered" if healthy else "broken"
