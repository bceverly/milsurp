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

**And a failure has to last before it is news.** Checkpoint Charlie's rate
limit refused a scan most days and its retry an hour later worked, so the
administrators got "stopped scraping" and "scraping again" nearly every day --
the same habit-forming noise as a nightly repeat, in pairs. So a failed scan
only records when the shop started failing (``Site.scan_failing_since``); the
scheduler mails "stopped" once the failure has outlasted
``scheduler.scan_alert_grace_minutes`` (three hours by default) and is still
there; and a healthy scan clears it, saying "scraping again" only to people
who were told it stopped. A blip that recovers inside the grace says nothing
at all.

Never raises. Alerting that can break a scan is worse than no alerting: it
turns every mail outage into a scraping outage, and the failure it reports is
its own.
"""

from __future__ import annotations

import html as _html
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ScanRun, ScanStatus, Site, User, UserRole, as_utc, utcnow
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


def _admin_addresses(session: Session) -> list[str]:
    users = (
        session.execute(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
        .scalars()
        .all()
    )
    return [user.email for user in users if user.email]


def _broken_message(site: Site, run: ScanRun, failed: int, since: datetime) -> tuple[str, str]:
    # Escaped, like the name: an administrator can rename a shop, and an error
    # can quote what the vendor sent.
    detail = _html.escape(run.error_message or "no detail recorded")
    subject = f"Milsurp: {site.name} stopped scraping"
    scans = f"{failed} scan{'s' if failed != 1 else ''}"
    html = (
        f"<p><strong>{_html.escape(site.name)}</strong> ({_html.escape(site.slug)}) "
        f"has been failing since "
        f"{since:%Y-%m-%d %H:%M} UTC: {scans} without one that worked. The last "
        f"error:</p>"
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
        f"<p><strong>{_html.escape(site.name)}</strong> ({_html.escape(site.slug)}) "
        f"completed a scan: "
        f"{run.items_found or 0:,} listing(s) seen, {run.items_new or 0:,} new.</p>"
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
    """Record this run's verdict, and mail a recovery that is owed.

    A failed run only starts the clock -- ``report_overdue`` decides later
    whether it lasted long enough to mail. A healthy one stops it, and says
    "scraping again" only if "stopped" was said. Returns ``"recovered"`` when
    that was mailed, for the caller's log and the tests. Called after the run
    is committed, so a message can never describe a scan that was then rolled
    back.
    """
    try:
        if run.status in IGNORED:
            return None
        if run.status not in HEALTHY:
            if site.scan_failing_since is None:
                # When the failing scan *started*, so it counts among the
                # scans the eventual message says failed.
                site.scan_failing_since = run.started_at or run.finished_at or utcnow()
                session.commit()
            return None

        owed = site.scan_failure_reported
        if site.scan_failing_since is not None or owed:
            site.scan_failing_since = None
            site.scan_failure_reported = False
            session.commit()
        if not owed:
            # Working, or a blip that recovered inside the grace: nobody was
            # told it stopped, so nobody is owed the news that it started.
            return None
        subject, html = _recovered_message(site, run)
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
        return "recovered"


def report_overdue(session: Session, grace: timedelta, now: datetime | None = None) -> list[str]:
    """Mail "stopped scraping" for every shop failing longer than ``grace``.

    Called on the scheduler's tick. Once per failure: the shop is marked told,
    and only a healthy scan clears that. A disabled shop is not reported --
    somebody switched it off and knows. Returns the slugs reported. Never
    raises, for the same reason ``consider`` does not.
    """
    told: list[str] = []
    try:
        cutoff = (as_utc(now) or utcnow()) - grace
        overdue = (
            session.execute(
                select(Site).where(
                    Site.enabled.is_(True),
                    Site.scan_failure_reported.is_(False),
                    Site.scan_failing_since.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        for site in overdue:
            since = as_utc(site.scan_failing_since)
            if since is None or since > cutoff:
                continue
            last = session.execute(
                select(ScanRun)
                .where(ScanRun.site_id == site.id, ScanRun.status.not_in((*HEALTHY, *IGNORED)))
                .order_by(ScanRun.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            failed = session.execute(
                select(func.count(ScanRun.id)).where(
                    ScanRun.site_id == site.id,
                    ScanRun.status.not_in((*HEALTHY, *IGNORED)),
                    # Naive, as the column is stored.
                    ScanRun.started_at >= since.replace(tzinfo=None),
                )
            ).scalar_one()
            # Marked first and either way: a shop with no administrator to
            # tell, or mail that will not go, must not be retried every tick.
            site.scan_failure_reported = True
            session.commit()
            if last is None:
                continue
            addresses = _admin_addresses(session)
            if not addresses:
                log.warning(
                    "No active administrator has an email address; %s not reported.", site.slug
                )
                continue
            subject, html = _broken_message(site, last, max(1, failed), since)
            _send(addresses, subject, html, site.slug)
            told.append(site.slug)
    except Exception:
        log.warning("Reporting failing shops failed", exc_info=True)
    return told
