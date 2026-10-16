"""The long jobs started from a button on Site settings.

Two reads of the manufacturers' own sites, each a command until 2026-10-13
and now a button too, and since 2026-10-14 a re-read of the catalog itself:

* **variants** -- app.services.makersites: each modern model's versions, with
  MSRP, barrel, finish and UPC, from the readers built for Ruger, Smith &
  Wesson, Kimber, Walther and Rock Island Armory (Armscor), and for every
  other maker from Bud's Gun Shop's catalog (makersites.BudsReader). They
  arrive as pending variants, approved on the Armory's Variants tab.
* **pages** -- app.services.makerpages: each modern model's own page on its
  manufacturer's site, suggested on the Armory's Manufacturer pages tab.
* **barrels** -- app.services.barrels, frames and serials: every stored
  gun's barrel length and threading, every handgun's frame size, and every
  gun's serial and year made, read
  again from its own words, as ``cli.py barrels-backfill`` does,
  and the listings of models still made matched to their versions again. No
  site is asked anything.

Neither runs on a clock. The button sets ``requested_at``; the scheduler
looks once a minute, runs one at a time on the reference worker, and records
how it went on the row the page shows.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ManufacturerJob, utcnow
from ..scrapers.base import ScrapeContext

#: The jobs, in the order the page shows them.
JOBS = ("variants", "pages", "barrels")


def job(session: Session, name: str) -> ManufacturerJob:
    if name not in JOBS:
        raise ValueError(f"No such job: {name!r}. The jobs are {', '.join(JOBS)}.")
    row = session.get(ManufacturerJob, name)
    if row is None:
        row = ManufacturerJob(name=name)
        session.add(row)
        session.commit()
    return row


def all_jobs(session: Session) -> list[ManufacturerJob]:
    return [job(session, name) for name in JOBS]


def ask(session: Session, name: str) -> ManufacturerJob:
    """Ask the scheduler to run *name* on its next minute."""
    row = job(session, name)
    row.requested_at = utcnow()
    session.commit()
    return row


def requested(session: Session) -> list[str]:
    """The jobs somebody has asked for, oldest request first."""
    return list(
        session.execute(
            select(ManufacturerJob.name)
            .where(ManufacturerJob.requested_at.is_not(None))
            .order_by(ManufacturerJob.requested_at)
        ).scalars()
    )


def _summary(name: str, counts: dict[str, Any]) -> str:
    if name == "barrels":
        return (
            f"Read {counts.get('examined', 0):,} gun(s): {counts.get('length', 0):,} barrel "
            f"length(s), {counts.get('threaded', 0):,} threaded, "
            f"{counts.get('not_threaded', 0):,} stated not threaded; "
            f"{counts.get('frames_stated', 0):,} frame size(s) stated and "
            f"{counts.get('frames_from_armory', 0):,} from the armory; "
            f"{counts.get('capacity_stated', 0):,} capacity value(s) stated and "
            f"{counts.get('capacity_from_armory', 0):,} from the armory; "
            f"{counts.get('years_stated', 0):,} year(s) made stated and "
            f"{counts.get('years_placed', 0):,} placed by serial; "
            f"{counts.get('relinked', 0):,} listing(s) matched to a different version."
        )
    if name == "variants":
        return (
            f"Read {counts.get('models', 0)} model(s): {counts.get('proposed', 0)} variant(s) "
            f"proposed, {counts.get('refreshed', 0)} brought up to date, "
            f"{counts.get('unread', 0)} with no page found; "
            f"{counts.get('models_proposed', 0)} new model(s) proposed for products no "
            "model names."
            + (
                f" {counts['errors']} maker site(s) answered with an error."
                if counts.get("errors")
                else ""
            )
        )
    return (
        f"Asked about {counts.get('asked', 0)} model(s): {counts.get('proposed', 0)} page(s) "
        f"suggested, {counts.get('confident', 0)} of them confident; "
        f"{counts.get('nothing', 0)} with no page found."
        + (f" {counts['unread']} maker site(s) could not be read." if counts.get("unread") else "")
    )


#: What a run's outcome is called on its row, and on Site settings.
OK = "ok"
WARNING = "warning"
FAILED = "failed"
INTERRUPTED = "interrupted"


def _status(name: str, counts: dict[str, Any]) -> str:
    """Finished, but some of what was asked could not be read: a maker's site
    that answered with an error. A model with nothing on its maker's site is
    an answer, not a warning."""
    trouble = counts.get("unread") if name == "pages" else counts.get("errors")
    return WARNING if trouble else OK


def reap_interrupted(session: Session) -> int:
    """Mark a run the service restarted under as interrupted, so Site
    settings does not say it is running for ever. Called as the scheduler
    starts. Returns how many there were."""
    stuck = list(
        session.execute(
            select(ManufacturerJob).where(ManufacturerJob.started_at.is_not(None))
        ).scalars()
    )
    for row in stuck:
        row.last_run_at = utcnow()
        row.last_status = INTERRUPTED
        row.last_summary = (
            f"Interrupted: the service restarted during the run, at {row.progress or 'its start'}."
        )[:500]
        row.started_at = row.progress = None
    session.commit()
    return len(stuck)


def run(session: Session, ctx: ScrapeContext, name: str, log: Callable[[str], None] = print) -> str:
    """Run one job now, recording how it went. Returns its summary.

    While it runs, its row says so: ``started_at``, and ``progress`` -- the
    last step the job reported, "Bud's Gun Shop: Sig Sauer (2 of 34 makers)".
    """
    from . import barrels, makerpages, makersites

    started = time.monotonic()
    row = job(session, name)
    row.requested_at = None
    row.started_at = utcnow()
    row.progress = "Starting"
    session.commit()

    def report(message: str) -> None:
        log(message)
        # A step heading, not every line: those begin with a space.
        if message and not message.startswith(" "):
            current = job(session, name)
            current.progress = message.strip()[:200]
            session.commit()

    try:
        if name == "barrels":
            report("Reading every stored gun")
            counts = barrels.refresh(session)
        elif name == "variants":
            counts = makersites.run(session, ctx, log=report)
        else:
            counts = makerpages.run(session, ctx, log=report)
        summary, status = _summary(name, counts), _status(name, counts)
    except Exception as exc:  # recorded where Site settings shows it
        session.rollback()
        summary, status = f"Failed: {exc}", FAILED
    row = job(session, name)
    row.last_run_at = utcnow()
    row.last_status = status
    row.last_summary = summary[:500]
    row.last_seconds = round(time.monotonic() - started, 1)
    row.started_at = row.progress = None
    session.commit()
    return summary
